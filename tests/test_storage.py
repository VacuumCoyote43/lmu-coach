"""Pruebas de lo que guarda archivos: copia de sesiones, nombres de curvas, planes y decoraciones.
Todo en carpetas temporales: nunca toca los datos reales de la app."""
import os
import time
import unittest
from types import SimpleNamespace

from lmu_coach import archive, config, corners, goals, racelog, svm, training
from lmu_coach.car_images import CarImages

from .helpers import TempDirTest


class ArchiveTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.lmu = self.tmp / "lmu"
        self.dest = self.tmp / "copia"
        self.lmu.mkdir()
        old = time.time() - 120
        for name, size in (("a.duckdb", 1000), ("b.duckdb", 2000)):
            p = self.lmu / name
            p.write_bytes(os.urandom(size))
            os.utime(p, (old, old))
        wal = self.lmu / "b.duckdb.wal"
        wal.write_bytes(b"pendiente")
        os.utime(wal, (old, old))

    def test_copies_new_files_with_wal(self):
        r = archive.sync(self.lmu, self.dest)
        self.assertEqual((r["copied"], r["error"]), (2, None))
        self.assertTrue((self.dest / "b.duckdb.wal").exists())
        self.assertEqual((self.dest / "a.duckdb").read_bytes(), (self.lmu / "a.duckdb").read_bytes())
        self.assertEqual(archive.sync(self.lmu, self.dest)["copied"], 0)        # nada nuevo
        self.assertEqual(archive.stats(self.dest)[0], 2)

    def test_skips_file_being_recorded(self):
        os.utime(self.lmu / "a.duckdb")                                       # recién escrito
        r = archive.sync(self.lmu, self.dest)
        self.assertEqual(r["copied"], 1)
        self.assertFalse((self.dest / "a.duckdb").exists())

    def test_wal_merged_later_is_refreshed(self):
        archive.sync(self.lmu, self.dest)
        (self.lmu / "b.duckdb.wal").unlink()                                 # LMU pasa el .wal al archivo
        p = self.lmu / "b.duckdb"
        p.write_bytes(os.urandom(2500))
        old = time.time() - 120
        os.utime(p, (old, old))
        self.assertEqual(archive.sync(self.lmu, self.dest)["copied"], 1)
        self.assertFalse((self.dest / "b.duckdb.wal").exists())
        self.assertEqual((self.dest / "b.duckdb").stat().st_size, 2500)

    def test_never_touches_lmu_folder(self):
        before = {p.name: p.stat().st_mtime for p in self.lmu.iterdir()}
        archive.sync(self.lmu, self.dest)
        self.assertEqual(before, {p.name: p.stat().st_mtime for p in self.lmu.iterdir()})


class CornersTest(TempDirTest):
    MONZA = ("Autodromo Nazionale Monza", "Autodromo Nazionale Monza")

    def setUp(self):
        super().setUp()
        self._path, self._user = corners.USER_PATH, corners._user
        corners.USER_PATH, corners._user = self.tmp / "corner_names.json", None

    def tearDown(self):
        corners.USER_PATH, corners._user = self._path, self._user
        super().tearDown()

    def test_default_names_by_apex(self):
        self.assertEqual(corners.name_for(*self.MONZA, 970), "Rettifilo")
        self.assertIsNone(corners.name_for(*self.MONZA, 1500))
        z = SimpleNamespace(idx=6, apex=5230)
        self.assertEqual(corners.label(z, *self.MONZA), "F6 · Parabolica")
        self.assertEqual(corners.spoken(z, *self.MONZA), "en Parabolica")
        self.assertEqual(corners.spoken(SimpleNamespace(idx=3, apex=1500), *self.MONZA), "en la 3")

    def test_layout_is_deduced_from_braking_points(self):
        wec = [244, 773, 903, 1875, 2041, 2992]
        self.assertEqual(corners.resolve_layout("Silverstone Circuit", wec), "Silverstone Grand Prix Circuit - WEC")
        elms = [431, 1040, 1200, 2345, 2809]
        self.assertEqual(corners.resolve_layout("Silverstone Circuit", elms), "Silverstone Grand Prix Circuit - ELMS")

    def test_rename_and_reset(self):
        corners.set_name(*self.MONZA, 964, "Primera")
        self.assertEqual(corners.name_for(*self.MONZA, 960), "Primera")
        corners.set_name(*self.MONZA, 2154, "")                              # vacío: sin nombre
        self.assertIsNone(corners.name_for(*self.MONZA, 2154))
        corners.reset_name(*self.MONZA, 964)
        self.assertEqual(corners.name_for(*self.MONZA, 964), "Rettifilo")
        self.assertTrue(corners.USER_PATH.exists())


class TrainingStoreTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self._path = training.PLAN_PATH
        training.PLAN_PATH = self.tmp / "plans.json"

    def tearDown(self):
        training.PLAN_PATH = self._path
        super().tearDown()

    def test_save_load_and_match(self):
        plan = [training.Focus(2, 738, "F2", 0.5, ["frena antes"], "frena antes", 10)]
        training.save("Portimão", "296", plan)
        got = training.active("Portimão", "296")
        self.assertEqual(got[0].short, "frena antes")
        self.assertIs(training.focus_for(got, SimpleNamespace(apex=760)), got[0])
        self.assertIsNone(training.focus_for(got, SimpleNamespace(apex=1500)))
        training.clear("Portimão", "296")
        self.assertEqual(training.active("Portimão", "296"), [])


class CarImageGuessTest(unittest.TestCase):
    def setUp(self):
        self.ci = CarImages(None)
        self.ci._loaded = True
        self.ci._stems = {"21_26_AFCO95641716", "91_24_MANT4FC2B6C0", "397_26_296GT3", "397_25ELMS_911GT3R",
                          "30_25_DUQUB0EF584B", "30_DUQUEIN8BA0435F"}

    def test_guesses(self):
        self.assertEqual(self.ci._guess("Vista AF Corse 2026 #21:WEC"), "21_26_AFCO95641716")
        self.assertEqual(self.ci._guess("Manthey Ema 2024 #91:LM"), "91_24_MANT4FC2B6C0")
        self.assertEqual(self.ci._guess("296GT3 Custom Team 2026 #397"), "397_26_296GT3")
        self.assertEqual(self.ci._guess("911GT3R ELMS Custom Team 2025 #397"), "397_25ELMS_911GT3R")
        self.assertEqual(self.ci._guess("Duqueine Team #30:ELMS25"), "30_25_DUQUB0EF584B")
        self.assertIsNone(self.ci._guess("Equipo Inventado 2026 #5:LM"))


class GoalsTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self._path = goals.GOALS_PATH
        goals.GOALS_PATH = self.tmp / "goals.json"

    def tearDown(self):
        goals.GOALS_PATH = self._path
        super().tearDown()

    def test_set_get_clear(self):
        self.assertIsNone(goals.get("Monza", "296"))
        goals.set_goal("Monza", "296", 106.5)
        self.assertEqual(goals.get("Monza", "296"), 106.5)
        self.assertEqual(goals.all_goals(), {("Monza", "296", "Monza"): 106.5})
        goals.set_goal("Silverstone", "296", 120.0, "Silverstone - ELMS")      # un objetivo por trazado
        self.assertIsNone(goals.get("Silverstone", "296", "Silverstone - WEC"))
        self.assertEqual(goals.get("Silverstone", "296", "Silverstone - ELMS"), 120.0)
        goals.clear("Monza", "296")
        self.assertIsNone(goals.get("Monza", "296"))

    def test_parse_and_speech(self):
        self.assertEqual(goals.parse_time("1:46.5"), 106.5)
        self.assertEqual(goals.parse_time("1:46,250"), 106.25)
        self.assertEqual(goals.parse_time("98.7"), 98.7)
        self.assertIsNone(goals.parse_time("abc"))
        self.assertEqual(goals.spoken_gap(-0.1), "Objetivo conseguido")
        self.assertEqual(goals.spoken_gap(0.3), "Te faltan tres décimas para tu objetivo")


class ConfigTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self._path = config.CONFIG_PATH
        config.CONFIG_PATH = self.tmp / "config.json"

    def tearDown(self):
        config.CONFIG_PATH = self._path
        super().tearDown()

    def test_defaults_and_messages(self):
        cfg = config.load_config()
        self.assertTrue(config.msg_on(cfg, "spot_left"))
        self.assertFalse(config.msg_on(cfg, "spot_still"))          # desactivado de fábrica
        cfg["msgs"]["spot_left"] = False
        cfg["spot_side"] = 3.0
        config.save_config(cfg)
        again = config.load_config()
        self.assertFalse(config.msg_on(again, "spot_left"))
        self.assertEqual(again["spot_side"], 3.0)
        self.assertTrue(config.msg_on(again, "no_existe"))           # fuera del catálogo: siempre

    def test_every_message_key_is_unique_and_grouped(self):
        keys = [m.key for m in config.MESSAGES]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(m.group in config.GROUPS for m in config.MESSAGES))


class RaceLogTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self._dir = racelog.RACES_DIR
        racelog.RACES_DIR = self.tmp / "races"

    def tearDown(self):
        racelog.RACES_DIR = self._dir
        super().tearDown()

    def test_save_and_find_by_session_start(self):
        import json
        p = racelog.save({"start": 4, "finish": 2, "of": 9, "log": [(1, 4, 1.0, None, False)], "spoken": "x"},
                         "Monza", "296")
        d = json.loads(p.read_text(encoding="utf-8"))
        self.assertNotIn("spoken", d)
        d["saved"] = "2026-10-19 21:10"                      # la carrera empezó a las 20:30
        p.write_text(json.dumps(d), encoding="utf-8")
        self.assertEqual(racelog.find("Monza", "296", "2026-10-19 20:30")["finish"], 2)
        self.assertIsNone(racelog.find("Monza", "911", "2026-10-19 20:30"))
        self.assertIsNone(racelog.find("Monza", "296", "2026-10-19 22:00"))     # guardado antes de empezar


class SvmTest(TempDirTest):
    SAMPLE = r"""VehicleClassSetting="GT3 McLaren_720S_LMGT3_Evo WEC2025"
//VEH=D:\LMU\Vehicles\McLaren\95_25_UNIT382AB771.VEH
[GENERAL]
Notes=""
FuelSetting=85//0.86
[REARWING]
RWSetting=19//7.6 deg
[SUSPENSION]
FrontWheelTrackSetting=0//Non-adjustable
RearAntiSwaySetting=3//P3 18x2mm
[CONTROLS]
RearBrakeSetting=20//52.0:48.0
[FRONTLEFT]
PressureSetting=0//136 kPa
CamberSetting=12//-2.20 deg
[BASIC]
Downforce=0.500000
"""

    def test_parse_change_and_save(self):
        src = self.tmp / "a.svm"
        src.write_text(self.SAMPLE, encoding="utf-8")
        f = svm.parse(src)
        self.assertEqual((f.vehicle_class, f.veh_stem), ("GT3 McLaren_720S_LMGT3_Evo WEC2025", "95_25_UNIT382AB771"))
        self.assertEqual(f.entry("WM_PRESSURE-W_FL").text, "136 kPa")
        self.assertFalse(next(e for e in f.entries if e.key == "FrontWheelTrackSetting").adjustable)
        f.entry("VM_REAR_ANTISWAY").new_index = 2
        out = svm.save(f, self.tmp / "Portimao" / "menos barra", note="prueba")
        text = out.read_text(encoding="utf-8")
        self.assertIn("RearAntiSwaySetting=2//", text)
        self.assertIn('Notes="prueba"', text)
        self.assertIn("RWSetting=19//7.6 deg", text)          # lo demás, tal cual
        self.assertEqual(svm.parse(out).entry("VM_REAR_ANTISWAY").index, 2)

    def test_assistant_suggestions_respect_limits(self):
        from types import SimpleNamespace
        src = self.tmp / "a.svm"
        src.write_text(self.SAMPLE, encoding="utf-8")
        f = svm.parse(src)
        sug = SimpleNamespace(raw_changes=[("Barra tras.", "más dura", "VM_REAR_ANTISWAY", +1),
                                           ("Alerón", "un punto más", "VM_REAR_WING", +1),
                                           ("Presión", "menos", "WM_PRESSURE-W_FL", -1)])
        done = svm.apply_suggestions(f, [sug], {"VM_REAR_WING": (19, 0, 19), "VM_REAR_ANTISWAY": (3, 0, 7)})
        self.assertEqual(len(done), 1)                       # el alerón ya está al máximo; la presión, al mínimo
        self.assertEqual(f.entry("VM_REAR_ANTISWAY").new_index, 4)

    def test_track_folder_guess(self):
        folders = ["Bahrain", "Interlagos", "Portimao", "Silverstone", "Silverstonewec"]
        self.assertEqual(svm.guess_track_folder("Algarve International Circuit", folders), "Portimao")
        self.assertEqual(svm.guess_track_folder("Autódromo José Carlos Pace", folders), "Interlagos")


class DashboardTest(unittest.TestCase):
    def test_serves_page_and_state(self):
        import json
        import urllib.request
        from lmu_coach import dashboard
        d = dashboard.Dashboard(port=0)
        self.assertTrue(d.start())
        port = d._server.server_address[1]
        try:
            d.state = dashboard.snapshot({"lap": 3, "speed": 201.4, "gear": 5, "delta": -0.21,
                                          "sectors": {"cur": [None, None, None]}, "fuel": {"fuel_laps": 7.5}},
                                         {"flag": None, "last": 106.2})
            page = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode("utf-8")
            self.assertIn("LMU Coach · Panel", page)
            st = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/state", timeout=5).read())
            self.assertEqual((st["lap"], st["speed"], st["delta"], st["last"]), (3, 201, -0.21, 106.2))
            self.assertEqual(st["fuel"]["fuel_laps"], 7.5)
        finally:
            d.stop()

    def test_waiting_status(self):
        from lmu_coach import dashboard
        self.assertEqual(dashboard.snapshot({"status": "Esperando"}, {}), {"status": "Esperando", "sub": ""})


class LogTest(TempDirTest):
    def test_repeated_warning_written_once(self):
        import logging
        from lmu_coach import log as L
        h = logging.FileHandler(self.tmp / "t.log", encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
        L.log.addHandler(h)
        L.log.setLevel(logging.INFO)
        old_dir = L.LOG_DIR
        try:
            for _ in range(30):
                try:
                    raise RuntimeError("lectura fallida")
                except RuntimeError:
                    L.warn_once("prueba-repetida", "fallo de prueba")
            h.flush()
            txt = (self.tmp / "t.log").read_text(encoding="utf-8")
            self.assertEqual(txt.count("fallo de prueba"), 1)
            self.assertIn("RuntimeError: lectura fallida", txt)
            L.LOG_DIR = self.tmp
            self.assertEqual(L.recent_problems(1), 1)
        finally:
            L.log.removeHandler(h)
            h.close()
            L.LOG_DIR = old_dir


if __name__ == "__main__":
    unittest.main()
