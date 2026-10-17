"""Avisos por voz con las voces de Windows, sin dependencias extra.

Un proceso de PowerShell en segundo plano lee frases por stdin y las dice. Usa las voces modernas de
Windows (OneCore: Pablo, Laura, Helena…) y, si no están disponibles, las clásicas de System.Speech.
Cada frase nueva corta la anterior: nunca se acumulan avisos atrasados.

Órdenes por stdin: una frase por línea, «__voz__ Nombre», «__vel__ 1.2» y «__salir__».
Al arrancar, y cada vez que cambia la voz, el proceso escribe por stdout «__voces__ A|B|C» y «__actual__ A».
"""
import os
import subprocess
import threading

_SCRIPT = r"""
[Console]::InputEncoding = [Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$wav = $env:LMU_COACH_TTS_WAV
$rate = 1.2
try { $rate = [double]::Parse($env:LMU_COACH_TTS_RATE, [Globalization.CultureInfo]::InvariantCulture) } catch {}

$oc = $null
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
  $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } |
    Select-Object -First 1
  $asTask = $asTask.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
  $oc = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
  $all = @([Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices)
  if ($all.Count -eq 0) { $oc = $null }
} catch { $oc = $null }

$sapi = $null
if (-not $oc) {
  Add-Type -AssemblyName System.Speech
  $sapi = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $all = @($sapi.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo })
}
$player = $null

function Short($v) {
  $n = if ($oc) { $v.DisplayName } else { $v.Name }
  return ($n -replace '^Microsoft ', '' -replace ' Desktop$', '')
}
function Lang($v) { if ($oc) { $v.Language } else { $v.Culture.Name } }

function Set-Voice($name) {
  $v = $null
  if ($name) { $v = $all | Where-Object { (Short $_) -eq $name } | Select-Object -First 1 }
  if (-not $v) { $v = $all | Where-Object { (Lang $_) -like 'es-ES*' } | Select-Object -First 1 }
  if (-not $v) { $v = $all | Where-Object { (Lang $_) -like 'es*' } | Select-Object -First 1 }
  if (-not $v) { $v = $all | Select-Object -First 1 }
  if ($v) {
    if ($oc) { $oc.Voice = $v } else { $sapi.SelectVoice($v.Name) }
    [Console]::Out.WriteLine('__actual__ ' + (Short $v))
  }
}
function Set-Rate($r) {
  $script:rate = $r
  if ($oc) { $oc.Options.SpeakingRate = [Math]::Max(0.5, [Math]::Min(3.0, $r)) }
  else { $sapi.Rate = [int][Math]::Max(-10, [Math]::Min(10, [Math]::Round(($r - 1) * 8))) }
}
function Say($text) {
  if ($oc) {
    $t = $asTask.Invoke($null, @($oc.SynthesizeTextToStreamAsync($text)))
    $t.Wait()
    $ms = New-Object System.IO.MemoryStream
    [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($t.Result).CopyTo($ms)
    if ($wav) { [IO.File]::WriteAllBytes($wav, $ms.ToArray()); return }
    if ($script:player) { $script:player.Stop() }
    $ms.Position = 0
    $script:player = New-Object System.Media.SoundPlayer $ms
    $script:player.Play()
  } else {
    if ($wav) { $sapi.SetOutputToWaveFile($wav); $sapi.Speak($text); $sapi.SetOutputToNull(); return }
    $sapi.SpeakAsyncCancelAll(); $sapi.SpeakAsync($text) | Out-Null
  }
}

[Console]::Out.WriteLine('__voces__ ' + (($all | ForEach-Object { Short $_ }) -join '|'))
Set-Voice $env:LMU_COACH_TTS_VOICE
Set-Rate $rate
[Console]::Out.Flush()
while ($true) {
  $l = [Console]::In.ReadLine()
  if ($l -eq $null -or $l -eq '__salir__') { break }
  try {
    if ($l.StartsWith('__voz__ ')) { Set-Voice $l.Substring(8) }
    elseif ($l.StartsWith('__vel__ ')) { Set-Rate ([double]::Parse($l.Substring(8), [Globalization.CultureInfo]::InvariantCulture)) }
    else { Say $l }
  } catch {}
  [Console]::Out.Flush()
}
if ($player) { $player.Stop() }
if ($sapi) { $sapi.Dispose() }
"""

CREATE_NO_WINDOW = 0x08000000
RATES = [("Normal", 1.0), ("Rápida", 1.2), ("Muy rápida", 1.45)]


class Speaker:
    def __init__(self, enabled=True, voice: str | None = None, rate: float = 1.2, wav_path: str | None = None):
        self.enabled = enabled
        self.voice = voice            # nombre pedido (None = la primera en español)
        self.rate = rate
        self.voices: list[str] = []   # voces instaladas (se rellena al arrancar el proceso)
        self.current: str | None = None
        self._proc = None
        self._lock = threading.Lock()
        self._wav = wav_path

    def _ensure(self):
        if self._proc and self._proc.poll() is None:
            return True
        try:
            env = dict(os.environ)
            if self._wav:
                env["LMU_COACH_TTS_WAV"] = self._wav
            env["LMU_COACH_TTS_VOICE"] = self.voice or ""
            env["LMU_COACH_TTS_RATE"] = str(self.rate)
            self._proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _SCRIPT],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW, env=env)
            threading.Thread(target=self._read_output, args=(self._proc,), daemon=True).start()
            return True
        except OSError:
            self._proc = None
            return False

    def _read_output(self, proc):
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip().lstrip("﻿")
            if line.startswith("__voces__ "):
                self.voices = [v for v in line[10:].split("|") if v]
            elif line.startswith("__actual__ "):
                self.current = line[11:]

    def start(self):
        """Arranca el proceso ya (para tener la lista de voces antes de decir nada)."""
        with self._lock:
            self._ensure()

    def _send(self, line: str):
        with self._lock:
            if not self._ensure():
                return
            try:
                self._proc.stdin.write((line.replace("\n", " ") + "\n").encode("utf-8"))
                self._proc.stdin.flush()
            except OSError:
                self._proc = None

    def say(self, text: str):
        if self.enabled and text:
            self._send(text)

    def set_voice(self, name: str):
        self.voice = name
        self._send(f"__voz__ {name}")

    def set_rate(self, rate: float):
        self.rate = rate
        self._send(f"__vel__ {rate}")

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
