"""Lectura de telemetría: en directo desde LMU o simulada (modo demo)."""
import ctypes as C
import math
import time
from ctypes import wintypes
from dataclasses import dataclass

from .shm_structs import (
    MAX_VEHICLES,
    ScoringInfoV01,
    SharedMemoryObjectOut,
    TelemInfoV01,
    VehicleScoringInfoV01,
    offset_of,
)

FILE_MAP_READ = 0x0004


@dataclass
class Sample:
    """Una muestra del coche del jugador, ya normalizada."""
    et: float            # tiempo de sesión (s)
    lap: int             # número de vuelta
    lap_start_et: float  # tiempo de sesión al empezar la vuelta
    lap_dist: float      # distancia en la vuelta (m), interpolada entre actualizaciones de scoring
    track_len: float     # longitud del circuito (m)
    speed: float         # km/h
    throttle: float      # 0..1
    brake: float         # 0..1
    steer: float         # -1..1
    gear: int
    rpm: float
    x: float
    z: float
    in_pits: bool
    lap_invalid: bool
    last_lap_time: float  # última vuelta según el juego (s, <=0 si no hay)
    track: str
    car: str
    in_realtime: bool
    sector: int = 0      # 0, 1, 2 (sector actual según el juego)
    fuel: float | None = None        # litros
    fuel_capacity: float | None = None
    ve: float | None = None          # energía virtual (%; None si el coche no la usa)
    tyre_temp: list | None = None    # °C por rueda (media de la banda: interior, centro, exterior)
    tyre_opt: float | None = None    # °C óptimos del compuesto según el juego
    brake_temp: list | None = None   # °C por rueda


def _celsius(v: float) -> float:
    """Las temperaturas de neumático vienen en kelvin."""
    return v - 273.15 if v > 200 else v


def _opt_temp(v: float) -> float | None:
    c = _celsius(v) if v else None
    return c if c is not None and 20 < c < 160 else None


def _s(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("utf-8", "replace").strip()


class LMUReader:
    """Lee la memoria compartida nativa de LMU (LMU_Data) por sondeo.

    No usa los eventos de sincronización del juego a propósito: son de
    auto-reset y robarlos podría dejar sin datos a otras apps (SimHub, CrewChief...).
    """

    MAP_NAME = "LMU_Data"

    def __init__(self):
        self._k32 = C.WinDLL("kernel32", use_last_error=True)
        self._k32.OpenFileMappingW.restype = wintypes.HANDLE
        self._k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        self._k32.MapViewOfFile.restype = C.c_void_p
        self._k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, C.c_size_t]
        self._k32.UnmapViewOfFile.argtypes = [C.c_void_p]
        self._handle = None
        self._view = None
        self._off_si = offset_of(SharedMemoryObjectOut, "scoring", "scoringInfo")
        self._off_vsc = offset_of(SharedMemoryObjectOut, "scoring", "vehScoringInfo")
        self._off_tel = offset_of(SharedMemoryObjectOut, "telemetry")
        self._off_telinfo = offset_of(SharedMemoryObjectOut, "telemetry", "telemInfo")
        # Interpolación de la distancia entre actualizaciones de scoring (~5 Hz)
        self._last_scoring_dist = None
        self._dist = 0.0
        self._last_et = None

    def connect(self) -> bool:
        if self._view:
            return True
        h = self._k32.OpenFileMappingW(FILE_MAP_READ, False, self.MAP_NAME)
        if not h:
            return False
        view = self._k32.MapViewOfFile(h, FILE_MAP_READ, 0, 0, C.sizeof(SharedMemoryObjectOut))
        if not view:
            self._k32.CloseHandle(h)
            return False
        self._handle, self._view = h, view
        return True

    def close(self):
        if self._view:
            self._k32.UnmapViewOfFile(self._view)
        if self._handle:
            self._k32.CloseHandle(self._handle)
        self._view = self._handle = None

    def _copy(self, struct, offset):
        return struct.from_buffer_copy(C.string_at(self._view + offset, C.sizeof(struct)))

    def read(self) -> Sample | None:
        if not self.connect():
            return None
        hdr = C.string_at(self._view + self._off_tel, 3)
        active, player_idx, has_vehicle = hdr[0], hdr[1], bool(hdr[2])
        if not has_vehicle or player_idx >= max(active, 1) or player_idx >= MAX_VEHICLES:
            return None
        tel = self._copy(TelemInfoV01, self._off_telinfo + player_idx * C.sizeof(TelemInfoV01))
        si = self._copy(ScoringInfoV01, self._off_si)

        # Buscar el registro de scoring del jugador
        vs = None
        n = max(0, min(si.mNumVehicles, MAX_VEHICLES))
        for i in range(n):
            cand = self._copy(VehicleScoringInfoV01, self._off_vsc + i * C.sizeof(VehicleScoringInfoV01))
            if cand.mIsPlayer:
                vs = cand
                break
        if vs is None:
            return None

        v = tel.mLocalVel
        speed_ms = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
        et = tel.mElapsedTime
        lap_dist = self._interp_dist(vs.mLapDist, speed_ms, et, si.mLapDist)

        return Sample(
            et=et,
            lap=tel.mLapNumber,
            lap_start_et=tel.mLapStartET,
            lap_dist=lap_dist,
            track_len=si.mLapDist,
            speed=speed_ms * 3.6,
            throttle=tel.mUnfilteredThrottle,
            brake=tel.mUnfilteredBrake,
            steer=tel.mUnfilteredSteering,
            gear=tel.mGear,
            rpm=tel.mEngineRPM,
            x=tel.mPos.x,
            z=tel.mPos.z,
            in_pits=bool(vs.mInPits),
            lap_invalid=bool(tel.mLapInvalidated) or vs.mCountLapFlag != 2,
            last_lap_time=vs.mLastLapTime,
            track=_s(tel.mTrackName) or _s(si.mTrackName),
            car=_s(tel.mVehicleName) or _s(vs.mVehicleName),
            in_realtime=bool(si.mInRealtime),
            sector=tel.mCurrentSector & 0x7FFFFFFF,  # el bit de signo indica pit lane
            fuel=tel.mFuel,
            fuel_capacity=tel.mFuelCapacity or None,
            ve=self._ve_percent(tel.mVirtualEnergy),
            tyre_temp=[_celsius(sum(w.mTemperature) / 3) for w in tel.mWheel],
            tyre_opt=_opt_temp(tel.mWheel[0].mOptimalTemp),
            brake_temp=[w.mBrakeTemp for w in tel.mWheel],
        )

    def _telem_all(self):
        """(índice del jugador, [TelemInfoV01 de cada coche activo])."""
        hdr = C.string_at(self._view + self._off_tel, 3)
        active, player_idx = min(hdr[0], MAX_VEHICLES), hdr[1]
        tels = [self._copy(TelemInfoV01, self._off_telinfo + i * C.sizeof(TelemInfoV01)) for i in range(active)]
        return player_idx, tels

    def spotter_frame(self):
        """Tu posición, velocidad y volante, y la posición de los demás (para el spotter)."""
        from .spotter import SpotFrame
        if not self.connect():
            return None
        idx, tels = self._telem_all()
        if idx >= len(tels):
            return None
        me = tels[idx]
        o, l = me.mOri, me.mLocalVel
        vx = o[0].x * l.x + o[0].y * l.y + o[0].z * l.z
        vz = o[2].x * l.x + o[2].y * l.y + o[2].z * l.z
        others = []
        for i, t in enumerate(tels):
            if i == idx:
                continue
            v = t.mLocalVel
            others.append((t.mPos.x, t.mPos.z, (v.x * v.x + v.y * v.y + v.z * v.z) ** 0.5))
        return SpotFrame((me.mPos.x, me.mPos.z), (vx, vz), me.mUnfilteredSteering, others)

    def damage(self):
        """Daños de tu coche: abolladuras (8 zonas), piezas sueltas, pinchazos, ruedas perdidas, motor."""
        if not self.connect():
            return None
        idx, tels = self._telem_all()
        if idx >= len(tels):
            return None
        t = tels[idx]
        return {"dents": list(t.mDentSeverity), "detached": bool(t.mDetached),
                "flat": [bool(w.mFlat) for w in t.mWheel], "wheel_off": [bool(w.mDetached) for w in t.mWheel],
                "overheating": bool(t.mOverheating)}

    def race_info(self):
        """Clasificación de todos los coches (para el ingeniero de carrera); None si no hay datos."""
        from .engineer import RaceCar, RaceInfo
        if not self.connect():
            return None
        si = self._copy(ScoringInfoV01, self._off_si)
        n = max(0, min(si.mNumVehicles, MAX_VEHICLES))
        cars = []
        for i in range(n):
            v = self._copy(VehicleScoringInfoV01, self._off_vsc + i * C.sizeof(VehicleScoringInfoV01))
            cars.append(RaceCar(place=v.mPlace, cls=_s(v.mVehicleClass), driver=_s(v.mDriverName) or str(v.mID),
                                laps=v.mTotalLaps, lap_dist=v.mLapDist, in_pits=bool(v.mInPits),
                                pitstops=v.mNumPitstops, is_player=bool(v.mIsPlayer), best=v.mBestLapTime,
                                last=v.mLastLapTime, est=v.mEstimatedLapTime, finished=v.mFinishStatus != 0,
                                behind_leader=v.mTimeBehindLeader, laps_behind_leader=v.mLapsBehindLeader))
        timed = 0 < si.mEndET < 1e7
        laps_left = None
        if 0 < si.mMaxLaps < 10000:
            lead = max((c.laps for c in cars), default=0)
            laps_left = max(0, si.mMaxLaps - lead)
        # carrera con bandera verde (5) o coche de seguridad (6)
        return RaceInfo(is_race=si.mSession >= 10 and si.mGamePhase in (5, 6), track_len=si.mLapDist,
                        time_left=(si.mEndET - si.mCurrentET) if timed else None, laps_left=laps_left, cars=cars)

    _ve_seen_max = 0.0

    def _ve_percent(self, v: float):
        """LMU puede dar la energía virtual como fracción (0–1) o en %; la devolvemos siempre en %."""
        if not v or v < 0:
            return None
        self._ve_seen_max = max(self._ve_seen_max, v)
        return v * 100.0 if self._ve_seen_max <= 1.0001 else v

    def _interp_dist(self, scoring_dist, speed_ms, et, track_len):
        """El scoring llega a ~5 Hz; integramos la velocidad entre medias."""
        if self._last_scoring_dist is None or scoring_dist != self._last_scoring_dist:
            self._last_scoring_dist = scoring_dist
            self._dist = scoring_dist
        elif self._last_et is not None and et > self._last_et:
            self._dist += speed_ms * (et - self._last_et)
            if track_len > 0 and self._dist >= track_len:
                self._dist -= track_len
        self._last_et = et
        return self._dist


class _DemoRace:
    """Rivales con ritmo fijo alrededor del coche de la demo."""
    RIVALS = [("Rival A", "GT3", -2.5, 0.995), ("Rival B", "GT3", 1.6, 1.004), ("Rival C", "GT3", 4.0, 1.01),
              ("Prototipo", "Hypercar", -40.0, 0.88)]


class DemoReader:
    """Coche simulado en un circuito inventado, para probar sin el juego.

    Cada vuelta varía un poco los puntos de frenada y las velocidades de paso
    para que el delta y los avisos tengan algo que mostrar.
    """

    TRACK_LEN = 3000.0
    # (inicio frenada m, ápice m, velocidad mínima km/h)
    CORNERS = [(520, 640, 95), (1180, 1260, 140), (1900, 2040, 75), (2550, 2650, 120)]
    VMAX = 270.0

    def __init__(self, speedup: float = 1.0):
        self.speedup = speedup
        self._t0 = time.perf_counter()
        self._lap = 0
        self._lap_start = 0.0
        self._dist = 0.0
        self._last = None
        self._last_lap_time = -1.0
        self._profile = self._new_profile()

    def connect(self):
        return True

    def race_info(self):
        from .engineer import RaceCar, RaceInfo
        L = self.TRACK_LEN
        me_prog = self._lap + self._dist / L
        lap_t = self._last_lap_time if self._last_lap_time > 0 else 53.0
        t = me_prog * lap_t
        cars = [RaceCar(0, "GT3", "Tú (demo)", self._lap, self._dist, False, 0, True, lap_t, lap_t, lap_t)]
        for name, cls, start, pace in _DemoRace.RIVALS:
            prog = max(0.0, (t - start) / (lap_t * pace))
            cars.append(RaceCar(0, cls, name, int(prog), (prog % 1) * L, False, 0, False, lap_t * pace,
                                lap_t * pace, lap_t * pace))
        order = sorted(cars, key=lambda c: -(c.laps + c.lap_dist / L))
        for p, c in enumerate(order, 1):
            c.place = p
        return RaceInfo(is_race=True, track_len=L, time_left=max(0.0, 1800 - t), laps_left=None, cars=cars)

    def close(self):
        pass

    def _new_profile(self):
        import random
        rnd = random.Random(self._lap * 7919 + 13)
        prof = []
        for b, apex, vmin in self.CORNERS:
            prof.append((b + rnd.uniform(-25, 25), apex, vmin + rnd.uniform(-8, 8)))
        return prof

    def _target_speed(self, d):
        v = self.VMAX
        for b, apex, vmin in self._profile:
            if b <= d <= apex:
                frac = (d - b) / (apex - b)
                v = min(v, self.VMAX - (self.VMAX - vmin) * math.sqrt(frac))
            elif apex < d < apex + 350:
                frac = (d - apex) / 350
                v = min(v, vmin + (self.VMAX - vmin) * frac ** 0.8)
        return v

    def _inputs(self, d):
        for b, apex, _ in self._profile:
            if b <= d <= apex:
                return 0.0, max(0.1, 1.0 - (d - b) / (apex - b))
            if apex < d < apex + 350:
                return min(1.0, 0.3 + (d - apex) / 200), 0.0
        return 1.0, 0.0

    def read(self) -> Sample:
        now = (time.perf_counter() - self._t0) * self.speedup
        if self._last is None:
            self._last = now
        dt = now - self._last
        self._last = now
        speed = self._target_speed(self._dist)
        self._dist += speed / 3.6 * dt
        if self._dist >= self.TRACK_LEN:
            self._dist -= self.TRACK_LEN
            self._last_lap_time = now - self._lap_start
            self._lap += 1
            self._lap_start = now
            self._profile = self._new_profile()
        thr, brk = self._inputs(self._dist)
        ang = self._dist / self.TRACK_LEN * 2 * math.pi
        return Sample(
            et=now, lap=self._lap, lap_start_et=self._lap_start, lap_dist=self._dist,
            track_len=self.TRACK_LEN, speed=speed, throttle=thr, brake=brk, steer=0.0,
            gear=max(1, min(6, int(speed // 45) + 1)), rpm=6000 + speed * 10,
            x=math.cos(ang) * 480, z=math.sin(ang) * 480,
            in_pits=False, lap_invalid=False, last_lap_time=self._last_lap_time,
            track="Circuito Demo", car="Demo GT3", in_realtime=True,
            sector=0 if self._dist < 1000 else 1 if self._dist < 2100 else 2,
            fuel=max(0.0, 30.0 - (self._lap * self.TRACK_LEN + self._dist) / self.TRACK_LEN * 2.1),
            fuel_capacity=90.0,
            ve=max(0.0, 40.0 - (self._lap * self.TRACK_LEN + self._dist) / self.TRACK_LEN * 3.4),
            tyre_temp=[78 + 6 * math.sin(now / 9 + k) + (4 if k < 2 else 0) for k in range(4)],
            tyre_opt=80.0,
            brake_temp=[300 + 420 * brk + (60 if k < 2 else 0) for k in range(4)],
        )
