"""Punto de entrada del .exe: sin argumentos abre la app; con --coach abre el overlay."""
import sys


def main():
    if "--coach" in sys.argv:
        from lmu_coach.app import main as coach_main
        coach_main([a for a in sys.argv[1:] if a != "--coach"])
    else:
        from lmu_coach.gui.main import main as gui_main
        gui_main()


if __name__ == "__main__":
    main()
