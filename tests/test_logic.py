"""Pruebas de la lógica pura (sin juego ni sesiones de LMU): se pueden ejecutar en cualquier PC."""
import math
import unittest

from lmu_coach import speech, updater
from lmu_coach.engineer import Engineer, RaceCar, RaceInfo
from lmu_coach.lapstats import LapStats, _theil_sen, stints, strategy
from lmu_coach.spotter import DamageWatch, SpotFrame, Spotter


class SpeechTest(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(speech.number_es(0), "cero")
        self.assertEqual(speech.number_es(21), "veintiuno")
        self.assertEqual(speech.number_es(46), "cuarenta y seis")
        self.assertEqual(speech.number_es(90), "noventa")

    def test_lap_time(self):
        self.assertEqual(speech.lap_time_es(106.658), "uno, cuarenta y seis, seis cinco ocho")

    def test_gap_in_tenths(self):
        self.assertIn("décimas", speech.gap_es(0.3))


class FakeSpeaker:
    enabled, rate = True, 1.2

    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)


class VoiceQueueTest(unittest.TestCase):
    def setUp(self):
        self.sp = FakeSpeaker()
        self.q = speech.VoiceQueue(self.sp)

    def run_until(self, t_end, step=0.1):
        t = 0.0
        while t < t_end:
            self.q.tick(now=t)
            t += step

    def test_messages_wait_their_turn(self):
        self.q.say("pierdes dos décimas en Copse", kind="corner", ttl=10, now=0)
        self.q.say("El de delante entra en boxes", kind="pit", ttl=10, now=0.1)
        self.assertEqual(self.sp.said, ["pierdes dos décimas en Copse"])     # el segundo espera
        self.run_until(10)
        self.assertEqual(self.sp.said[-1], "El de delante entra en boxes")

    def test_same_kind_replaces_waiting_message(self):
        self.q.say("primero", kind="info", now=0)
        self.q.say("Coche detrás a uno", kind="close", ttl=5, now=0.1)
        self.q.say("Coche detrás a cero coma seis", kind="close", ttl=5, now=0.2)
        self.run_until(6)
        self.assertNotIn("Coche detrás a uno", self.sp.said)
        self.assertIn("Coche detrás a cero coma seis", self.sp.said)

    def test_interrupt_and_expiry(self):
        self.q.say("un mensaje bastante largo que tarda varios segundos en decirse", kind="info", now=0)
        self.q.say("caduca pronto", kind="x", ttl=0.5, now=0.1)
        self.q.say("frena", interrupt=True, now=0.2)
        self.run_until(10)
        self.assertIn("frena", self.sp.said)
        self.assertNotIn("caduca pronto", self.sp.said)

    def test_disabled_says_nothing(self):
        self.sp.enabled = False
        self.q.say("hola", now=0)
        self.q.say("frena", interrupt=True, now=0)
        self.assertEqual(self.sp.said, [])


class UpdaterTest(unittest.TestCase):
    def test_versions_compare_as_numbers(self):
        self.assertTrue(updater.is_newer("1.10.0", "1.7.3"))
        self.assertTrue(updater.is_newer("v1.11.0", "1.10.0"))
        self.assertFalse(updater.is_newer("1.9.9", "1.10.0"))
        self.assertFalse(updater.is_newer("1.10.0", "1.10.0"))


def car(place, laps, dist, me=False, cls="GT3", name=None, behind=0.0, laps_behind=0, pits=False, stops=0, pace=100.0):
    return RaceCar(place, cls, name or f"P{place}", laps, dist, pits, stops, me, pace, pace, pace,
                   behind_leader=behind, laps_behind_leader=laps_behind)


class EngineerTest(unittest.TestCase):
    L = 4000.0

    def info(self, cars):
        return RaceInfo(True, self.L, 1800, None, cars)

    def test_gaps_use_game_timing(self):
        e = Engineer()
        e.update(self.info([car(1, 3, 1000, behind=0), car(2, 3, 950, me=True, behind=1.25),
                            car(3, 3, 900, behind=2.05)]), now=0)
        self.assertEqual(e.state["pos"], 2)
        self.assertAlmostEqual(e.state["ahead"], 1.25)
        self.assertAlmostEqual(e.state["behind"], 0.8)

    def test_several_overtakes_announced_once(self):
        e = Engineer()
        order = lambda me_place: [car(p, 3, 1000 - p, me=(p == me_place), name="yo" if p == me_place else f"r{p}")
                                  for p in range(1, 7)]
        e.update(self.info(order(5)), now=0)
        said = []
        for t, p in ((1, 4), (1.5, 3), (2, 2)):          # tres adelantamientos seguidos
            said += e.update(self.info(order(p)), now=t)
        said += e.update(self.info(order(2)), now=6)       # posición estable
        texts = [m for m, kind in said if kind == "position"]
        self.assertEqual(len(texts), 1)
        self.assertIn("Ganas tres posiciones", texts[0])

    def test_no_close_alert_on_first_lap(self):
        e = Engineer()
        said = e.update(self.info([car(1, 0, 100, me=True), car(2, 0, 90, behind=0.3)]), now=0)
        self.assertFalse([m for m, k in said if k == "close"])
        said = e.update(self.info([car(1, 1, 100, me=True), car(2, 1, 90, behind=0.4)]), now=10)
        self.assertTrue([m for m, k in said if k == "close"])

    def test_rival_pit_alert_once(self):
        e = Engineer()
        cars = lambda pit: [car(1, 3, 1000, name="delante", pits=pit, stops=0),
                            car(2, 3, 950, me=True, behind=1.0)]
        e.update(self.info(cars(False)), now=0)
        first = e.update(self.info(cars(True)), now=1)
        again = e.update(self.info(cars(True)), now=2)
        self.assertEqual([k for _, k in first], ["pit"])
        self.assertFalse(again)

    def test_not_a_race(self):
        e = Engineer()
        self.assertEqual(e.update(RaceInfo(False, self.L, None, None, [car(1, 1, 1, me=True)])), [])
        self.assertIsNone(e.state)


class FlagsAndSummaryTest(unittest.TestCase):
    L = 4000.0

    def info(self, cars, **kw):
        return RaceInfo(True, self.L, 1800, None, cars, **kw)

    def test_full_course_yellow_and_green(self):
        e = Engineer()
        cars = [car(1, 3, 1000, me=True), car(2, 3, 900, behind=5)]
        e.update(self.info(cars, phase=5), now=0)
        said = e.update(self.info(cars, phase=6, yellow_state=2), now=1)
        self.assertEqual([m for m, k in said if k == "flag"], ["Amarilla en todo el circuito. No adelantes",
                                                                "Boxes cerrados"])
        said = e.update(self.info(cars, phase=6, yellow_state=4), now=2)
        self.assertEqual([m for m, k in said if k == "flag"], ["Boxes abiertos"])
        said = e.update(self.info(cars, phase=5), now=3)
        self.assertEqual([m for m, k in said if k == "flag"], ["Verde, verde, verde"])

    def test_sector_yellow_and_blue_flag_not_repeated(self):
        e = Engineer()
        me = car(1, 3, 1000, me=True)
        e.update(self.info([me, car(2, 3, 900, behind=5)]), now=0)
        said = e.update(self.info([me, car(2, 3, 900, behind=5)], sector_flags=(0, 1, 0)), now=1)
        self.assertIn("Amarilla en el sector dos", [m for m, _ in said])
        said = e.update(self.info([me, car(2, 3, 900, behind=5)], sector_flags=(0, 1, 0)), now=2)
        self.assertFalse([m for m, k in said if k == "flag"])
        me.flag = 6
        said = e.update(self.info([me, car(2, 3, 900, behind=5)]), now=3)
        self.assertIn("Bandera azul, deja pasar", [m for m, _ in said])

    def test_race_summary_at_the_end(self):
        e = Engineer()
        order = lambda me_place, laps: [car(p, laps, 1000 - p * 10, me=(p == me_place),
                                            name="yo" if p == me_place else f"r{p}") for p in range(1, 6)]
        e.update(self.info(order(4, 0)), now=0)                 # sales cuarto
        for lap, (pos, t) in enumerate(((4, 10), (3, 20), (2, 30)), start=1):
            e.update(self.info(order(pos, lap)), now=t)
        said = e.update(self.info(order(2, 3), session_over=True, phase=8), now=40)
        self.assertEqual([k for _, k in said], ["raceend"])
        self.assertIn("Ganas dos posiciones", said[0][0])
        self.assertEqual((e.finished["start"], e.finished["finish"], e.finished["of"]), (4, 2, 5))
        self.assertEqual([r[1] for r in e.finished["log"]], [4, 3, 2])
        self.assertFalse(e.update(self.info(order(2, 3), session_over=True, phase=8), now=41))   # una vez

    def test_pit_rejoin_counts_cars_within_pit_loss(self):
        e = Engineer()
        cars = [car(1, 5, 1000, me=True), car(2, 5, 900, behind=8), car(3, 5, 800, behind=20),
                car(4, 5, 700, behind=45)]
        e.update(self.info(cars), now=0)
        self.assertEqual(e.pit_rejoin(30), 3)                   # pasan los que van a 8 y 20 s


class PitPlanTest(unittest.TestCase):
    def test_makes_it(self):
        from lmu_coach import pitplan
        p = pitplan.plan(10, 0.0, fuel=60, fuel_pl=3.0, ve=None, ve_pl=None)
        self.assertTrue(p.makes_it)
        self.assertEqual(pitplan.spoken(p), "Con este consumo llegas al final")

    def test_stop_lap_and_refuel(self):
        from lmu_coach import pitplan
        # 20 vueltas por delante, 30 L a 3 L/vuelta = 10 vueltas; justo cruzando meta
        p = pitplan.plan(20, 0.0, fuel=30, fuel_pl=3.0, ve=None, ve_pl=None, capacity=100)
        self.assertEqual(p.stop_in, 8)            # 1 vuelta para cruzar + 8 completas, con reserva
        # al salir faltan 20 - 1 - 8 = 11 vueltas: 11,35 × 3 = 34,05 L menos los 3 que quedan
        self.assertAlmostEqual(p.add_fuel, 31.05, places=2)
        p = pitplan.plan(20, 0.5, fuel=2.0, fuel_pl=3.0, ve=40, ve_pl=4.0)
        self.assertEqual(p.stop_in, 0)
        self.assertEqual(p.limit, "fuel")
        self.assertIn("Entra en boxes al acabar esta vuelta", pitplan.spoken(p, rejoin=3))
        self.assertIn("Volverías tercero", pitplan.spoken(p, rejoin=3))

    def test_energy_limits(self):
        from lmu_coach import pitplan
        p = pitplan.plan(15, 0.0, fuel=80, fuel_pl=3.0, ve=30, ve_pl=5.0)
        self.assertEqual(p.limit, "ve")
        self.assertIsNotNone(p.ve_target)
        self.assertLessEqual(p.ve_target, 100)

    def test_remaining_laps(self):
        from lmu_coach import pitplan
        self.assertEqual(pitplan.remaining_laps(None, 10, 100, 0.25), 9.75)
        # 10 min con vueltas de 100 s, a mitad de vuelta: 0,5 hasta meta + 6 (5,5 redondeado arriba)
        self.assertEqual(pitplan.remaining_laps(600, None, 100, 0.5), 6.5)
        self.assertIsNone(pitplan.remaining_laps(None, None, 100, 0))


class ChangelogTest(unittest.TestCase):
    def test_news_since_installed_version(self):
        from lmu_coach import changelog
        from lmu_coach.version import __version__
        self.assertEqual([v for v, _ in changelog.since("1.13.0", "1.15.0")], ["1.15.0", "1.14.0"])
        self.assertEqual(changelog.since("1.15.0", "1.15.0"), [])
        self.assertIn(__version__, changelog.CHANGES)        # cada versión publicada cuenta sus novedades


class CornerTipTest(unittest.TestCase):
    def fb(self, t=0.4, brake=0.0, vmin=0.0, thr=0.0):
        from types import SimpleNamespace
        from lmu_coach.coach import Feedback
        return Feedback(SimpleNamespace(idx=3), t, brake, vmin, thr, [], 0)

    def test_main_cause_is_spoken(self):
        from lmu_coach.coach import spoken_tip
        self.assertEqual(spoken_tip(self.fb(brake=-41)), "frenas cuarenta y un metros antes")
        self.assertEqual(spoken_tip(self.fb(vmin=-21)), "veintiún kilómetros por hora menos en el vértice")
        self.assertEqual(spoken_tip(self.fb(brake=-13, thr=60)), "aceleras sesenta metros tarde")   # pesa más
        self.assertEqual(spoken_tip(self.fb(brake=20, vmin=-8)), "frenas tarde y te pasas en el vértice")

    def test_silent_when_nothing_lost_or_no_clear_cause(self):
        from lmu_coach.coach import spoken_tip
        self.assertIsNone(spoken_tip(self.fb(t=-0.3, brake=-40)))
        self.assertIsNone(spoken_tip(self.fb(t=0.4)))


class SetupLimitsTest(unittest.TestCase):
    """El asistente de reglaje no propone lo imposible: ajustes al tope, fijos o en sentidos opuestos."""
    SETUP = {"WM_PRESSURE-W_FL": ("", "136 kPa"), "VM_FRONT_ANTISWAY": ("", "P4"), "VM_REAR_ANTISWAY": ("", "P1"),
             "VM_DIFF_POWER": ("", "Non-adjustable"), "VM_DIFF_PRELOAD": ("", "80 Nm"),
             "VM_ENGINE_BRAKEMAP": ("", "N/A"), "VM_BRAKE_BALANCE": ("", "52.2:47.8")}
    STEPS = {"WM_PRESSURE-W_FL": (0, 0, 74), "VM_FRONT_ANTISWAY": (4, 0, 7), "VM_REAR_ANTISWAY": (1, 0, 7),
             "VM_DIFF_POWER": (0, 0, 0), "VM_DIFF_PRELOAD": (80, 0, 200), "VM_ENGINE_BRAKEMAP": (0, 0, 0),
             "VM_BRAKE_BALANCE": (19, 0, 56)}

    def run_limits(self, sugs):
        from lmu_coach.setup_assistant import apply_limits
        return apply_limits(sugs, self.SETUP, self.STEPS)

    def sug(self, prio, title, changes):
        from lmu_coach.setup_assistant import Suggestion
        return Suggestion(prio, "x", title, "dato.", list(changes))

    def test_value_at_minimum_is_not_suggested(self):
        out = self.run_limits([self.sug(2, "Presión alta en DI", [("Presión en frío (DI)", "-6 kPa",
                                                                    "WM_PRESSURE-W_FL", -1)])])
        self.assertEqual(out[0].changes, [])
        self.assertEqual(out[0].priority, 3)
        self.assertIn("ya está al mínimo (136 kPa)", out[0].evidence)

    def test_fixed_settings_dropped_and_diff_falls_back_to_preload(self):
        out = self.run_limits([self.sug(1, "Sobreviraje a la salida", [
            ("Freno motor", "-1", "VM_ENGINE_BRAKEMAP", 0),
            ("Diferencial en tracción", "más bloqueo", "VM_DIFF_POWER", +1)])])
        self.assertEqual([c[0] for c in out[0].changes], ["Precarga del diferencial"])
        self.assertIn("ahora 80 Nm", out[0].changes[0][1])

    def test_opposite_requests_keep_the_most_important(self):
        out = self.run_limits([
            self.sug(2, "Sobreviraje a la salida", [("Barra estabilizadora tras.", "más blanda", "VM_REAR_ANTISWAY", -1)]),
            self.sug(1, "Subviraje en el vértice", [("Barra estabilizadora tras.", "más dura", "VM_REAR_ANTISWAY", +1),
                                                    ("Barra estabilizadora del.", "más blanda", "VM_FRONT_ANTISWAY", -1)])])
        first = next(s for s in out if s.title.startswith("Subviraje"))
        second = next(s for s in out if s.title.startswith("Sobreviraje"))
        self.assertEqual(len(first.changes), 2)
        self.assertEqual(second.changes, [])
        self.assertIn("pide lo contrario", second.evidence)

    def test_technique_only_advice_is_untouched(self):
        out = self.run_limits([self.sug(2, "El ABS trabaja mucho", [("Tu técnica", "pisa menos")])])
        self.assertEqual((out[0].priority, out[0].title), (2, "El ABS trabaja mucho"))


class RadioTest(unittest.TestCase):
    SNAP = {"fuel": 23.43, "fuel_pl": 2.91, "race": {"pos": 4, "of": 12, "cls": "GT3", "ahead": 1.23,
                                                     "behind": None, "trend_ahead": -0.31}, "ahead_name": "Rossi"}

    def test_templates_fill_and_skip_missing_parts(self):
        from lmu_coach import radio as R
        self.assertEqual(R.render("{combustible}, para {combustible_vueltas}", self.SNAP), "23,4 litros, para 8 vueltas")
        self.assertEqual(R.render("{nombre_delante} a {delante}. {tendencia_delante}", self.SNAP),
                         "Rossi a 1,2 segundos. Recortas 0,3 por vuelta")
        self.assertEqual(R.render("Posición {posicion}, detrás {detras}", self.SNAP), "Posición 4 de 12 en GT3")
        self.assertEqual(R.render("{energia}", self.SNAP), "Sin datos ahora")
        self.assertTrue(all(R.render("{" + f.key + "}", {}, examples=True) for f in R.FIELDS))

    def test_phrases_match_without_accents_or_case(self):
        from lmu_coach import radio as R
        self.assertEqual(R.find_command("Cuanto combustible me queda", R.DEFAULT_COMMANDS)["say"],
                         "{combustible}, para {combustible_vueltas}")
        self.assertIsNone(R.find_command("pon música", R.DEFAULT_COMMANDS))
        self.assertIn("cuándo paro", R.all_phrases(R.DEFAULT_COMMANDS))

    def test_whisper_text_matches_closest_phrase(self):
        from lmu_coach import radio as R
        from lmu_coach.whisper_asr import best_phrase
        phrases = R.all_phrases(R.DEFAULT_COMMANDS)
        self.assertEqual(best_phrase("Cuándo combustible me queda.", phrases)[0], "cuánto combustible me queda")
        self.assertEqual(best_phrase("¿A cuánto va el de delante?", phrases)[0], "a cuánto va el de delante")
        p, score = best_phrase("pon música de fondo", phrases)
        self.assertLess(score, 0.6)

    def test_push_to_talk_flow(self):
        import queue
        from lmu_coach import radio as R

        class FakeListener:
            def __init__(self):
                self.results, self.on, self.error = queue.Queue(), None, None
            def start(self, phrases):
                self.phrases = phrases
            def listen(self, on):
                self.on = on
            def close(self):
                pass

        held = [False]
        old = R.button_down
        R.button_down = lambda b: held[0]
        try:
            radio = R.Radio(FakeListener())
            cfg = {"radio": {"on": True, "button": {"type": "key", "vk": 0x70}, "commands": R.DEFAULT_COMMANDS}}
            snap = lambda: self.SNAP
            self.assertIsNone(radio.update(cfg, snap, now=0))
            held[0] = True
            self.assertEqual(radio.update(cfg, snap, now=1), ("listening", ""))
            self.assertTrue(radio.listener.on)
            radio.listener.results.put(("cuánto combustible me queda", 0.8))
            held[0] = False
            self.assertEqual(radio.update(cfg, snap, now=1.5), ("answer", "23,4 litros, para 8 vueltas"))
            self.assertFalse(radio.listener.on)
            # «repite» y una frase dicha con poca seguridad
            held[0] = True
            radio.update(cfg, snap, now=3)
            radio.listener.results.put(("repite", 0.9))
            self.assertEqual(radio.update(cfg, snap, now=3.2), ("answer", "23,4 litros, para 8 vueltas"))
            held[0] = True
            radio.update(cfg, snap, now=4)    # sigue pulsado: no vuelve a empezar
            held[0] = False
            radio.update(cfg, snap, now=5)
            held[0] = True
            radio.update(cfg, snap, now=6)
            radio.listener.results.put(("posición", 0.2))
            held[0] = False
            self.assertEqual(radio.update(cfg, snap, now=6.3), ("unknown", "«posición» (seguridad 0.20)"))
        finally:
            R.button_down = old


class SpotterTest(unittest.TestCase):
    def drive_circle(self, mirror):
        """Giro a la derecha en un círculo, con un rival por fuera y otro por dentro; el mundo puede ir espejado."""
        sp, said, extra = Spotter(still_s=1.5), [], []
        R, v = 150.0, 40.0
        for k in range(400):
            t = k * 0.05
            a = v * t / R
            x, z = R * math.sin(a), R * math.cos(a)
            vx, vz = v * math.cos(a), -v * math.sin(a)
            if mirror:
                x, vx = -x, -vx
            others = []
            for t0, t1, r in ((10, 14, R + 3), (12, 16, R - 3)):
                if t0 < t < t1:
                    ox, oz = r * math.sin(a), r * math.cos(a)
                    others.append((-ox if mirror else ox, oz, v))
            msg = sp.update(SpotFrame((x, z), (vx, vz), 0.3, others), now=t)
            if msg and msg[0] not in ("spot_ready", "spot_still"):
                said.append(msg[1])
            elif msg:
                extra.append(msg[0])
        sp.extra = extra
        return sp, said

    def test_learns_sides_in_both_conventions(self):
        for mirror in (False, True):
            sp, said = self.drive_circle(mirror)
            self.assertTrue(sp.calibrated)
            self.assertEqual(said[:2], ["Izquierda", "En medio"])
            self.assertEqual(said[-1], "Libre")
            self.assertEqual(sp.extra[0], "spot_ready")             # avisa una vez de que ya sabe los lados
            self.assertIn("spot_still", sp.extra)                   # y recuerda que siguen ahí

    def test_configurable_side_distance(self):
        sp = Spotter(side_max=2.5)
        sp.calib = 10                                                # ya calibrado
        sp._ready_said = True
        f = SpotFrame((0, 0), (40, 0), 0.0, [(0, 3.5, 40)])         # coche a 3,5 m del lateral
        self.assertIsNone(sp.update(f, now=0))
        sp.configure(side_max=4.8)
        self.assertIsNotNone(sp.update(f, now=1))

    def test_silent_until_calibrated(self):
        sp = Spotter()
        msg = sp.update(SpotFrame((0, 0), (40, 0), 0.0, [(0, 3, 40)]), now=0)
        self.assertIsNone(msg)


class DamageTest(unittest.TestCase):
    def test_new_damage_is_reported_once(self):
        d = DamageWatch()
        base = {"dents": [0] * 8, "detached": False, "flat": [False] * 4, "wheel_off": [False] * 4,
                "overheating": False}
        self.assertEqual(d.update(base, 0), [])
        hit = dict(base, dents=[0, 2, 0, 0, 0, 0, 0, 0], flat=[False, True, False, False])
        self.assertEqual(d.update(hit, 1), [("dmg_body", "Daños fuertes en la carrocería"), ("dmg_tyre", "Pinchazo delantera derecha")])
        self.assertEqual(d.update(hit, 2), [])
        self.assertEqual(d.state["level"], 2)


def lap(n, t, fuel=2.7, wear=0.6, note="", valid=True):
    return LapStats(n, t, valid, note, fuel_used=fuel, wear=[wear] * 4, wear_left=[100 - n * wear] * 4)


class StintTest(unittest.TestCase):
    def test_theil_sen_ignores_outlier(self):
        x = list(range(10))
        y = [100 + 0.1 * i for i in x]
        y[5] += 8                                     # una vuelta con trompo
        a, b = _theil_sen(x, y)
        self.assertAlmostEqual(b, 0.1, places=3)

    def test_split_by_pit_and_mistakes(self):
        laps = [lap(1, 101.0), *[lap(n, 100 + 0.1 * n) for n in range(2, 12)], lap(7, 0)]
        laps[5] = lap(6, 104.0)                          # error de 3,4 s
        laps += [lap(12, 140, note="boxes / vuelta de salida", fuel=-60)]
        laps += [lap(n, 100 + 0.05 * (n - 13)) for n in range(13, 23)]
        sts = stints([l for l in laps if l.time > 0])
        self.assertEqual(len(sts), 2)
        self.assertIn(6, [m[0].num for m in sts[0].mistakes])
        self.assertGreater(sts[0].slope, 0)
        self.assertAlmostEqual(sts[0].fuel_per_lap, 2.7)

    def test_strategy_needs_a_stop(self):
        plan = strategy(60, 100, 3.0, None, 90)
        self.assertEqual(plan.total_laps, 37)
        self.assertGreaterEqual(plan.stops, 1)
        self.assertEqual(sum(s.laps for s in plan.stints), plan.total_laps)


class OverviewTest(unittest.TestCase):
    def test_progress_per_track_and_car(self):
        from lmu_coach import lapstats
        from lmu_coach.sessions import SessionInfo

        def ses(day, times, car="296", imported=False):
            laps = [[i + 1, t, True, t / 3, t / 3, t / 3, ""] for i, t in enumerate(times)]
            return SessionInfo(f"{day}.duckdb", 0, 0, "Monza", "", car, "GT3", "Libres", f"{day} 20:00", "",
                               len(times), len(times), min(times), 1, imported=imported, lap_list=laps)

        sessions = [ses("2026-10-01", [110, 109]), ses("2026-10-05", [108, 107.5]), ses("2026-10-06", [107]),
                    ses("2026-10-06", [100], imported=True), ses("2026-10-02", [120], car="911")]
        out = lapstats.overview(sessions)
        self.assertEqual([(c.car, c.days) for c in out], [("296", 3), ("911", 1)])
        c = out[0]
        self.assertEqual((c.best, c.first_best, c.laps, c.last_day), (107, 109, 5, "2026-10-06"))
        self.assertAlmostEqual(c.gained, 2.0)
        self.assertAlmostEqual(c.last_week_gain, 2.0)
        self.assertIsNone(out[1].last_week_gain)


if __name__ == "__main__":
    unittest.main()
