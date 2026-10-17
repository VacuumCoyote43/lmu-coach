# PyInstaller: python -m PyInstaller lmu_coach.spec --noconfirm
# Genera dist/LMU Coach/LMU Coach.exe (app + modo coach con --coach)

a = Analysis(
    ["lmu_coach_main.py"],
    pathex=[],
    datas=[("assets/icon.png", "assets"), ("assets/icon.ico", "assets")],
    hiddenimports=["lmu_coach.app", "lmu_coach.gui.main", "lmu_coach.gui.launcher", "uuid", "decimal", "ipaddress"],  # duckdb los importa en tiempo de ejecución
    excludes=["PyQt5", "PyQt6", "PySide2", "matplotlib", "scipy", "pandas", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LMU Coach",
    icon="assets/icon.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LMU Coach", upx=False)
