"""Radio con el ingeniero: pulsas un botón (del volante o una tecla), dices una frase y te responde.

Las frases y lo que contesta cada una los eliges tú (Ajustes › Radio). Las respuestas son plantillas con
datos entre llaves: «Te quedan {combustible}, para {combustible_vueltas}». FIELDS es todo lo que se puede
pedir; el coach rellena una «foto» (snapshot) con los datos del momento y render() la convierte en frase.

El reconocimiento es el de Windows (System.Speech, sin conexión), con una lista cerrada de frases: así
acierta aunque haya ruido. Un proceso de PowerShell escucha mientras el botón está pulsado.
"""
import ctypes as C
import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass


# --------------------------------------------------------------------------- formatos para la voz

def _dec(x: float, nd=1) -> str:
    """12.34 → «12,3» (la voz de Windows lee bien la coma decimal)."""
    s = f"{x:.{nd}f}".replace(".", ",")
    return s[:-2] if nd == 1 and s.endswith(",0") else s


def _secs(x: float) -> str:
    return f"{_dec(abs(x))} segundos" if abs(x) >= 1.05 or abs(x) < 0.95 else "un segundo"


def _lap(t) -> str | None:
    if not t or t <= 0:
        return None
    from .speech import lap_time_es
    return lap_time_es(t)


def _laps(n: float) -> str:
    n = max(0.0, n)
    if n < 1:
        return "menos de una vuelta"
    return "una vuelta" if int(n) == 1 else f"{int(n)} vueltas"


def _wheels(vals, fmt) -> str | None:
    if not vals or len(vals) != 4 or any(v is None for v in vals):
        return None
    return (f"delanteras {fmt(vals[0])} y {fmt(vals[1])}, traseras {fmt(vals[2])} y {fmt(vals[3])}")


def _gap_name(snap, side) -> str | None:
    r = snap.get("race") or {}
    g = r.get(side)
    return None if g is None else _secs(g)


# --------------------------------------------------------------------------- catálogo de datos

@dataclass(frozen=True)
class Field:
    key: str
    group: str
    label: str
    example: str
    get: object        # función snapshot -> texto o None


def _tyre_state(snap):
    temps, opt = snap.get("tyre_temp"), snap.get("tyre_opt")
    if not temps or not opt:
        return None
    avg_f, avg_r = (temps[0] + temps[1]) / 2, (temps[2] + temps[3]) / 2
    word = lambda t: "frías" if t < opt - 15 else "calientes" if t > opt + 15 else "en temperatura"
    a, b = word(avg_f), word(avg_r)
    return f"todas {a}" if a == b else f"delanteras {a}, traseras {b}"


def _damage(snap):
    d = snap.get("damage")
    if not d:
        return "sin daños"
    parts = []
    if d.get("level"):
        parts.append("daños fuertes en la carrocería" if d["level"] >= 2 else "algún daño en la carrocería")
    if d.get("detached"):
        parts.append("has perdido alguna pieza")
    if d.get("flat"):
        parts.append("tienes un pinchazo")
    if d.get("overheating"):
        parts.append("el motor se calienta")
    return ", ".join(parts) or "sin daños"


def _remaining(snap):
    tl, ll = snap.get("time_left"), snap.get("laps_left")
    if ll is not None:
        return _laps(ll)
    if tl is not None and tl > 0:
        m, s = divmod(int(tl), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h} {'hora' if h == 1 else 'horas'} y {m} minutos"
        return f"{m} minutos" if m >= 2 else f"{m * 60 + s} segundos"
    return None


def _pit(snap):
    p = snap.get("pit_text")
    return p


def _trend(snap, side):
    r = snap.get("race") or {}
    t = r.get("trend_" + side)
    if t is None or abs(t) < 0.1:
        return None
    if side == "ahead":
        return f"{'recortas' if t < 0 else 'pierdes'} {_dec(abs(t))} por vuelta"
    return f"{'se acerca' if t < 0 else 'se aleja'} {_dec(abs(t))} por vuelta"


def _goal(snap):
    g, best = snap.get("goal"), snap.get("best_lap")
    if not g:
        return "no tienes ningún objetivo fijado en este circuito con este coche"
    if not best:
        return f"tu objetivo es {_lap(g)}"
    gap = best - g
    return "objetivo conseguido" if gap <= 0 else f"te faltan {_secs(gap)} para tu objetivo"


def _delta(snap):
    d = snap.get("delta")
    if d is None:
        return None
    return "igual que tu referencia" if abs(d) < 0.05 else f"{'más' if d > 0 else 'menos'} {_secs(d)}"


def _position(snap):
    r = snap.get("race") or {}
    if not r.get("pos"):
        return None
    return f"{r['pos']} de {r['of']}" + (f" en {r['cls']}" if r.get("cls") else "")


FIELDS = [
    # coche
    Field("combustible", "Coche", "Combustible que queda", "23,4 litros",
          lambda s: f"{_dec(s['fuel'])} litros" if s.get("fuel") is not None else None),
    Field("combustible_vueltas", "Coche", "Vueltas con ese combustible", "8 vueltas",
          lambda s: _laps(s["fuel"] / s["fuel_pl"]) if s.get("fuel") is not None and s.get("fuel_pl") else None),
    Field("consumo", "Coche", "Consumo por vuelta", "2,9 litros por vuelta",
          lambda s: f"{_dec(s['fuel_pl'], 2)} litros por vuelta" if s.get("fuel_pl") else None),
    Field("energia", "Coche", "Energía virtual que queda", "62 por ciento",
          lambda s: f"{s['ve']:.0f} por ciento" if s.get("ve") is not None else None),
    Field("energia_vueltas", "Coche", "Vueltas con esa energía", "11 vueltas",
          lambda s: _laps(s["ve"] / s["ve_pl"]) if s.get("ve") is not None and s.get("ve_pl") else None),
    Field("consumo_energia", "Coche", "Gasto de energía por vuelta", "5,4 por ciento por vuelta",
          lambda s: f"{_dec(s['ve_pl'])} por ciento por vuelta" if s.get("ve_pl") else None),
    Field("neumaticos", "Coche", "Estado de temperatura de los neumáticos", "todas en temperatura", _tyre_state),
    Field("neumaticos_temp", "Coche", "Temperatura de cada neumático", "delanteras 85 y 87, traseras 90 y 91",
          lambda s: _wheels(s.get("tyre_temp"), lambda v: f"{v:.0f}")),
    Field("presiones", "Coche", "Presión de cada neumático (en caliente)", "delanteras 171 y 172, traseras 166 y 167",
          lambda s: _wheels(s.get("tyre_pressure"), lambda v: f"{v:.0f}")),
    Field("desgaste", "Coche", "Neumático que queda (el más gastado)", "queda un 82 por ciento",
          lambda s: f"queda un {min(s['tyre_wear']) * 100:.0f} por ciento" if s.get("tyre_wear") else None),
    Field("desgaste_ruedas", "Coche", "Neumático que queda en cada rueda", "delanteras 84 y 85, traseras 82 y 83",
          lambda s: _wheels(s.get("tyre_wear"), lambda v: f"{v * 100:.0f}")),
    Field("frenos_temp", "Coche", "Temperatura de cada freno", "delanteras 620 y 615, traseras 480 y 470",
          lambda s: _wheels(s.get("brake_temp"), lambda v: f"{v:.0f}")),
    Field("agua", "Coche", "Temperatura del agua", "92 grados",
          lambda s: f"{s['water']:.0f} grados" if s.get("water") else None),
    Field("aceite", "Coche", "Temperatura del aceite", "104 grados",
          lambda s: f"{s['oil']:.0f} grados" if s.get("oil") else None),
    Field("danos", "Coche", "Daños", "sin daños", _damage),
    # vuelta
    Field("vuelta", "Vuelta", "Vuelta en la que vas", "vuelta 12",
          lambda s: f"vuelta {s['lap']}" if s.get("lap") is not None else None),
    Field("ultima_vuelta", "Vuelta", "Tiempo de la última vuelta", "uno, cuarenta y seis, seis cinco ocho",
          lambda s: _lap(s.get("last_lap"))),
    Field("mejor_vuelta", "Vuelta", "Tu mejor vuelta de la sesión", "uno, cuarenta y seis, dos nueve uno",
          lambda s: _lap(s.get("best_lap"))),
    Field("referencia", "Vuelta", "Tiempo de tu referencia", "uno, cuarenta y cinco, nueve siete siete",
          lambda s: _lap(s.get("ref_time"))),
    Field("delta", "Vuelta", "Delta con tu referencia ahora", "más 0,3 segundos", _delta),
    Field("vuelta_ideal", "Vuelta", "Vuelta ideal de la sesión", "uno, cuarenta y cinco, ocho", lambda s: _lap(s.get("ideal"))),
    Field("objetivo", "Vuelta", "Cuánto te falta para tu objetivo", "te faltan 0,4 segundos para tu objetivo", _goal),
    # carrera
    Field("posicion", "Carrera", "Posición en tu clase", "4 de 12 en GT3", _position),
    Field("delante", "Carrera", "Diferencia con el de delante", "1,2 segundos", lambda s: _gap_name(s, "ahead")),
    Field("detras", "Carrera", "Diferencia con el de detrás", "0,8 segundos", lambda s: _gap_name(s, "behind")),
    Field("nombre_delante", "Carrera", "Piloto de delante", "Rossi", lambda s: s.get("ahead_name")),
    Field("nombre_detras", "Carrera", "Piloto de detrás", "Vettel", lambda s: s.get("behind_name")),
    Field("tendencia_delante", "Carrera", "Si recortas o pierdes con el de delante", "recortas 0,3 por vuelta",
          lambda s: _trend(s, "ahead")),
    Field("tendencia_detras", "Carrera", "Si el de detrás se acerca o se aleja", "se acerca 0,2 por vuelta",
          lambda s: _trend(s, "behind")),
    Field("restante", "Carrera", "Lo que queda de carrera", "23 minutos", _remaining),
    Field("parada", "Carrera", "Estrategia: cuándo parar y cuánto repostar",
          "Para en dos vueltas, reposta treinta litros. Volverías cuarto", _pit),
    Field("paradas", "Carrera", "Paradas que llevas", "una parada",
          lambda s: None if s.get("stops") is None else
          ("ninguna parada" if s["stops"] == 0 else "una parada" if s["stops"] == 1 else f"{s['stops']} paradas")),
    # pista
    Field("temp_pista", "Pista", "Temperatura de la pista", "31 grados",
          lambda s: f"{s['track_temp']:.0f} grados" if s.get("track_temp") is not None else None),
    Field("temp_aire", "Pista", "Temperatura del aire", "22 grados",
          lambda s: f"{s['air_temp']:.0f} grados" if s.get("air_temp") is not None else None),
    Field("lluvia", "Pista", "Lluvia", "no llueve",
          lambda s: None if s.get("rain") is None else "no llueve" if s["rain"] < 0.05 else
          "llueve un poco" if s["rain"] < 0.4 else "llueve mucho"),
    Field("hora", "Pista", "Hora del ordenador", "las 21:40", lambda s: time.strftime("las %H:%M")),
]
BY_KEY = {f.key: f for f in FIELDS}

DEFAULT_COMMANDS = [
    {"phrases": ["combustible", "cuánto combustible me queda"],
     "say": "{combustible}, para {combustible_vueltas}"},
    {"phrases": ["energía", "cuánta energía me queda"], "say": "{energia}, para {energia_vueltas}"},
    {"phrases": ["cuándo paro", "estrategia"], "say": "{parada}"},
    {"phrases": ["el de delante", "a cuánto va el de delante"], "say": "{nombre_delante} a {delante}. {tendencia_delante}"},
    {"phrases": ["el de detrás", "a cuánto va el de detrás"], "say": "{nombre_detras} a {detras}. {tendencia_detras}"},
    {"phrases": ["posición", "en qué posición voy"], "say": "{posicion}"},
    {"phrases": ["cuánto queda"], "say": "Quedan {restante}"},
    {"phrases": ["neumáticos", "cómo van los neumáticos"], "say": "{neumaticos}. {desgaste}"},
    {"phrases": ["presiones"], "say": "{presiones}"},
    {"phrases": ["frenos"], "say": "{frenos_temp}"},
    {"phrases": ["mi mejor vuelta"], "say": "{mejor_vuelta}"},
    {"phrases": ["última vuelta"], "say": "{ultima_vuelta}"},
    {"phrases": ["delta"], "say": "{delta}"},
    {"phrases": ["objetivo"], "say": "{objetivo}"},
    {"phrases": ["pista", "cómo está la pista"], "say": "Pista {temp_pista}, aire {temp_aire}, {lluvia}"},
    {"phrases": ["daños"], "say": "{danos}"},
    {"phrases": ["motor"], "say": "Agua {agua}, aceite {aceite}"},
    {"phrases": ["repite"], "say": "{repetir}"},
]
REPEAT = "{repetir}"
_PH = re.compile(r"\{(\w+)\}")


def _value(key: str, snap: dict, examples: bool):
    f = BY_KEY.get(key)
    if f is None:
        return "{" + key + "}"
    if examples:
        return f.example
    try:
        return f.get(snap) or None
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def render(template: str, snap: dict, examples=False) -> str:
    """Rellena la plantilla. Cada trozo de la frase (entre comas o puntos) que tenga un dato sin valor ahora
    se quita entero; si no queda nada, «Sin datos ahora»."""
    parts = re.split(r"([.,;])", template)
    out = []
    for i in range(0, len(parts), 2):
        clause, sep = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        missing = False

        def sub(m):
            nonlocal missing
            v = _value(m.group(1), snap, examples)
            if v is None:
                missing = True
                return ""
            return v

        text = _PH.sub(sub, clause)
        if not missing and text.strip():
            out.append(text.strip() + sep)
    txt = " ".join(out).strip(" ,;")
    if not txt:
        return "Sin datos ahora"
    txt = re.sub(r"([.] )(\w)", lambda m: m.group(1) + m.group(2).upper(), txt)   # mayúscula tras punto
    return txt[:1].upper() + txt[1:]


def normalize(text: str) -> str:
    """Sin tildes ni mayúsculas ni signos: así se compara lo oído con las frases."""
    import unicodedata
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ ]+", " ", t).strip()


def find_command(heard: str, commands: list) -> dict | None:
    h = normalize(heard)
    for c in commands:
        if any(normalize(p) == h for p in c.get("phrases", [])):
            return c
    return None


def all_phrases(commands: list) -> list[str]:
    """Frases para el reconocedor: con sus tildes (se pronuncian distinto), sin signos ni repetidas."""
    seen, out = set(), []
    for c in commands:
        for p in c.get("phrases", []):
            n = normalize(p)
            if n and n not in seen:
                seen.add(n)
                out.append(re.sub(r"[¿?¡!.,;:|]+", " ", p.lower()).strip())
    return out


# --------------------------------------------------------------------------- botón para hablar

class JOYINFOEX(C.Structure):
    _fields_ = [(n, C.c_uint32) for n in ("dwSize", "dwFlags", "dwXpos", "dwYpos", "dwZpos", "dwRpos", "dwUpos",
                                          "dwVpos", "dwButtons", "dwButtonNumber", "dwPOV", "dwReserved1",
                                          "dwReserved2")]


class JOYCAPSW(C.Structure):
    _fields_ = [("wMid", C.c_ushort), ("wPid", C.c_ushort), ("szPname", C.c_wchar * 32)] + \
               [(f"_r{i}", C.c_uint32) for i in range(40)]


JOY_RETURNBUTTONS = 0x80


def joy_buttons(dev: int) -> int | None:
    """Botones pulsados del mando «dev» (bits) o None si no está conectado."""
    j = JOYINFOEX()
    j.dwSize = C.sizeof(j)
    j.dwFlags = JOY_RETURNBUTTONS
    try:
        if C.windll.winmm.joyGetPosEx(dev, C.byref(j)) != 0:
            return None
    except (AttributeError, OSError):
        return None
    return j.dwButtons


def joy_name(dev: int) -> str:
    caps = JOYCAPSW()
    try:
        if C.windll.winmm.joyGetDevCapsW(dev, C.byref(caps), C.sizeof(caps)) == 0:
            return caps.szPname or f"Mando {dev + 1}"
    except (AttributeError, OSError):
        pass
    return f"Mando {dev + 1}"


def key_down(vk: int) -> bool:
    try:
        return bool(C.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except (AttributeError, OSError):
        return False


def button_label(b: dict | None) -> str:
    if not b:
        return "sin asignar"
    if b.get("type") == "key":
        return f"tecla {b.get('name') or b.get('vk')}"
    return f"botón {b.get('button', 0) + 1} de {b.get('name') or 'mando'}"


def button_down(b: dict | None) -> bool:
    if not b:
        return False
    if b.get("type") == "key":
        return key_down(int(b.get("vk", 0)))
    bits = joy_buttons(int(b.get("dev", 0)))
    return bool(bits is not None and bits & (1 << int(b.get("button", 0))))


def pressed_now() -> dict | None:
    """Lo primero que esté pulsado ahora (para asignar el botón): un botón de cualquier mando o una tecla."""
    for dev in range(16):
        bits = joy_buttons(dev)
        if bits:
            n = (bits & -bits).bit_length() - 1
            return {"type": "joy", "dev": dev, "button": n, "name": joy_name(dev)}
    names = {0x70 + i: f"F{i + 1}" for i in range(12)}
    names.update({0x20: "Espacio", 0x0D: "Intro", 0x09: "Tab", 0x14: "Bloq Mayús", 0xA2: "Ctrl izq.",
                  0xA3: "Ctrl dcha.", 0xA4: "Alt izq.", 0xA0: "Mayús izq.", 0xA1: "Mayús dcha."})
    names.update({0x30 + i: str(i) for i in range(10)})
    names.update({0x41 + i: chr(0x41 + i) for i in range(26)})
    names.update({0x60 + i: f"Num {i}" for i in range(10)})
    for vk, name in names.items():
        if key_down(vk):
            return {"type": "key", "vk": vk, "name": name}
    return None


# --------------------------------------------------------------------------- reconocimiento de voz

_ASR = r"""
[Console]::InputEncoding = [Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$eng = $null
try {
  $rec = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() |
    Where-Object { $_.Culture.Name -like 'es*' } | Select-Object -First 1
  if (-not $rec) { [Console]::Out.WriteLine('__error__ No hay reconocimiento de voz en español instalado'); exit }
  $eng = New-Object System.Speech.Recognition.SpeechRecognitionEngine($rec)
  $eng.SetInputToDefaultAudioDevice()
} catch { [Console]::Out.WriteLine('__error__ ' + $_.Exception.Message); exit }
$script:best = $null
Register-ObjectEvent $eng SpeechRecognized -Action {
  $r = $Event.SourceEventArgs.Result
  [Console]::Out.WriteLine('__oido__ ' + [math]::Round($r.Confidence, 2) + '|' + $r.Text)
} | Out-Null
Register-ObjectEvent $eng SpeechRecognitionRejected -Action {
  [Console]::Out.WriteLine('__nada__')
} | Out-Null
[Console]::Out.WriteLine('__listo__')
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null -or $line -eq '__salir__') { break }
  if ($line.StartsWith('__frases__ ')) {
    try { $eng.RecognizeAsyncCancel() } catch {}
    $eng.UnloadAllGrammars()
    $ch = New-Object System.Speech.Recognition.Choices
    $ch.Add([string[]]($line.Substring(11).Split('|') | Where-Object { $_ }))
    $gb = New-Object System.Speech.Recognition.GrammarBuilder
    $gb.Culture = $eng.RecognizerInfo.Culture
    $gb.Append($ch)
    $eng.LoadGrammar((New-Object System.Speech.Recognition.Grammar($gb)))
  } elseif ($line -eq '__on__') {
    try { $eng.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple) } catch {}
  } elseif ($line -eq '__off__') {
    try { $eng.RecognizeAsyncStop() } catch {}
  }
}
"""

CREATE_NO_WINDOW = 0x08000000


class Listener:
    """Proceso de PowerShell que escucha el micrófono mientras se le pide. Los resultados llegan a .results
    como (texto, confianza) o (None, 0) si oyó algo que no es ninguna frase."""

    def __init__(self):
        self.results: queue.Queue = queue.Queue()
        self.error: str | None = None
        self.ready = False
        self._proc = None
        self._lock = threading.Lock()
        self._phrases = None

    def start(self, phrases: list[str]):
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                try:
                    self._proc = subprocess.Popen(
                        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _ASR],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
                except OSError as e:
                    self.error = str(e)
                    return
                self._phrases = None
                threading.Thread(target=self._read, args=(self._proc,), daemon=True).start()
        self.set_phrases(phrases)

    def set_phrases(self, phrases: list[str]):
        if phrases and phrases != self._phrases:
            self._phrases = list(phrases)
            self._send("__frases__ " + "|".join(p.replace("|", " ") for p in phrases))

    def _read(self, proc):
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip().lstrip("﻿")
            if line.startswith("__oido__ "):
                conf, _, text = line[9:].partition("|")
                try:
                    self.results.put((text, float(conf.replace(",", "."))))
                except ValueError:
                    self.results.put((text, 0.0))
            elif line == "__nada__":
                self.results.put((None, 0.0))
            elif line == "__listo__":
                self.ready = True
            elif line.startswith("__error__"):
                self.error = line[10:]

    def _send(self, line: str):
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                return
            try:
                self._proc.stdin.write((line + "\n").encode("utf-8"))
                self._proc.stdin.flush()
            except OSError:
                self._proc = None

    def listen(self, on: bool):
        self._send("__on__" if on else "__off__")

    def close(self):
        self._send("__salir__")
        with self._lock:
            if self._proc:
                try:
                    self._proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None


class ModernListener:
    """El reconocedor moderno de Windows (WinRT, red neuronal, sin conexión): bastante mejor que System.Speech.
    Misma interfaz que Listener. Con el botón pulsado escucha en sesión continua; al soltar, termina la frase."""

    CONF = {0: 0.9, 1: 0.7, 2: 0.45, 3: 0.0}      # Alta, Media, Baja, Rechazada

    def __init__(self):
        self.results: queue.Queue = queue.Queue()
        self.error: str | None = None
        self.ready = False
        self._loop = None
        self._rec = None
        self._phrases = None
        self._running = False
        self._thread = None

    @staticmethod
    def available() -> bool:
        try:
            from winrt.windows.media.speechrecognition import SpeechRecognizer
            return any(l.language_tag.lower().startswith("es") for l in SpeechRecognizer.supported_grammar_languages)
        except Exception:
            return False

    def _ensure_loop(self):
        if self._loop is None:
            import asyncio
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
            self._thread.start()

    def _run(self, coro):
        import asyncio
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def start(self, phrases: list[str]):
        self._ensure_loop()
        if phrases and phrases != self._phrases:
            self._phrases = list(phrases)
            self._run(self._build(list(phrases)))

    set_phrases = start

    async def _build(self, phrases):
        from winrt.windows.globalization import Language
        from winrt.windows.media.speechrecognition import (SpeechRecognitionListConstraint, SpeechRecognizer,
                                                            SpeechRecognitionResultStatus)
        try:
            if self._rec is not None and self._running:
                await self._rec.continuous_recognition_session.cancel_async()
                self._running = False
            lang = next((l for l in SpeechRecognizer.supported_grammar_languages
                         if l.language_tag.lower().startswith("es")), Language("es-ES"))
            rec = SpeechRecognizer(lang)
            rec.constraints.append(SpeechRecognitionListConstraint(phrases))
            r = await rec.compile_constraints_async()
            if r.status != SpeechRecognitionResultStatus.SUCCESS:
                self.error = f"No se pudieron preparar las frases (código {int(r.status)})"
                return
            rec.continuous_recognition_session.add_result_generated(self._on_result)
            self._rec, self.ready, self.error = rec, True, None
        except Exception as e:
            self.error = f"Reconocimiento de voz de Windows: {e}"

    def _on_result(self, _session, args):
        res = args.result
        raw = float(getattr(res, "raw_confidence", 0.0) or 0.0)
        conf = max(raw, self.CONF.get(int(res.confidence), 0.0)) if int(res.confidence) != 3 else raw
        self.results.put((res.text or None, conf))

    def listen(self, on: bool):
        if self._loop is None:
            return
        self._run(self._listen(on))

    async def _listen(self, on):
        if self._rec is None:
            return
        try:
            sess = self._rec.continuous_recognition_session
            if on and not self._running:
                await sess.start_async()
                self._running = True
            elif not on and self._running:
                self._running = False
                await sess.stop_async()             # termina la frase en curso y da su resultado
        except Exception as e:
            self._running = False
            self.error = f"Micrófono: {e}"

    def close(self):
        if self._loop is not None:
            try:
                self._run(self._listen(False)).result(2)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop = None


def make_listener(engine: str = "auto"):
    """«moderno» (WinRT), «clasico» (System.Speech) o «auto»: el moderno si está disponible."""
    if engine in ("auto", "moderno") and ModernListener.available():
        return ModernListener()
    return Listener()


class Radio:
    """Pulsar para hablar: con el botón pulsado escucha; al soltarlo (o al reconocer una frase) responde.
    update() se llama en cada vuelta del bucle del coach y devuelve la frase a decir (o None)."""
    MAX_LISTEN_S = 8.0
    GRACE_S = 1.2           # tras soltar el botón, aún espera el resultado este tiempo

    def __init__(self, listener=None):
        self.listener = listener
        self._engine = None
        self.listening = False
        self._down = False
        self._since = 0.0
        self._released_at = None
        self.last_answer = None
        self.last_heard = None

    def update(self, cfg: dict, snapshot_fn, now: float | None = None) -> tuple[str, str] | None:
        """(«listening»|«answer»|«unknown», texto) cuando hay algo que hacer."""
        now = time.monotonic() if now is None else now
        r = cfg.get("radio") or {}
        if not r.get("on"):
            return None
        commands = r.get("commands") or DEFAULT_COMMANDS
        engine = r.get("engine", "auto")
        if self.listener is None or (self._engine is not None and engine != self._engine):
            if self.listener is not None:
                self.listener.close()
            self.listener, self._engine = make_listener(engine), engine
        down = button_down(r.get("button"))
        out = None
        if down and not self._down:                    # se acaba de pulsar
            self.listener.start(all_phrases(commands))
            self._drain()
            self.listener.listen(True)
            self.listening, self._since, self._released_at = True, now, None
            out = ("listening", "")
        elif not down and self._down and self.listening:
            self._released_at = now
        self._down = down
        if self.listening:
            try:
                text, conf = self.listener.results.get_nowait()
            except queue.Empty:
                text = conf = None
                expired = (self._released_at is not None and now - self._released_at > self.GRACE_S) or \
                    now - self._since > self.MAX_LISTEN_S
                if expired:
                    self._stop()
                    return ("unknown", "")
                return out
            self.last_heard = (text, conf)
            if text is None or conf < float(r.get("min_conf", 0.45)):
                if self._released_at is not None:      # ya soltó: no hay más que esperar
                    self._stop()
                    return ("unknown", f"«{text}» (seguridad {conf:.2f})" if text else "")
                return out
            self._stop()
            cmd = find_command(text, commands)
            if cmd is None:
                return ("unknown", text)
            if REPEAT in cmd.get("say", ""):
                return ("answer", self.last_answer or "No he dicho nada todavía")
            answer = render(cmd.get("say", ""), snapshot_fn())
            self.last_answer = answer
            return ("answer", answer)
        return out

    def _stop(self):
        self.listening = False
        self.listener.listen(False)

    def _drain(self):
        while not self.listener.results.empty():
            try:
                self.listener.results.get_nowait()
            except queue.Empty:
                break

    def close(self):
        if self.listener is not None:
            self.listener.close()

