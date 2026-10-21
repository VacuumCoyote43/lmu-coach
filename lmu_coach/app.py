"""Modo coach: une lector, grabador, coach y overlay."""
import argparse
import threading
import time

from . import corners, goals, training
from .engineer import Engineer
from .spotter import DamageWatch, Spotter
from .coach import LiveCoach
from .laps import LapRecorder, LapStore, Reference, fmt_time, save_async
from .speech import RATES, Speaker, VoiceQueue, gap_es, lap_time_es
from .overlay import AMBER, MUTED, Overlay
from .config import DEFAULT_CONFIG, config_mtime, load_config, msg_on, save_config  # noqa: F401
from .paths import DEMO_LAPS_DIR, INDEX_PATH, LAPS_DIR
from .reader import DemoReader, LMUReader
from .log import log, warn_once

LAP_FLASH_SECONDS = 6.0


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
            log.warning("No se pudo cargar la referencia del histórico", exc_info=True)  # seguimos con lo que haya
    return best, "mejor vuelta"


def beep():
    import winsound
    threading.Thread(target=winsound.Beep, args=(1400, 120), daemon=True).start()


# prioridad (más alta, antes) y caducidad (s) de cada aviso del ingeniero
ENGINEER_PRIO = {"close": 3, "position": 2, "pit": 1, "fastclass": 3, "end5": 2, "lastlap": 2, "flag": 3,
                 "pitwindow": 2}
ENGINEER_TTL = {"close": 3, "position": 6, "pit": 8, "fastclass": 3, "end5": 20, "lastlap": 20, "flag": 6,
                "pitwindow": 15}


class _Z:
    """Frenada mínima (vértice e índice) a partir de un objetivo del plan, para nombrarla."""

    def __init__(self, f):
        self.idx, self.apex = f.idx, f.apex


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
        self.voice = VoiceQueue(self.speaker)
        self.overlay = Overlay(self.cfg, self.close, on_voice=self._voice_toggled, on_temps=self._temps_toggled, on_engineer=self._engineer_toggled,
                               on_spotter=self._spotter_toggled,
                               voice_menu=(self._voice_choices, self._voice_chosen, self._rate_chosen))
        # consumo: lo aprendido en esta sesión y, mientras tanto, lo histórico de tus sesiones
        self.fuel_laps, self.ve_laps = [], []
        self.hist_fuel = self.hist_ve = None
        self.brake_base = None        # temperaturas de freno habituales con este coche (de tus sesiones)
        self._temps = None            # medias suavizadas para el overlay
        self._hot_since = None
        self._lap_fuel0 = self._lap_ve0 = None
        self._cur = None
        self._placed = False          # ¿ya comprobado que el coach está en el monitor del juego?
        self._place_next = 0.0
        self.engineer = Engineer()
        self.spotter = Spotter()
        self._cfg_mtime = config_mtime()
        self._cfg_next = 0.0
        self.damage = DamageWatch()
        self._spot_next = self._damage_next = 0.0
        self._summary_due = None
        self._race_next = 0.0
        self._spoken_corner = None
        self._corner_ctx = None
        self.plan = []
        self._spoken = set()          # avisos ya dichos en esta vuelta (frenadas, invalidación…)
        self._last_fb = None
        self.ref_key = None
        self.goal = None              # objetivo de tiempo con este coche y circuito (Mi progreso)
        self.ref_time = None
        self.ref_pinned = False
        self.lap_flash = None   # resultado de la última vuelta, se muestra en grande unos segundos
        self._last_et = None
        self._beeped_zone = None
        self._apply_config()

    # --- configuración (la ventana de Ajustes de la app la cambia mientras el coach está abierto) ----

    def _apply_config(self):
        c = self.cfg
        self.spotter.configure(c.get("spot_len"), c.get("spot_side"), c.get("spot_gap"), c.get("spot_still_s"))
        self.engineer.configure(c.get("eng_close_s"), c.get("eng_fast_s"), c.get("eng_summary_every"))
        self.speaker.enabled = bool(c.get("voice", True))
        if c.get("voice_name") and c.get("voice_name") != self.speaker.voice:
            self.speaker.set_voice(c["voice_name"])
        rate = float(c.get("voice_rate", 1.2))
        if rate != self.speaker.rate:
            self.speaker.set_rate(rate)
        try:
            self.overlay.root.attributes("-alpha", float(c.get("opacity", 0.93)))
            if bool(c.get("temps", True)) != self.overlay.show_temps:
                self.overlay.set_temps(bool(c.get("temps", True)))
        except Exception:
            warn_once("overlay-cfg", "No se pudo aplicar la configuración al overlay")

    def _watch_config(self):
        """Si el archivo de configuración ha cambiado (Ajustes de la app), recargarlo y aplicarlo."""
        now = time.monotonic()
        if now < self._cfg_next:
            return
        self._cfg_next = now + 1.0
        m = config_mtime()
        if m == self._cfg_mtime:
            return
        self._cfg_mtime = m
        new = load_config()
        new["x"], new["y"] = self.cfg.get("x", new["x"]), self.cfg.get("y", new["y"])   # la ventana manda
        self.cfg.clear()
        self.cfg.update(new)
        self._apply_config()
        self.overlay.toast("Ajustes actualizados", MUTED, 2)

    def _save_config(self):
        save_config(self.cfg)
        self._cfg_mtime = config_mtime()

    def _say(self, key: str, text: str, **kw):
        """Dice un mensaje del catálogo si está activado en los ajustes."""
        if msg_on(self.cfg, key):
            self.voice.say(text, **kw)

    def run(self):
        self.overlay.root.report_callback_exception = (
            lambda t, v, tb: log.error("Error en el coach", exc_info=(t, v, tb)))
        self.overlay.root.after(self.POLL_MS, self._tick)
        self.overlay.root.mainloop()

    def close(self):
        self._save_config()
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
        self._watch_config()
        if not self._placed and time.monotonic() >= self._place_next:
            self._place_next = time.monotonic() + 3
            self._placed = self._place_on_game_screen()
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
        self._race_step()
        self._spot_step()

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
            "temps": self._temps_state(s) if self.cfg.get("temps", True) else None,
            "race": self.engineer.state if self.cfg.get("engineer", True) else None,
            "spot": (self.spotter.state if self.cfg.get("spotter", True) and self.cfg.get("spot_overlay", True)
                     else None),
            "damage": self.damage.state,
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
        self.brake_base = None
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
        track = self.ref_key[0] if self.ref_key else lap.track
        layout = corners.resolve_layout(track, [z.apex for z in ref.zones])
        self.overlay.namer = lambda z: corners.label(z, track, layout, with_num=False)
        car = self.ref_key[1] if self.ref_key else lap.car
        self.plan = training.active(track, car)
        self.overlay.focus = lambda z: (f.short if (f := training.focus_for(self.plan, z)) else None)
        if self.plan:
            self.overlay.toast("Plan: " + ", ".join(corners.label(_Z(f), track, layout, with_num=False)
                                                    for f in self.plan), "#ffb020", 6)
        self._spoken_corner = lambda z: corners.spoken(z, track, layout)
        self._corner_ctx = (track, layout)
        self.goal = None if self.demo else goals.get(track, self.ref_key[1] if self.ref_key else lap.car, layout)
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
            log.warning("No se pudo leer el consumo histórico", exc_info=True)
        try:
            from .lapstats import brake_baseline
            from .paths import IMPORTED_DIR
            from .sessions import SessionIndex, find_telemetry_dir
            idx = SessionIndex(find_telemetry_dir(), INDEX_PATH, IMPORTED_DIR)
            mine = [i for i in idx.sessions if not i.imported and not i.error and i.car == car]
            self.brake_base = brake_baseline(mine)
        except Exception:
            log.warning("No se pudieron leer las temperaturas de freno habituales", exc_info=True)

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
                self._say("fuel", f"{what} para {amount}", kind="fuel", prio=2, ttl=20)
                return

    # --- voz ---------------------------------------------------------------

    def _voice_toggled(self, on):
        self.cfg["voice"] = on
        self.speaker.enabled = on
        self._save_config()
        if on:
            self.voice.say("Avisos por voz activados", interrupt=True)

    # --- temperaturas -----------------------------------------------------

    def _temps_state(self, s):
        """Temperaturas suavizadas con su estado: frío / bien / templado / caliente."""
        if not s.tyre_temp or not s.brake_temp:
            return None
        new = s.tyre_temp + s.brake_temp
        if self._temps is None or len(self._temps) != len(new):
            self._temps = list(new)
        else:
            k = 0.05   # a ~66 Hz, media de unos 0,3 s
            self._temps = [a + k * (b - a) for a, b in zip(self._temps, new)]
        tyres, brakes = self._temps[:4], self._temps[4:]
        opt = s.tyre_opt
        tyre_state = [None if opt is None else ("cold" if t < opt - 15 else "hot" if t > opt + 15
                                                else "warm" if abs(t - opt) > 8 else "ok") for t in tyres]
        base = self.brake_base
        brake_state = []
        for i, b in enumerate(brakes):
            if not base:
                brake_state.append(None)
                continue
            lo, hi = base["front" if i < 2 else "rear"]
            brake_state.append("hot" if b > hi * 1.12 else "warm" if b > hi else "cold" if b < lo * 0.8 else "ok")
        self._brake_warning(brake_state)
        return {"tyre": tyres, "tyre_state": tyre_state, "opt": opt, "brake": brakes, "brake_state": brake_state}

    def _brake_warning(self, states):
        """Aviso (una vez por vuelta) si los frenos de un eje pasan 2 s muy por encima de lo habitual."""
        hot = [i for i, st in enumerate(states) if st == "hot"]
        if not hot:
            self._hot_since = None
            return
        now = time.monotonic()
        self._hot_since = self._hot_since or now
        key = ("frenos", self._cur.lap if self._cur else 0)
        if now - self._hot_since > 2 and key not in self._spoken:
            self._spoken.add(key)
            axle = "delanteros" if min(hot) < 2 else "traseros"
            self.overlay.toast(f"Frenos {axle} muy calientes", "#ff4d4d")
            self._say("brakes", f"Frenos {axle} muy calientes", kind="brakes", prio=2, ttl=8)

    def _place_on_game_screen(self):
        """Si el coach está en otro monitor que LMU, lo lleva al del juego (en la misma esquina).
        Devuelve True cuando ya ha encontrado la ventana del juego (no hace falta volver a mirar)."""
        if self.demo:
            return True
        try:
            from .screens import game_monitor, monitor_at
            game = game_monitor()
            # la posición guardada (al arrancar, la ventana aún no sabe dónde está y diría 0,0)
            x, y = int(self.cfg.get("x", 60)), int(self.cfg.get("y", 60))
            mine = monitor_at(x + 150, y + 20)
        except Exception:
            warn_once("pantallas", "No se pudo comprobar en qué monitor está el juego")
            return True
        # ¿la posición guardada cae dentro de algún monitor? (si se desconectó uno, el coach quedaría fuera)
        visible = bool(mine) and mine[0] <= x + 150 < mine[2] and mine[1] <= y + 20 < mine[3]
        if not game:
            if visible:
                return False          # aún no está LMU: seguir mirando
            game = monitor_at(0, 0)   # fuera de pantalla: al monitor principal mientras tanto
            if not game:
                return False
        elif visible and game == mine:
            return True
        ox, oy = (mine[0], mine[1]) if mine else (game[0], game[1])
        nx = game[0] + min(max(0, x - ox), game[2] - game[0] - 300)
        ny = game[1] + min(max(0, y - oy), game[3] - game[1] - 220)
        self.overlay.move_to(nx, ny)
        self.overlay.toast("Coach movido a la pantalla del juego", AMBER, 5)
        return True

    # --- ingeniero de carrera ---------------------------------------------

    def _race_step(self):
        """Unas 4 veces por segundo: clasificación y avisos del ingeniero (solo en carrera)."""
        now = time.monotonic()
        if now < self._race_next or not self.cfg.get("engineer", True):
            return
        self._race_next = now + 0.25
        try:
            info = self.reader.race_info()
        except Exception:
            warn_once("clasificacion", "No se pudo leer la clasificación en directo")
            return
        if info is None:
            return
        for msg, kind in self.engineer.update(info):
            self._say(kind, msg, kind=kind, prio=ENGINEER_PRIO.get(kind, 1), ttl=ENGINEER_TTL.get(kind, 6),
                           interrupt=kind in ("close", "fastclass"))   # te van a alcanzar: no puede esperar
        # el resumen de la vuelta, 4 s después de cruzar meta (para no pisar el tiempo de vuelta)
        if self.engineer.pending_summary:
            self._summary_due = (self.engineer.pending_summary, now + 4.0)
            self.engineer.pending_summary = None
        if self._summary_due and now >= self._summary_due[1]:
            self._say("summary", self._summary_due[0], kind="summary", prio=1, ttl=15)
            self._summary_due = None

    def _spot_step(self):
        """Spotter (~20 veces por segundo) y daños (2 por segundo)."""
        now = time.monotonic()
        if self.cfg.get("spotter", True) and now >= self._spot_next:
            self._spot_next = now + 0.05
            try:
                f = self.reader.spotter_frame() if hasattr(self.reader, "spotter_frame") else None
            except Exception:
                warn_once("spotter", "No se pudo leer la posición de los coches para el spotter")
                f = None
            if f is not None:
                msg = self.spotter.update(f, now)
                if msg:
                    self._say(msg[0], msg[1], interrupt=True)
        if now >= self._damage_next:
            self._damage_next = now + 0.5
            try:
                d = self.reader.damage() if hasattr(self.reader, "damage") else None
            except Exception:
                warn_once("danos", "No se pudieron leer los daños del coche")
                d = None
            if d is not None:
                for key, msg in self.damage.update(d, now):
                    self.overlay.toast(msg, "#ff4d4d", 6)
                    self._say(key, msg, kind="damage", prio=3, ttl=8)

    def _spotter_toggled(self, on):
        self.cfg["spotter"] = on
        self._save_config()
        if not on:
            self.spotter.state = None

    def _engineer_toggled(self, on):
        self.cfg["engineer"] = on
        self._save_config()
        if not on:
            self.engineer.state = None

    def _temps_toggled(self, on):
        self.cfg["temps"] = on
        self._save_config()
        self.overlay.set_temps(on)

    def _voice_choices(self):
        """(voces instaladas, voz actual, velocidades, velocidad actual) para el menú del overlay."""
        sp = self.speaker
        return sp.voices, sp.current or sp.voice, RATES, sp.rate

    def _voice_chosen(self, name):
        self.cfg["voice_name"] = name
        self._save_config()
        self.speaker.set_voice(name)
        self._voice_sample()

    def _rate_chosen(self, rate):
        self.cfg["voice_rate"] = rate
        self._save_config()
        self.speaker.set_rate(rate)
        self._voice_sample()

    def _voice_sample(self):
        self.voice.say(f"Frena. {lap_time_es(106.658)}", interrupt=True)

    def _voice_events(self, s, cue):
        self.voice.tick()
        if not self.speaker.enabled:
            return
        # objetivo del plan de entrenamiento, unos 4 s antes de la curva
        if cue and not cue.braking and self.plan and 0 < cue.dist_to <= max(s.speed / 3.6 * 4.0, 120):
            f = training.focus_for(self.plan, cue.zone)
            key = ("plan", cue.zone.idx)
            if f and key not in self._spoken:
                self._spoken.add(key)
                name = corners.name_for(*self._corner_ctx, cue.zone.apex) if self._corner_ctx else None
                self._say("plan", f"{name or 'Curva ' + str(cue.zone.idx)}: {f.short.replace(' m ', ' metros ')}",
                               kind="plan", prio=2, ttl=2.5)
        # «frena» un instante antes del punto de frenada (la voz tarda unas décimas en sonar)
        if cue and not cue.braking and 0 < cue.dist_to <= max(s.speed / 3.6 * 0.45, 8):
            key = ("brake", cue.zone.idx)
            if key not in self._spoken:
                self._spoken.add(key)
                self._say("brake", "frena", interrupt=True)
        # balance de la frenada que acabas de pasar, si has ganado o perdido algo apreciable
        fb = self.coach.last_feedback
        if fb is not None and fb is not self._last_fb:
            self._last_fb = fb
            if abs(fb.time_diff) >= 0.15:
                verb = "pierdes" if fb.time_diff > 0 else "ganas"
                where = self._spoken_corner(fb.zone) if self._spoken_corner else f"en la {fb.zone.idx}"
                self._say("corner", f"{verb} {gap_es(fb.time_diff)} {where}", kind="corner", prio=1, ttl=4)
        reason = self.recorder.invalid_reason or ""
        if self.recorder.started_clean and "límites" in reason and "invalid" not in self._spoken:
            self._spoken.add("invalid")
            self._say("invalid", "vuelta invalidada", kind="invalid", prio=2, ttl=5)

    def _say_lap(self, lap_time, valid, reason):
        if not self.speaker.enabled or not self.recorder.started_clean or lap_time < LapRecorder.MIN_LAP_TIME:
            return
        if not valid:
            self._say("lap", "vuelta no válida", kind="lap", prio=2, ttl=6)
            return
        t = lap_time_es(lap_time)
        if self.ref_time is None or lap_time < self.ref_time:
            gain = f", {gap_es(lap_time - self.ref_time)} mejor" if self.ref_time else ""
            self._say("lap", f"Nueva mejor vuelta. {t}{gain}", kind="lap", prio=2, ttl=8)
        else:
            self._say("lap", f"{t}. Más {gap_es(lap_time - self.ref_time)}", kind="lap", prio=2, ttl=8)
        self._goal_check(lap_time)

    def _goal_check(self, lap_time):
        """Frente a tu objetivo: solo si la vuelta anda cerca (una vuelta con tráfico no aporta nada)."""
        if not self.goal:
            return
        gap = lap_time - self.goal
        if gap <= 0:
            self.overlay.toast("🎯 ¡Objetivo conseguido!", "#2ecc71", 8)
            self._say("goal", goals.spoken_gap(gap), kind="goal", prio=2, ttl=12)
            self.goal = None          # dicho una vez; el siguiente se fija en Mi progreso
        elif gap < 2.0:
            self._say("goal", goals.spoken_gap(gap), kind="goal", prio=1, ttl=12)



def main(argv=None):
    from .log import setup
    setup("coach")
    ap = argparse.ArgumentParser(description="LMU Coach: delta y avisos de frenada en directo")
    ap.add_argument("--demo", action="store_true", help="usa un coche simulado (sin el juego)")
    ap.add_argument("--demo-speed", type=float, default=1.0, help="acelera la simulación demo")
    args, _ = ap.parse_known_args(argv)
    App(demo=args.demo, demo_speed=args.demo_speed).run()


if __name__ == "__main__":
    main()
