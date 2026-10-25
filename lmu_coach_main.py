"""Punto de entrada del .exe: sin argumentos abre la app; con --coach abre el overlay."""
import sys
from pathlib import Path


def _diag_session(path, out):
    """Diagnóstico: intenta leer los canales de análisis de una sesión y vuelca los errores completos."""
    import traceback
    lines = []
    try:
        from lmu_coach.sessions import SessionData, read_session_info
        sd = SessionData(read_session_info(Path(path)))
        for name in ("Fuel Level", "Virtual Energy", "TyresPressure", "TyresTempLeft"):
            try:
                ch = sd.channel(name)
                lines.append(f"{name}: {None if ch is None else (ch[0].shape, ch[1].shape)}")
            except Exception:
                lines.append(f"{name}: ERROR\n{traceback.format_exc()}")
        lines.append("errores registrados: " + repr(getattr(sd, "channel_errors", {})))
        try:
            from lmu_coach.setup_assistant import analyze
            rep = analyze(sd)
            lines.append(f"asistente: {len(rep.suggestions)} sugerencias, {len(rep.zones)} curvas")
            lines += [f"  {s.priority} · {s.title}" for s in rep.suggestions]
        except Exception:
            lines.append(f"asistente: ERROR\n{traceback.format_exc()}")
    except Exception:
        lines.append(traceback.format_exc())
    Path(out).write_text("\n".join(lines), encoding="utf-8")


def _selftest_voice(out):
    """Comprueba que el reconocimiento de voz moderno funciona dentro del .exe (prepara las frases y escucha)."""
    import time
    import traceback
    lines = []
    try:
        from lmu_coach import radio as R
        lines.append(f"moderno disponible: {R.ModernListener.available()}")
        lst = R.make_listener("auto")
        lines.append(f"motor: {type(lst).__name__}")
        lst.start(R.all_phrases(R.DEFAULT_COMMANDS))
        t = time.time()
        while not lst.ready and not lst.error and time.time() - t < 10:
            time.sleep(0.05)
        lines.append(f"listo: {lst.ready} · error: {lst.error}")
        lst.listen(True)
        time.sleep(1)
        lst.listen(False)
        time.sleep(1)
        lines.append(f"error tras escuchar: {lst.error}")
        lst.close()
        # Whisper: cargar el modelo y transcribir un .wav (si se pasa)
        from lmu_coach import whisper_asr as W
        lines.append(f"whisper disponible: {W.available()} · modelo base: {W.is_downloaded('base')}")
        if W.available() and W.is_downloaded("base"):
            wl = W.WhisperListener("base")
            wl.start(R.all_phrases(R.DEFAULT_COMMANDS))
            t = time.time()
            while not wl.ready and not wl.error and time.time() - t < 60:
                time.sleep(0.1)
            lines.append(f"whisper listo: {wl.ready} · error: {wl.error} · {time.time() - t:.1f} s")
            wav = sys.argv[sys.argv.index("--selftest-voice") + 2] if len(sys.argv) > sys.argv.index(
                "--selftest-voice") + 2 else None
            if wav and wl.ready:
                import wave
                import numpy as np
                with wave.open(wav) as w:
                    audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
                t = time.time()
                wl._transcribe(audio)
                lines.append(f"whisper oye: {wl.results.get(timeout=30)} · «{wl.last_text}» · {time.time() - t:.2f} s")
        # voces neuronales de Edge
        from lmu_coach import speech_edge as E
        lines.append(f"edge disponible: {E.available()}")
        t = time.time()
        p = E.generate(f"Prueba de voz {time.time():.0f}", "es-ES-AlvaroNeural", 1.2)
        lines.append(f"edge genera: {p.stat().st_size} bytes en {time.time() - t:.2f} s")
        p.unlink()
    except Exception:
        lines.append(traceback.format_exc())
    Path(out).write_text("\n".join(lines), encoding="utf-8")


def main():
    if "--selftest-voice" in sys.argv:
        _selftest_voice(sys.argv[sys.argv.index("--selftest-voice") + 1])
        return
    if "--diag-session" in sys.argv:
        i = sys.argv.index("--diag-session")
        _diag_session(sys.argv[i + 1], sys.argv[i + 2])
        return
    if "--coach" in sys.argv:
        from lmu_coach.app import main as coach_main
        coach_main([a for a in sys.argv[1:] if a != "--coach"])
    else:
        from lmu_coach.gui.launcher import main as gui_main
        gui_main()


if __name__ == "__main__":
    main()
