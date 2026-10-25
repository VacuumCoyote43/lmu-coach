"""Voces neuronales de Microsoft Edge para el coach, con las de Windows de reserva.

Edge (paquete edge-tts) suena casi humano pero necesita internet y tarda ~1 s en generar cada frase. Por eso:
- Cada frase generada se guarda (caché en disco): la segunda vez suena al instante y sin internet.
- Las frases urgentes (frena, spotter, banderas…) se generan al elegir la voz, antes de salir a pista.
- Si no hay internet o Edge falla, esa frase la dice la voz de Windows.

VoiceSpeaker tiene la misma interfaz que speech.Speaker (say, set_voice, set_rate, voices, current, enabled…) y
su lista de voces incluye las de Edge y las de Windows: elegir una u otra cambia de motor.
"""
import asyncio
import hashlib
import io
import threading
import time
import wave

from .paths import DATA_DIR

CACHE_DIR = DATA_DIR / "voice_cache"
EDGE_VOICES = {
    "Álvaro (neural)": "es-ES-AlvaroNeural",
    "Elvira (neural)": "es-ES-ElviraNeural",
    "Ximena (neural)": "es-ES-XimenaNeural",
    "Jorge, México (neural)": "es-MX-JorgeNeural",
    "Dalia, México (neural)": "es-MX-DaliaNeural",
    "Tomás, Argentina (neural)": "es-AR-TomasNeural",
}
DEFAULT_VOICE = "Álvaro (neural)"
OFFLINE_RETRY_S = 60          # sin internet: no volver a intentarlo hasta pasado este tiempo

# lo que tiene que sonar al instante: se genera al elegir la voz
URGENT = [
    "frena", "Izquierda", "Derecha", "En medio", "Libre", "Libre a la izquierda", "Libre a la derecha",
    "Sigue a la izquierda", "Sigue a la derecha", "Sigues en medio", "Spotter listo",
    "vuelta invalidada", "vuelta no válida", "Verde, verde, verde", "Amarilla en todo el circuito. No adelantes",
    "Boxes cerrados", "Boxes abiertos", "Se relanza en esta vuelta", "Amarilla en el sector uno",
    "Amarilla en el sector dos", "Amarilla en el sector tres", "Bandera azul, deja pasar", "Quedan cinco minutos",
    "Última vuelta", "No te he entendido", "Avisos por voz activados", "Daños en la carrocería",
    "Daños fuertes en la carrocería", "Has perdido alguna pieza", "Motor sobrecalentado",
    "Entra en boxes al acabar esta vuelta", "Para en la próxima vuelta", "Frenos delanteros muy calientes",
    "Frenos traseros muy calientes", "El de delante entra en boxes", "El de detrás entra en boxes",
    "Hypercar detrás, déjale sitio", "LMP2 detrás, déjale sitio", "LMP3 detrás, déjale sitio",
    "GT3 detrás, déjale sitio", "LMGT3 detrás, déjale sitio", "Con este consumo llegas al final",
    "Objetivo conseguido", "Frena. Coche a la izquierda", "Repito la última respuesta",
]


def edge_rate(rate: float) -> str:
    """1,0 → «+0%», 1,2 → «+15%», 1,45 → «+34%» (la escala de Edge corre más que la de Windows)."""
    return f"{round((rate - 1.0) * 75):+d}%"


def cache_path(voice_id: str, rate: float, text: str):
    h = hashlib.sha1(f"{voice_id}|{edge_rate(rate)}|{text.strip()}".encode("utf-8")).hexdigest()[:20]
    return CACHE_DIR / voice_id / f"{h}.wav"


def available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("edge_tts") is not None and importlib.util.find_spec("av") is not None
    except Exception:
        return False


def _mp3_to_wav(mp3: bytes) -> bytes:
    import av
    out = io.BytesIO()
    pcm = bytearray()
    with av.open(io.BytesIO(mp3)) as c:
        res = av.AudioResampler(format="s16", layout="mono", rate=24000)
        for frame in c.decode(audio=0):
            for f in res.resample(frame):
                pcm += bytes(f.planes[0])[:f.samples * 2]
        for f in res.resample(None):
            pcm += bytes(f.planes[0])[:f.samples * 2]
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(bytes(pcm))
    return out.getvalue()


async def _synth(text: str, voice_id: str, rate: float) -> bytes:
    import edge_tts
    c = edge_tts.Communicate(text, voice_id, rate=edge_rate(rate), connect_timeout=4, receive_timeout=10)
    mp3 = bytearray()
    async for chunk in c.stream():
        if chunk["type"] == "audio":
            mp3 += chunk["data"]
    if not mp3:
        raise RuntimeError("Edge no devolvió audio")
    return _mp3_to_wav(bytes(mp3))


def generate(text: str, voice_id: str, rate: float):
    """Genera (si no está ya) y guarda la frase; devuelve la ruta del .wav. Lanza excepción si falla."""
    p = cache_path(voice_id, rate, text)
    if p.is_file():
        return p
    data = asyncio.run(_synth(text, voice_id, rate))
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(p)
    return p


def play(path) -> None:
    import winsound
    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)


def stop() -> None:
    import winsound
    winsound.PlaySound(None, winsound.SND_PURGE)


class VoiceSpeaker:
    """Edge con caché y Windows de reserva. Misma interfaz que speech.Speaker."""

    def __init__(self, enabled=True, voice: str | None = None, rate: float = 1.2):
        from .speech import Speaker
        self.enabled = enabled
        self.rate = rate
        self.edge_ok = available()
        self.win = Speaker(enabled, voice if voice and voice not in EDGE_VOICES else None, rate)
        self.voice = voice or (DEFAULT_VOICE if self.edge_ok else None)
        self._seq = 0
        self._lock = threading.Lock()
        self._offline_until = 0.0
        self.last_error = None
        self._warm_key = None
        self.on_prewarm = None           # función(hechas, total) para enseñar el avance

    # --- voces --------------------------------------------------------------------------

    @property
    def edge(self) -> bool:
        return self.edge_ok and self.voice in EDGE_VOICES

    @property
    def voices(self) -> list[str]:
        return (list(EDGE_VOICES) if self.edge_ok else []) + list(self.win.voices)

    @property
    def current(self) -> str | None:
        return self.voice if self.edge else self.win.current

    def start(self):
        self.win.start()
        if self.edge:
            self.prewarm()

    def set_voice(self, name: str):
        self.voice = name
        if name in EDGE_VOICES:
            self.prewarm()
        else:
            self.win.set_voice(name)

    def set_rate(self, rate: float):
        self.rate = rate
        self.win.set_rate(rate)
        if self.edge:
            self.prewarm()

    # --- hablar ---------------------------------------------------------------------------

    def say(self, text: str):
        if not self.enabled or not text:
            return
        if not self.edge:
            self.win.say(text)
            return
        with self._lock:
            self._seq += 1
            seq = self._seq
        voice_id = EDGE_VOICES[self.voice]
        p = cache_path(voice_id, self.rate, text)
        if p.is_file():
            play(p)
            return
        if time.monotonic() < self._offline_until:
            self._fallback(text)
            return
        threading.Thread(target=self._gen_and_play, args=(text, voice_id, self.rate, seq), daemon=True).start()

    def _gen_and_play(self, text, voice_id, rate, seq):
        try:
            p = generate(text, voice_id, rate)
        except Exception as e:
            self.last_error = str(e)
            self._offline_until = time.monotonic() + OFFLINE_RETRY_S
            if seq == self._seq:
                self._fallback(text)
            return
        if seq == self._seq:             # si mientras tanto se pidió otra frase, esta ya no se dice
            play(p)

    def _fallback(self, text):
        stop()
        self.win.say(text)

    # --- frases urgentes ---------------------------------------------------------------------

    def prewarm(self, extra: list[str] | None = None):
        """Genera en segundo plano las frases urgentes con la voz y velocidad actuales."""
        if not self.edge:
            return
        key = (self.voice, self.rate)
        if key == self._warm_key:
            return
        self._warm_key = key
        voice_id, rate = EDGE_VOICES[self.voice], self.rate
        phrases = list(dict.fromkeys(URGENT + (extra or [])))

        def work():
            todo = [t for t in phrases if not cache_path(voice_id, rate, t).is_file()]
            done = len(phrases) - len(todo)
            if self.on_prewarm:
                self.on_prewarm(done, len(phrases))
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(4) as ex:
                for ok in ex.map(lambda t: self._safe_gen(t, voice_id, rate), todo):
                    done += 1
                    if self.on_prewarm:
                        self.on_prewarm(done, len(phrases))
                    if not ok and (self._warm_key != key):
                        return
        threading.Thread(target=work, daemon=True).start()

    def _safe_gen(self, text, voice_id, rate) -> bool:
        try:
            generate(text, voice_id, rate)
            return True
        except Exception as e:
            self.last_error = str(e)
            return False

    def close(self):
        try:
            stop()
        except Exception:
            pass
        self.win.close()
