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


def main():
    if "--diag-session" in sys.argv:
        i = sys.argv.index("--diag-session")
        _diag_session(sys.argv[i + 1], sys.argv[i + 2])
        return
    if "--coach" in sys.argv:
        from lmu_coach.app import main as coach_main
        coach_main([a for a in sys.argv[1:] if a != "--coach"])
    else:
        from lmu_coach.gui.main import main as gui_main
        gui_main()


if __name__ == "__main__":
    main()
