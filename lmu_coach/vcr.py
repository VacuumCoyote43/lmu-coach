"""Lector de repeticiones de LMU (.Vcr, formato gMotor "gMb1.002f"). Solo lectura.

Formato (deducido por ingeniería inversa, ver docs/plan-replays-vcr.md):

    cabecera de texto   //[[gMb1.002f (c)2016 ]] [[ ]]\\n
    "IRSR" + 12 bytes   (cabecera binaria)
    fotogramas, uno tras otro:
        f32  tiempo de sesión (s, múltiplo de 1/50)
        u16  número de eventos
        eventos:
            u8   id del vehículo
            u8   longitud (bits 0-7)
            u8   bit 0: bit 8 de la longitud; resto: tipo de evento
            ...  (longitud + 2 bytes más)          → tamaño total = longitud + 5

Eventos de estado de coche (tipo 0x10, 70 bytes): posición x, y, z en float32 en el byte 46.
"""
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

HEADER_END = b"\n"
BLOCK = 32 * 1024 * 1024


@dataclass
class Event:
    vehicle: int
    kind: int        # byte 2 sin el bit de longitud
    data: bytes      # el evento completo (incluidos los 3 bytes de cabecera)


@dataclass
class Frame:
    time: float
    offset: int
    events: list


def event_size(b1: int, b2: int) -> int:
    return (b1 | ((b2 & 1) << 8)) + 5


def frames(path: Path, start_time: float | None = None) -> Iterator[Frame]:
    """Recorre todos los fotogramas del archivo leyendo por bloques."""
    with open(path, "rb") as f:
        head = f.read(4096)
        text_end = head.find(HEADER_END)
        if not head.startswith(b"//[[gMb") or text_end < 0 or head[text_end + 1:text_end + 5] != b"IRSR":
            raise ValueError("No parece una repetición de LMU (.Vcr)")
        pos = text_end + 1 + 16
        f.seek(pos)
        buf = b""
        buf_start = pos
        eof = False
        while True:
            # asegurar al menos 64 KB por delante (los fotogramas grandes caben de sobra)
            if len(buf) - (pos - buf_start) < 65536 and not eof:
                chunk = f.read(BLOCK)
                eof = not chunk
                buf = buf[pos - buf_start:] + chunk
                buf_start = pos
            i = pos - buf_start
            if i + 6 > len(buf):
                return
            t, n = struct.unpack_from("<fH", buf, i)
            j = i + 6
            evs = []
            for _ in range(n):
                if j + 3 > len(buf):
                    return
                size = event_size(buf[j + 1], buf[j + 2])
                if j + size > len(buf):
                    return
                evs.append(Event(buf[j], buf[j + 2] & 0xFE, buf[j:j + size]))
                j += size
            yield Frame(t, pos, evs)
            pos = buf_start + j


# Eventos de estado de coche: 70 bytes, tipos 0x10–0x1c, posición x, y, z float32 en el byte 46
STATE_KINDS = frozenset(range(0x10, 0x1e, 2))
STATE_SIZE = 70
POS_OFFSET = 46


def positions(path: Path):
    """(tiempo, id de vehículo, x, y, z) de cada evento de estado de coche."""
    for fr in frames(path):
        for ev in fr.events:
            if ev.kind in STATE_KINDS and len(ev.data) == STATE_SIZE:
                x, y, z = struct.unpack_from("<fff", ev.data, POS_OFFSET)
                yield fr.time, ev.vehicle, x, y, z


# --- bloque final: información de la sesión y participantes ------------------------------

@dataclass
class Participant:
    vehicle: int       # id que usan los eventos
    driver: str
    vehicle_file: str  # p. ej. 397_26_296GT3
    team: str
    number: str
    t_start: float     # intervalo (tiempo de sesión) en el que ocupa la plaza
    t_end: float


def _pstr(buf: bytes, i: int, max_len=64):
    """Cadena precedida de su longitud (u8). Devuelve (texto, siguiente índice) o (None, i)."""
    if i >= len(buf):
        return None, i
    n = buf[i]
    s = buf[i + 1:i + 1 + n]
    if n > max_len or len(s) < n or any(c < 32 or c > 126 for c in s):
        return None, i
    return s.decode("latin-1"), i + 1 + n


def info(path: Path) -> dict:
    """Lee el bloque final: JSON de la sesión, circuito y participantes."""
    import json
    with open(path, "rb") as f:
        head = f.read(4096)
        i = head.find(b"IRSR")
        if i < 0:
            raise ValueError("No parece una repetición de LMU (.Vcr)")
        ptr = struct.unpack_from("<I", head, i + 8)[0]
        f.seek(ptr)
        tail = f.read()
    out = {"session": {}, "track": "", "participants": []}
    j = tail.find(b"{")
    k = tail.find(b"}", j)
    if j >= 0 and k > j:
        try:
            out["session"] = json.loads(tail[j:k + 1].decode("utf-8", "replace"))
        except ValueError:
            pass
    m = tail.find(b"Locations\\")
    if m >= 0:
        out["track"] = tail[m + 10:tail.find(b"\\", m + 10)].decode("latin-1")
    # Participantes: [u8 ?][u8 ?][u8 ?][u8 id] + 5 cadenas (piloto, coche, decoración, equipo, dorsal)
    # + datos varios + [f32 inicio][f32 fin]. Los dos tiempos van al FINAL de cada entrada, es
    # decir, justo antes de la cabecera de 4 bytes de la entrada siguiente.
    found = []
    for pos in range(12, len(tail) - 8):
        name, p = _pstr(tail, pos, 40)
        if not name or len(name) < 2 or not any(ch.isalpha() for ch in name):
            continue
        veh, p = _pstr(tail, p)
        if not veh or not any(ch.isalpha() for ch in veh):  # el archivo del coche siempre lleva letras
            continue
        skin, p = _pstr(tail, p)
        team, p = _pstr(tail, p)
        number, p = _pstr(tail, p, 8)
        if skin is None or team is None or number is None:
            continue
        found.append((pos, tail[pos - 1], name, veh, team, number))
    for k, (pos, vid, name, veh, team, number) in enumerate(found):
        if k + 1 < len(found):
            t0, t1 = struct.unpack_from("<ff", tail, found[k + 1][0] - 12)
        else:  # última entrada: los tiempos están tras sus datos, sin entrada siguiente
            t0, t1 = 0.0, -1e32
        valid = lambda t: 0 <= t < 1e7  # -1e32 = sigue en la plaza hasta el final
        out["participants"].append(Participant(
            vid, name, veh, team, number,
            round(t0, 3) if valid(t0) else 0.0,
            round(t1, 3) if valid(t1) else float("inf")))
    return out


def driver_at(participants: list, vehicle: int, t: float) -> "Participant | None":
    """Quién conducía el vehículo en el instante t (para carreras con relevos)."""
    cands = [p for p in participants if p.vehicle == vehicle]
    for p in cands:
        if p.t_start <= t < p.t_end:
            return p
    return cands[-1] if cands else None
