"""Nivel del micrófono en directo (para comprobar que la app te oye), con la API de audio de Windows (winmm),
sin librerías extra. Graba del micrófono por defecto, el mismo que usa el reconocimiento de voz."""
import ctypes as C
import math
import struct
from ctypes import wintypes as W

WAVE_MAPPER = 0xFFFFFFFF          # el dispositivo por defecto de Windows
WAVE_FORMAT_PCM = 1
WHDR_DONE = 0x01
RATE = 16000
CHUNK = 1600                      # 0,1 s


class WAVEFORMATEX(C.Structure):
    _fields_ = [("wFormatTag", W.WORD), ("nChannels", W.WORD), ("nSamplesPerSec", W.DWORD),
                ("nAvgBytesPerSec", W.DWORD), ("nBlockAlign", W.WORD), ("wBitsPerSample", W.WORD),
                ("cbSize", W.WORD)]


class WAVEHDR(C.Structure):
    pass


WAVEHDR._fields_ = [("lpData", C.c_void_p), ("dwBufferLength", W.DWORD), ("dwBytesRecorded", W.DWORD),
                    ("dwUser", C.c_size_t), ("dwFlags", W.DWORD), ("dwLoops", W.DWORD),
                    ("lpNext", C.POINTER(WAVEHDR)), ("reserved", C.c_size_t)]


class WAVEINCAPSW(C.Structure):
    _fields_ = [("wMid", W.WORD), ("wPid", W.WORD), ("vDriverVersion", W.UINT), ("szPname", C.c_wchar * 32),
                ("dwFormats", W.DWORD), ("wChannels", W.WORD), ("wReserved1", W.WORD)]


def devices() -> list[str]:
    """Micrófonos que ve Windows (el primero suele ser el predeterminado)."""
    try:
        w = C.windll.winmm
    except (AttributeError, OSError):
        return []
    out = []
    for i in range(w.waveInGetNumDevs()):
        caps = WAVEINCAPSW()
        if w.waveInGetDevCapsW(i, C.byref(caps), C.sizeof(caps)) == 0:
            out.append(caps.szPname)
    return out


class MicMeter:
    """open() empieza a grabar; level() devuelve el nivel de los últimos 0,1 s (0..1, escala en dB) o None."""

    def __init__(self, nbuf=4):
        self.h = W.HANDLE()
        self.bufs, self.hdrs = [], []
        self.nbuf = nbuf
        self.error = None
        self.peak = 0.0

    def open(self) -> bool:
        try:
            w = C.windll.winmm
        except (AttributeError, OSError) as e:
            self.error = str(e)
            return False
        fmt = WAVEFORMATEX(WAVE_FORMAT_PCM, 1, RATE, RATE * 2, 2, 16, 0)
        r = w.waveInOpen(C.byref(self.h), WAVE_MAPPER, C.byref(fmt), 0, 0, 0)
        if r != 0:
            self.error = "No hay micrófono o Windows no deja usarlo (Configuración › Privacidad › Micrófono)"
            return False
        for _ in range(self.nbuf):
            buf = C.create_string_buffer(CHUNK * 2)
            hdr = WAVEHDR()
            hdr.lpData = C.cast(buf, C.c_void_p)
            hdr.dwBufferLength = CHUNK * 2
            w.waveInPrepareHeader(self.h, C.byref(hdr), C.sizeof(hdr))
            w.waveInAddBuffer(self.h, C.byref(hdr), C.sizeof(hdr))
            self.bufs.append(buf)
            self.hdrs.append(hdr)
        w.waveInStart(self.h)
        return True

    def level(self) -> float | None:
        """Nivel de lo último grabado: 0 silencio, ~0,5 voz normal, 1 saturado."""
        if not self.hdrs:
            return None
        w = C.windll.winmm
        best = None
        for buf, hdr in zip(self.bufs, self.hdrs):
            if hdr.dwFlags & WHDR_DONE:
                n = hdr.dwBytesRecorded // 2
                if n:
                    samples = struct.unpack_from(f"<{n}h", buf.raw, 0)
                    rms = math.sqrt(sum(s * s for s in samples) / n) / 32768.0
                    db = 20 * math.log10(max(rms, 1e-5))          # -100 .. 0
                    lvl = min(1.0, max(0.0, (db + 60) / 60))      # -60 dB → 0, 0 dB → 1
                    best = lvl if best is None else max(best, lvl)
                hdr.dwFlags &= ~WHDR_DONE
                w.waveInAddBuffer(self.h, C.byref(hdr), C.sizeof(hdr))
        if best is not None:
            self.peak = max(best, self.peak * 0.85)
        return best

    def close(self):
        if not self.hdrs:
            return
        w = C.windll.winmm
        w.waveInStop(self.h)
        w.waveInReset(self.h)
        for hdr in self.hdrs:
            w.waveInUnprepareHeader(self.h, C.byref(hdr), C.sizeof(hdr))
        w.waveInClose(self.h)
        self.hdrs, self.bufs = [], []
