"""Pruebas con sesiones reales de LMU (solo si este PC las tiene; si no, se saltan).

Abren sesiones de verdad y pasan por todos los análisis y por la ventana principal sin pantalla.
"""
import sys
import time
import unittest

from .helpers import offscreen, real_sessions

SESSIONS = real_sessions(limit=3)
NO_DATA = "este PC no tiene sesiones de LMU con vueltas válidas"


@unittest.skipUnless(SESSIONS, NO_DATA)
class AnalysisTest(unittest.TestCase):
    def test_every_analysis_runs(self):
        from lmu_coach import analysis, lapstats, setup_assistant, training
        from lmu_coach.sessions import SessionData
        for info in SESSIONS:
            with self.subTest(session=info.path):
                sd = SessionData(info)
                valid = [l for l in sd.laps if l.valid]
                self.assertGreaterEqual(len(valid), 3)
                best = min(valid, key=lambda l: l.time)
                ref = analysis.by_distance(sd.lap_data(best.num), sd.track_len)
                other = analysis.by_distance(sd.lap_data(valid[0].num), sd.track_len)
                zones = analysis.compare_zones(ref, other, analysis.delta(ref, other))
                self.assertTrue(zones, "debería encontrar frenadas")
                stats = lapstats.lap_stats(sd)
                self.assertTrue(stats)
                lapstats.stints(stats)
                lapstats.consistency(sd)
                rep = setup_assistant.analyze(sd)
                self.assertTrue(rep.zones)
                focus, summary = training.build(sd)
                self.assertEqual(summary["laps"], len(valid))

    def test_ab_comparison_of_two_sessions(self):
        from lmu_coach import abtest
        from lmu_coach.sessions import SessionData
        a = SESSIONS[0]
        others = [s for s in real_sessions() if s.track == a.track and s.car == a.car and s.path != a.path]
        if not others:
            self.skipTest("no hay otra sesión con el mismo coche y circuito")
        r = abtest.compare(SessionData(a), SessionData(others[0]))
        self.assertIsNotNone(r.a.pace)
        self.assertTrue(r.corners)
        self.assertTrue(r.verdict())

    def test_coach_lap_from_history(self):
        from lmu_coach.sessions import SessionData
        info = SESSIONS[0]
        lap = SessionData(info).to_coach_lap(info.best_lap)
        self.assertAlmostEqual(lap.lap_time, info.best, places=2)


@unittest.skipUnless(SESSIONS, NO_DATA)
class MainWindowTest(unittest.TestCase):
    """Abre la app sin pantalla, una sesión y todas sus pestañas; falla si salta cualquier error dentro de Qt."""

    @classmethod
    def setUpClass(cls):
        offscreen()
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from lmu_coach.gui import theme
        theme.apply(cls.app)

    def pump(self, n=15):
        for _ in range(n):
            self.app.processEvents()
            time.sleep(0.02)

    def test_open_session_and_all_tabs(self):
        errors = []
        old_hook = sys.excepthook
        sys.excepthook = lambda t, v, tb: errors.append(f"{t.__name__}: {v}")
        try:
            from lmu_coach.gui import main as M
            w = M.MainWindow()
            w.resize(1500, 900)
            w.show()
            t0 = time.time()
            while w.worker and w.worker.isRunning() and time.time() - t0 < 120:
                self.pump(1)
            self.pump()
            w._open(SESSIONS[0])
            self.pump(30)
            v = w.view
            for g, i in v.all_pages():
                v.show_page(g, i)
                self.pump(20)
            v.laps.selectRow(min(2, v.laps.rowCount() - 1))
            self.pump(20)
            w.close()
        finally:
            sys.excepthook = old_hook
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
