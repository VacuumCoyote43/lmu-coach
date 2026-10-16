"""Modo coach: une lector, grabador, coach y overlay."""
import argparse
import json
import threading
import time

from .coach import LiveCoach
from .laps import LapRecorder, LapStore, Reference, fmt_time, save_async
from .overlay import AMBER, MUTED, Overlay
from .paths import CONFIG_PATH, DEMO_LAPS_DIR, INDEX_PATH, LAPS_DIR
from .reader import DemoReader, LMUReader

DEFAULT_CONFIG = {"x": 60, "y": 60, "opacity": 0.93, "beep_on_brake": False}
LAP_FLASH_SECONDS = 6.0


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def find_reference(store: LapStore, track: str, car: str, use_history=True):
    """Referencia fijada > la más rápida entre las vueltas del coach y el histórico de LMU."""
    pinned = store.pinned(track, car)
    if pinned:
        return pinned, "fijada"
    best = store.best(track, car)
    if use_history:
        try:
            from .sessions import SessionData, SessionIndex, find_telemetry_dir
            hit = SessionIndex(find_telemetry_dir(), INDEX_PATH).best_for(track, car)
            if hit and (best is None or hit[1] < best.lap_time):
                info, _ = hit
                return SessionData(info).to_coach_lap(info.best_lap), "histórico"
        except Exception:
            pass  # sin índice o archivo ilegible: seguimos con lo que haya
    return best, "mejor vuelta"


def beep():
    import winsound
    threading.Thread(target=winsound.Beep, args=(1400, 120), daemon=True).start()


class App:
    POLL_MS = 15  # ~66 Hz

    def __init__(self, demo=False, demo_speed=1.0):
        self.cfg = load_config()
        self.store = LapStore(DEMO_LAPS_DIR if demo else LAPS_DIR)
        self.demo = demo
        self.reader = DemoReader(demo_speed) if demo else LMUReader()
        self.coach = LiveCoach()
        self.recorder = LapRecorder(self._on_lap)
        self.overlay = Overlay(self.cfg, self.close)
        self.ref_key = None
        self.ref_time = None
        self.ref_pinned = False
        self.lap_flash = None   # resultado de la última vuelta, se muestra en grande unos segundos
        self._last_et = None
        self._beeped_zone = None

    def run(self):
        self.overlay.root.after(self.POLL_MS, self._tick)
        self.overlay.root.mainloop()

    def close(self):
        save_config(self.cfg)
        self.reader.close()
        self.overlay.root.destroy()

    # --- bucle -----------------------------------------------------------

    def _tick(self):
        try:
            self._step()
        finally:
            self.overlay.root.after(self.POLL_MS, self._tick)

    def _step(self):
        s = self.reader.read()
        if s is None:
            self.overlay.draw({"status": "Esperando a Le Mans Ultimate…",
                               "substatus": "Abre el juego y sal a pista. Si ya lo está, usa «Diagnóstico» en la app."})
            return
        if not s.in_realtime:
            self.overlay.draw({"status": "En el monitor / garaje", "substatus": f"{s.track} · {s.car}"})
            return

        self._ensure_reference(s.track, s.car)
        new_lap = self.recorder.lap_no is not None and s.lap != self.recorder.lap_no
        self.recorder.feed(s)
        if new_lap:
            self.coach.reset_lap()

        t_lap = s.et - s.lap_start_et
        d = self.recorder.cur_dist
        if s.et != self._last_et:
            self.coach.update(s, d, t_lap, invalid=self.recorder.invalid_reason is not None)
            self._last_et = s.et

        cue = self.coach.brake_cue(s, d)
        if self.cfg.get("beep_on_brake") and cue and cue.dist_to <= 0 and self._beeped_zone != (s.lap, cue.zone.idx):
            self._beeped_zone = (s.lap, cue.zone.idx)
            beep()

        if self.lap_flash and time.monotonic() - self.lap_flash["created"] > LAP_FLASH_SECONDS:
            self.lap_flash = None

        ref = self.coach.ref
        sec = self.coach.sectors
        self.overlay.draw({
            "lap": s.lap,
            "speed": s.speed,
            "gear": s.gear,
            "thr": s.throttle,
            "brk": s.brake,
            "ref_thr": ref.throttle_at(d) if ref and d >= 0 else None,
            "ref_brk": ref.brake_at(d) if ref and d >= 0 else None,
            "ref_time": self.ref_time,
            "delta": self.coach.delta,
            "trend": self.coach.delta_trend(),
            "cue": cue,
            "feedback": self.coach.last_feedback,
            "lap_invalid": self.recorder.invalid_reason is not None and self.recorder.started_clean,
            "sectors": {
                "has": len(sec.bounds) == 2,
                "cur": sec.cur, "prev": sec.prev, "idx": sec.idx,
                "live": sec.live_delta, "ideal": sec.ideal(),
            },
            "lap_flash": self.lap_flash,
        })

    # --- referencia y vueltas -------------------------------------------

    def _ensure_reference(self, track, car):
        key = (track, car)
        if key == self.ref_key:
            return
        self.ref_key = key
        lap, origin = find_reference(self.store, track, car, use_history=not self.demo)
        self.ref_pinned = origin == "fijada"
        self._set_reference(lap)
        if lap:
            self.overlay.toast(f"Referencia ({origin}): {fmt_time(lap.lap_time)}", MUTED)

    def _set_reference(self, lap):
        if lap is None:
            self.coach.set_reference(None)
            self.ref_time = None
            return
        ref = Reference(lap)
        self.coach.set_reference(ref)
        self.ref_time = lap.lap_time

    def _on_lap(self, lap, lap_time, valid, reason):
        sec = self.coach.sectors
        sec.finish_lap(lap_time, valid)
        if lap:
            sec.learn_bounds(lap.sectors)
        is_best = valid and (self.ref_time is None or lap_time < self.ref_time)
        diff = lap_time - self.ref_time if self.ref_time else None
        # Solo enseñamos en grande vueltas que hemos visto de principio a fin
        if self.recorder.started_clean and lap_time > LapRecorder.MIN_LAP_TIME:
            self.lap_flash = {"time": lap_time, "diff": diff, "valid": valid, "reason": reason,
                              "best": is_best, "sectors": list(sec.cur), "created": time.monotonic()}
        elif not valid:
            self.overlay.toast(f"Vuelta {fmt_time(lap_time)} no válida ({reason})", AMBER)
        if not valid:
            return
        save_async(self.store, lap)
        if is_best and not self.ref_pinned:  # una referencia fijada a mano no se sustituye
            self._set_reference(lap)


def main(argv=None):
    ap = argparse.ArgumentParser(description="LMU Coach: delta y avisos de frenada en directo")
    ap.add_argument("--demo", action="store_true", help="usa un coche simulado (sin el juego)")
    ap.add_argument("--demo-speed", type=float, default=1.0, help="acelera la simulación demo")
    args, _ = ap.parse_known_args(argv)
    App(demo=args.demo, demo_speed=args.demo_speed).run()


if __name__ == "__main__":
    main()
