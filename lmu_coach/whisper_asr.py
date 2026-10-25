"""Radio con Whisper (faster-whisper, sin conexión): graba mientras mantienes el botón, al soltar transcribe y
busca tu frase más parecida. Entiende bien con ruido; tarda ~0,5 s con el modelo «base» en un PC normal.

El modelo se descarga una vez (Ajustes › Radio) a la carpeta de datos de la app.
"""
import queue
import re
import threading
from difflib import SequenceMatcher

from .paths import DATA_DIR

MODELS_DIR = DATA_DIR / "models"
SIZES = {"tiny": "muy rápido (~75 MB, falla algo más)", "base": "recomendado (~145 MB, ~0,5 s)",
         "small": "más preciso (~480 MB, ~2 s)"}


def available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("faster_whisper") is not None
    except Exception:
        return False


def _model_dir(size: str):
    return MODELS_DIR / f"faster-whisper-{size}"


def is_downloaded(size: str) -> bool:
    d = _model_dir(size)
    return (d / "model.bin").is_file() and (d / "config.json").is_file()


FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
REPO = "https://huggingface.co/Systran/faster-whisper-{size}/resolve/main/{name}"


def download(size: str, progress=None, cancel=None) -> str | None:
    """Descarga el modelo (una vez) a la carpeta de datos. progress(hechos, total) en bytes; cancel() → True
    para parar. Devuelve un error en texto o None si todo bien. Cada archivo se baja a .part y se renombra
    al terminar: una descarga cortada no deja un modelo roto."""
    import urllib.request
    d = _model_dir(size)
    d.mkdir(parents=True, exist_ok=True)
    try:
        sizes = {}
        for name in FILES:                       # tamaños primero, para que la barra sepa el total
            req = urllib.request.Request(REPO.format(size=size, name=name), method="HEAD")
            with urllib.request.urlopen(req, timeout=20) as r:
                sizes[name] = int(r.headers.get("Content-Length") or 0)
        total, done = sum(sizes.values()), 0
        for name in FILES:
            dest = d / name
            if dest.is_file() and dest.stat().st_size == sizes[name]:
                done += sizes[name]
                if progress:
                    progress(done, total)
                continue
            part = dest.with_suffix(dest.suffix + ".part")
            with urllib.request.urlopen(REPO.format(size=size, name=name), timeout=30) as r, open(part, "wb") as f:
                while True:
                    if cancel and cancel():
                        f.close()
                        part.unlink(missing_ok=True)
                        return "Descarga cancelada"
                    chunk = r.read(1 << 18)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            part.replace(dest)
        return None if is_downloaded(size) else "La descarga no se completó"
    except Exception as e:
        return f"No se pudo descargar el modelo: {e}"


def _norm(t: str) -> str:
    from .radio import normalize
    return normalize(t)


def best_phrase(text: str, phrases: list[str]) -> tuple[str | None, float]:
    """La frase de la lista que más se parece a lo transcrito, con su parecido (0..1)."""
    h = _norm(text)
    if not h:
        return None, 0.0
    hw = set(h.split())
    best, score = None, 0.0
    for p in phrases:
        n = _norm(p)
        if not n:
            continue
        ratio = SequenceMatcher(None, h, n).ratio()
        pw = set(n.split())
        cover = len(hw & pw) / len(pw) if pw else 0.0          # palabras de la frase que has dicho
        extra = len(hw - pw) / max(len(hw), 1)                  # palabras de más
        s = max(ratio, cover * (1 - 0.5 * extra))
        if s > score:
            best, score = p, s
    return best, score


class WhisperListener:
    """Misma interfaz que los otros: start(frases), listen(on/off), results, error, ready, close()."""
    GRACE_S = 4.0            # tras soltar, tiempo para transcribir

    def __init__(self, size: str = "base"):
        self.size = size if size in SIZES else "base"
        self.results: queue.Queue = queue.Queue()
        self.error: str | None = None
        self.ready = False
        self._model = None
        self._phrases: list[str] = []
        self._rec = None
        self._loading = False
        self.last_text = None

    def start(self, phrases: list[str]):
        self._phrases = list(phrases)
        if self._model is None and not self._loading:
            self._loading = True
            threading.Thread(target=self._load, daemon=True).start()

    set_phrases = start

    def _load(self):
        try:
            if not is_downloaded(self.size):
                self.error = (f"Falta el modelo de Whisper «{self.size}»: descárgalo en Ajustes › Radio")
                return
            from faster_whisper import WhisperModel
            self._model = WhisperModel(str(_model_dir(self.size)), device="cpu", compute_type="int8", cpu_threads=4)
            self.ready, self.error = True, None
        except Exception as e:
            self.error = f"Whisper: {e}"
        finally:
            self._loading = False

    def listen(self, on: bool):
        from .micmeter import Recorder
        if on:
            self._rec = Recorder()
            if not self._rec.start():
                self.error = self._rec.error
                self._rec = None
            return
        if self._rec is None:
            return
        audio, self._rec = self._rec.stop(), None
        threading.Thread(target=self._transcribe, args=(audio,), daemon=True).start()

    def _transcribe(self, audio):
        import numpy as np
        if self._model is None:
            for _ in range(100):                 # aún cargando: esperar un poco
                if self._model is not None or self.error:
                    break
                threading.Event().wait(0.05)
        if self._model is None or len(audio) < 16000 * 0.3 or float(np.abs(audio).max()) < 0.01:
            self.results.put((None, 0.0))        # nada que entender (silencio o demasiado corto)
            return
        try:
            prompt = "Radio de carreras. " + ", ".join(self._phrases[:40]) + "."
            segs, _ = self._model.transcribe(audio, language="es", beam_size=1, initial_prompt=prompt,
                                             condition_on_previous_text=False, without_timestamps=True,
                                             vad_filter=False)
            text = " ".join(s.text for s in segs).strip()
        except Exception as e:
            self.error = f"Whisper: {e}"
            self.results.put((None, 0.0))
            return
        self.last_text = text
        phrase, score = best_phrase(text, self._phrases)
        # con parecido suficiente, la frase; si no, lo transcrito tal cual (para que veas qué ha oído)
        self.results.put((phrase if phrase and score >= 0.6 else re.sub(r"[.?!¿¡]", "", text), score))

    def close(self):
        if self._rec is not None:
            try:
                self._rec.stop()
            except Exception:
                pass
            self._rec = None
        self._model = None
