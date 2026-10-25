# PyInstaller: python -m PyInstaller lmu_coach.spec --noconfirm
# Genera dist/LMU Coach/LMU Coach.exe (app + modo coach con --coach)
from PyInstaller.utils.hooks import collect_all

# Whisper (radio con el ingeniero): librerías nativas y datos que PyInstaller no ve solo
datas, binaries, hidden = [("assets/icon.png", "assets"), ("assets/icon.ico", "assets")], [], []
for pkg in ("faster_whisper", "ctranslate2", "tokenizers", "av", "edge_tts", "aiohttp", "certifi"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h

a = Analysis(
    ["lmu_coach_main.py"],
    pathex=[],
    datas=datas,
    binaries=binaries,
    hiddenimports=["lmu_coach.app", "lmu_coach.gui.main", "lmu_coach.gui.launcher", "uuid", "decimal", "ipaddress",
                   "winrt.windows.media.speechrecognition", "winrt.windows.globalization", "winrt.windows.foundation",
                   "winrt.windows.foundation.collections", "winrt.runtime", "asyncio",
                   "lmu_coach.whisper_asr", "lmu_coach.speech_edge"] + hidden,  # duckdb los importa en tiempo de ejecución
    excludes=["PyQt5", "PyQt6", "PySide2", "matplotlib", "scipy", "pandas", "IPython", "pytest", "torch",
              "tensorflow", "onnxruntime"],
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
