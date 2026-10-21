"""Configuración del modo coach (config.json) y catálogo de todo lo que puede decir por voz.

La comparten el coach (proceso aparte, tkinter) y la ventana de Ajustes de la app: la app escribe el
archivo y el coach lo vuelve a leer en cuanto cambia, así que los ajustes se aplican sin reiniciarlo.
"""
import json
from dataclasses import dataclass

from .paths import CONFIG_PATH

DEFAULT_CONFIG = {
    "x": 60, "y": 60, "opacity": 0.93, "beep_on_brake": False,
    "voice": True, "voice_name": None, "voice_rate": 1.2,
    "temps": True, "engineer": True, "spotter": True,
    # spotter
    "spot_len": 5.2,         # m de solape para considerar que un coche va «al lado»
    "spot_side": 4.8,        # m de separación lateral máxima
    "spot_gap": 0.6,         # s mínimos entre dos avisos del spotter
    "spot_still_s": 4.0,     # cada cuánto recordar que sigue ahí (si «Sigue ahí» está activado)
    "spot_overlay": True,    # barras laterales en el overlay
    # ingeniero
    "eng_close_s": 1.0,      # «coche detrás» por debajo de esta diferencia
    "eng_fast_s": 2.5,       # aviso de clase más rápida con esta antelación
    "eng_summary_every": 1,  # resumen cada N vueltas
    "eng_pit_loss": 30.0,    # s que pierdes en una parada (entrar, repostar y salir), para saber dónde vuelves
    # coach
    "delta_every": 0,        # decir el delta con tu referencia cada N sectores (0 = nunca)
    "practice_corner": None,  # modo práctica: solo se habla de esta frenada (nº de curva)
    "msgs": {},              # {clave: True/False} para cada mensaje del catálogo
}


@dataclass(frozen=True)
class Msg:
    key: str
    group: str
    label: str
    example: str
    default: bool = True
    help: str = ""


GROUPS = {
    "spotter": "Spotter",
    "engineer": "Ingeniero de carrera",
    "coach": "Coach (vuelta y frenadas)",
    "car": "Coche: daños, combustible y frenos",
}

MESSAGES = [
    # spotter
    Msg("spot_left", "spotter", "Coche a la izquierda", "Izquierda"),
    Msg("spot_right", "spotter", "Coche a la derecha", "Derecha"),
    Msg("spot_middle", "spotter", "Coches a los dos lados", "En medio"),
    Msg("spot_clear", "spotter", "Ya no hay nadie al lado", "Libre"),
    Msg("spot_clear_side", "spotter", "Se va uno de los dos lados", "Libre a la izquierda",
        help="Cuando ibas en medio y uno de los dos coches se queda atrás o te pasa"),
    Msg("spot_still", "spotter", "Sigue ahí (recordatorio)", "Sigue a la izquierda", default=False,
        help="Lo repite mientras el coche siga a tu lado (cada cuánto: ajuste de abajo)"),
    Msg("spot_ready", "spotter", "Spotter listo", "Spotter listo", default=False,
        help="Al principio el spotter aprende qué lado es cuál con tus primeras curvas; avisa cuando ya lo sabe"),
    # ingeniero
    Msg("position", "engineer", "Cambios de posición", "Subes a la posición cuatro"),
    Msg("close", "engineer", "Coche de tu clase encima", "Coche detrás a cero coma ocho"),
    Msg("pit", "engineer", "Rival directo entra en boxes", "El de delante entra en boxes"),
    Msg("fastclass", "engineer", "Clase más rápida te alcanza", "Hypercar detrás, déjale sitio"),
    Msg("summary", "engineer", "Resumen de cada vuelta", "Posición tres de doce. Delante a uno coma dos"),
    Msg("end5", "engineer", "Quedan cinco minutos", "Quedan cinco minutos"),
    Msg("lastlap", "engineer", "Última vuelta", "Última vuelta"),
    Msg("flag", "engineer", "Banderas amarilla y coche de seguridad", "Amarilla en el sector dos"),
    Msg("pitwindow", "engineer", "Estrategia: cuándo parar", "Para en dos vueltas, reposta treinta litros",
        help="Con tu consumo real y lo que queda de carrera; también te dice en qué posición volverías"),
    Msg("raceend", "engineer", "Resumen al acabar la carrera", "Carrera terminada. Posición cuatro de doce"),
    # coach
    Msg("brake", "coach", "«Frena» antes de cada frenada", "Frena"),
    Msg("plan", "coach", "Objetivo del plan antes de la curva", "Rettifilo: frena 10 metros antes"),
    Msg("corner", "coach", "Tiempo ganado o perdido en cada curva", "Pierdes dos décimas en Parabolica"),
    Msg("corner_tip", "coach", "Consejo concreto en la curva", "En la 6 frenas 15 metros antes que en tu mejor vuelta",
        help="Qué haces distinto: punto de frenada, velocidad mínima o salida"),
    Msg("delta", "coach", "Delta con tu referencia", "Más tres décimas", default=False,
        help="Se dice al pasar por cada sector (cada cuánto: pestaña Coach)"),
    Msg("lap", "coach", "Tiempo de cada vuelta", "Uno cuarenta y seis seis. Más dos décimas"),
    Msg("invalid", "coach", "Vuelta invalidada", "Vuelta invalidada"),
    Msg("goal", "coach", "Objetivo de tiempo", "Te faltan tres décimas para tu objetivo"),
    # coche
    Msg("fuel", "car", "Combustible o energía bajos", "Combustible para dos vueltas"),
    Msg("brakes", "car", "Frenos muy calientes", "Frenos delanteros muy calientes"),
    Msg("dmg_body", "car", "Daños en la carrocería", "Daños en la carrocería"),
    Msg("dmg_part", "car", "Pieza perdida", "Has perdido alguna pieza"),
    Msg("dmg_tyre", "car", "Pinchazo o rueda perdida", "Pinchazo delantera izquierda"),
    Msg("dmg_engine", "car", "Motor sobrecalentado", "Motor sobrecalentado"),
]
BY_KEY = {m.key: m for m in MESSAGES}


def msg_on(cfg: dict, key: str) -> bool:
    """¿Está activado este mensaje? (los que no están en el catálogo, siempre)."""
    m = BY_KEY.get(key)
    if m is None:
        return True
    return bool((cfg.get("msgs") or {}).get(key, m.default))


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))     # copia profunda
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            cfg.update(data)
    except (OSError, ValueError):
        pass
    if not isinstance(cfg.get("msgs"), dict):
        cfg["msgs"] = {}
    return cfg


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def config_mtime() -> float:
    try:
        return CONFIG_PATH.stat().st_mtime
    except OSError:
        return 0.0
