"""Avisos por voz con las voces de Windows (System.Speech), sin dependencias extra.

Un proceso de PowerShell en segundo plano lee frases por stdin y las dice con una voz en español
si la hay. Cada frase nueva corta la anterior: nunca se acumulan avisos atrasados.
"""
import subprocess
import threading

_SCRIPT = r"""
[Console]::InputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $s.SelectVoiceByHints('NotSet', 'NotSet', 0, [System.Globalization.CultureInfo]'es-ES') } catch {}
$s.Rate = 1
$wav = $env:LMU_COACH_TTS_WAV
if ($wav) { $s.SetOutputToWaveFile($wav) }
while ($true) {
  $l = [Console]::In.ReadLine()
  if ($l -eq $null -or $l -eq '__salir__') { break }
  if ($wav) { $s.Speak($l) } else { $s.SpeakAsyncCancelAll(); $s.SpeakAsync($l) | Out-Null }
}
$s.Dispose()
"""

CREATE_NO_WINDOW = 0x08000000


class Speaker:
    def __init__(self, enabled=True, wav_path: str | None = None):
        self.enabled = enabled
        self._proc = None
        self._lock = threading.Lock()
        self._wav = wav_path

    def _ensure(self):
        if self._proc and self._proc.poll() is None:
            return True
        try:
            import os
            env = dict(os.environ)
            if self._wav:
                env["LMU_COACH_TTS_WAV"] = self._wav
            self._proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _SCRIPT],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW, env=env)
            return True
        except OSError:
            self._proc = None
            return False

    def say(self, text: str):
        if not self.enabled or not text:
            return
        with self._lock:
            if not self._ensure():
                return
            try:
                self._proc.stdin.write((text.replace("\n", " ") + "\n").encode("utf-8"))
                self._proc.stdin.flush()
            except OSError:
                self._proc = None

    def close(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.stdin.write(b"__salir__\n")
                    self._proc.stdin.flush()
                    self._proc.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    self._proc.kill()
            self._proc = None


# --- frases ---------------------------------------------------------------------------------

_UNITS = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez",
          "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve",
          "veinte", "veintiuno", "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis",
          "veintisiete", "veintiocho", "veintinueve"]
_TENS = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta", 8: "ochenta", 9: "noventa"}


def number_es(n: int) -> str:
    """0–99 en palabras."""
    if n < 30:
        return _UNITS[n]
    t, u = divmod(n, 10)
    return _TENS[t] + (f" y {_UNITS[u]}" if u else "")


def lap_time_es(sec: float) -> str:
    """106.658 → 'uno, cuarenta y seis, seis cinco ocho'."""
    m, s = divmod(sec, 60)
    whole = int(s)
    ms = int(round((s - whole) * 1000))
    if ms == 1000:
        whole, ms = whole + 1, 0
    digits = " ".join(_UNITS[int(c)] for c in f"{ms:03d}")
    return f"{number_es(int(m))}, {number_es(whole)}, {digits}" if m >= 1 else f"{number_es(whole)}, {digits}"


def gap_es(d: float) -> str:
    """Diferencia de tiempo hablada: 'dos décimas', 'una décima', 'un segundo dos'."""
    a = abs(d)
    if a < 0.05:
        return "igual"
    if a < 1:
        t = int(round(a * 10))
        return "una décima" if t == 1 else f"{number_es(t)} décimas"
    whole = int(a)
    dec = int(round((a - whole) * 10))
    if dec == 10:
        whole, dec = whole + 1, 0
    w = "un segundo" if whole == 1 else f"{number_es(whole)} segundos"
    return w + (f" {number_es(dec)}" if dec else "")
