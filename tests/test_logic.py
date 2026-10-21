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


class SpotterTest(unittest.TestCase):
    def drive_circle(self, mirror):
        """Giro a la derecha en un círculo, con un rival por fuera y otro por dentro; el mundo puede ir espejado."""
        sp, said = Spotter(), []
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
            if msg:
                said.append(msg)
        return sp, said

    def test_learns_sides_in_both_conventions(self):
        for mirror in (False, True):
            sp, said = self.drive_circle(mirror)
            self.assertTrue(sp.calibrated)
            self.assertEqual(said[:2], ["Izquierda", "En medio"])
            self.assertEqual(said[-1], "Libre")

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
        self.assertEqual(d.update(hit, 1), ["Daños fuertes en la carrocería", "Pinchazo delantera derecha"])
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


if __name__ == "__main__":
    unittest.main()
