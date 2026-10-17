"""Modo coach: une lector, grabador, coach y overlay."""
import argparse
import json
import threading
import time

from .coach import LiveCoach
from .laps import LapRecorder, LapStore, Reference, fmt_time, save_async
from .speech import RATES, Speaker, gap_es, lap_time_es
from .overlay import AMBER, MUTED, Overlay
from .paths import CONFIG_PATH, DEMO_LAPS_DIR, INDEX_PATH, LAPS_DIR
from .reader import DemoReader, LMUReader

DEFAULT_CONFIG = {"x": 60, "y": 60, "opacity": 0.93, "beep_on_brake": False, "voice": True,
                  "voice_name": None, "voice_rate": 1.2}
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
        self.speaker = Speaker(bool(self.cfg.get("voice", True)), self.cfg.get("voice_name"),
                               float(self.cfg.get("voice_rate", 1.2)))
        self.speaker.start()
        self.overlay = Overlay(self.cfg, self.close, on_voice=self._voice_toggled,
                               voice_menu=(self._voice_choices, self._voice_chosen, self._rate_chosen))
        # consumo: lo aprendido en esta sesión y, mientras tanto, lo histórico de tus sesiones
        self.fuel_laps, self.ve_laps = [], []
        self.hist_fuel = self.hist_ve = None
        self._lap_fuel0 = self._lap_ve0 = None
        self._cur = None
        self._spoken = set()          # avisos ya dichos en esta vuelta (frenadas, invalidación…)
        self._last_fb = None
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
        self.speaker.close()
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
        self._cur = s
        self.recorder.feed(s)
        if new_lap or self._lap_fuel0 is None:
            if new_lap:
                self.coach.reset_lap()
                self._spoken.clear()
                self._fuel_warning()
            self._lap_fuel0, self._lap_ve0 = s.fuel, s.ve

        t_lap = s.et - s.lap_start_et
        d = self.recorder.cur_dist
        if s.et != self._last_et:
            self.coach.update(s, d, t_lap, invalid=self.recorder.invalid_reason is not None)
            self._last_et = s.et

        cue = self.coach.brake_cue(s, d)
        if self.cfg.get("beep_on_brake") and cue and cue.dist_to <= 0 and self._beeped_zone != (s.lap, cue.zone.idx):
            self._beeped_zone = (s.lap, cue.zone.idx)
            beep()
        self._voice_events(s, cue)

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
            "fuel": self._fuel_state(s),
        })

    # --- referencia y vueltas -------------------------------------------

    def _ensure_reference(self, track, car):
        key = (track, car)
        if key == self.ref_key:
            return
        self.ref_key = key
        lap, origin = find_reference(self.store, track, car, use_history=not self.demo)
        self.fuel_laps, self.ve_laps = [], []
        self.hist_fuel = self.hist_ve = None
        if not self.demo:
            threading.Thread(target=self._load_history, args=(track, car), daemon=True).start()
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
        self._learn_consumption(reason)
        self._say_lap(lap_time, valid, reason)
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

    # --- combustible y energía ------------------------------------------

    def _load_history(self, track, car):
        """Consumo típico con este coche y circuito (tus sesiones), para tener dato desde la vuelta 1."""
        try:
            from .lapstats import history_consumption, own_sessions
            from .paths import IMPORTED_DIR
            from .sessions import SessionIndex, find_telemetry_dir
            idx = SessionIndex(find_telemetry_dir(), INDEX_PATH, IMPORTED_DIR)
            c = history_consumption(own_sessions(idx.sessions, track, car), max_sessions=6)
            self.hist_fuel, self.hist_ve = c.fuel, c.ve
        except Exception:
            pass

    def _learn_consumption(self, reason):
        s = self._cur
        if s is None or self._lap_fuel0 is None or (reason and "boxes" in reason):
            return
        if s.fuel is not None:
            used = self._lap_fuel0 - s.fuel
            if 0.05 < used < 30:
                self.fuel_laps = (self.fuel_laps + [used])[-5:]
        if s.ve is not None and self._lap_ve0 is not None:
            used = self._lap_ve0 - s.ve
            if 0.05 < used < 50:
                self.ve_laps = (self.ve_laps + [used])[-5:]

    def _per_lap(self):
        import statistics
        fuel = statistics.median(self.fuel_laps) if self.fuel_laps else self.hist_fuel
        ve = statistics.median(self.ve_laps) if self.ve_laps else self.hist_ve
        return fuel, ve

    def _fuel_state(self, s):
        fuel_pl, ve_pl = self._per_lap()
        out = {}
        if s.fuel is not None and fuel_pl:
            out["fuel_laps"] = s.fuel / fuel_pl
        if s.ve is not None and ve_pl:
            out["ve_laps"] = s.ve / ve_pl
        return out

    def _fuel_warning(self):
        st = self._fuel_state(self._cur) if self._cur else {}
        for key, what in (("fuel_laps", "Combustible"), ("ve_laps", "Energía")):
            v = st.get(key)
            if v is not None and v < 2.5:
                n = int(v)
                amount = "menos de una vuelta" if n < 1 else ("una vuelta" if n == 1 else f"{n} vueltas")
                self.speaker.say(f"{what} para {amount}")
                return

    # --- voz ---------------------------------------------------------------

    def _voice_toggled(self, on):
        self.cfg["voice"] = on
        self.speaker.enabled = on
        if on:
            self.speaker.say("Avisos por voz activados")

    def _voice_choices(self):
        """(voces instaladas, voz actual, velocidades, velocidad actual) para el menú del overlay."""
        sp = self.speaker
        return sp.voices, sp.current or sp.voice, RATES, sp.rate

    def _voice_chosen(self, name):
        self.cfg["voice_name"] = name
        self.speaker.set_voice(name)
        self._voice_sample()

    def _rate_chosen(self, rate):
        self.cfg["voice_rate"] = rate
        self.speaker.set_rate(rate)
        self._voice_sample()

    def _voice_sample(self):
        if self.speaker.enabled:
            self.speaker.say(f"Frena. {lap_time_es(106.658)}")

    def _voice_events(self, s, cue):
        sp = self.speaker
        if not sp.enabled:
            return
        # «frena» un instante antes del punto de frenada (la voz tarda unas décimas en sonar)
        if cue and not cue.braking and 0 < cue.dist_to <= max(s.speed / 3.6 * 0.45, 8):
            key = ("brake", cue.zone.idx)
            if key not in self._spoken:
                self._spoken.add(key)
                sp.say("frena")
        # balance de la frenada que acabas de pasar, si has ganado o perdido algo apreciable
        fb = self.coach.last_feedback
        if fb is not None and fb is not self._last_fb:
            self._last_fb = fb
            if abs(fb.time_diff) >= 0.15:
                verb = "pierdes" if fb.time_diff > 0 else "ganas"
                sp.say(f"{verb} {gap_es(fb.time_diff)} en la {fb.zone.idx}")
        reason = self.recorder.invalid_reason or ""
        if self.recorder.started_clean and "límites" in reason and "invalid" not in self._spoken:
            self._spoken.add("invalid")
            sp.say("vuelta invalidada")

    def _say_lap(self, lap_time, valid, reason):
        if not self.speaker.enabled or not self.recorder.started_clean or lap_time < LapRecorder.MIN_LAP_TIME:
            return
        if not valid:
            self.speaker.say("vuelta no válida")
            return
        t = lap_time_es(lap_time)
        if self.ref_time is None or lap_time < self.ref_time:
            gain = f", {gap_es(lap_time - self.ref_time)} mejor" if self.ref_time else ""
            self.speaker.say(f"Nueva mejor vuelta. {t}{gain}")
        else:
            self.speaker.say(f"{t}. Más {gap_es(lap_time - self.ref_time)}")



def main(argv=None):
    ap = argparse.ArgumentParser(description="LMU Coach: delta y avisos de frenada en directo")
    ap.add_argument("--demo", action="store_true", help="usa un coche simulado (sin el juego)")
    ap.add_argument("--demo-speed", type=float, default=1.0, help="acelera la simulación demo")
    args, _ = ap.parse_known_args(argv)
    App(demo=args.demo, demo_speed=args.demo_speed).run()


if __name__ == "__main__":
    main()
