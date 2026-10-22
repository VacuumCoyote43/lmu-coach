"""Novedades de cada versión: la app las enseña una vez después de actualizar."""

CHANGES = {
    "1.16.0": [
        "Pantalla de inicio: tu última sesión, tu objetivo más cercano, la semana y un botón grande para el coach "
        "(vuelve a ella con 🏠).",
        "Barra de arriba más limpia: importar, copia de seguridad y diagnóstico están ahora en el menú ⋯.",
        "En cada sesión, más sitio para las vueltas y las gráficas; «Dónde pierdes tiempo» va al lado de las "
        "gráficas (el detalle de cada frenada, al pasar el ratón).",
        "Los grupos Vuelta, Carrera y Coche son ahora botones, para no confundirlos con sus pestañas.",
        "El mapa de la trazada ya no amontona los nombres de las frenadas.",
        "Se quita el Ranking.",
    ],
    "1.15.0": [
        "El coach te dice por qué pierdes en una curva: «frenas quince metros antes», «aceleras veinte metros tarde»…",
        "Modo práctica: clic derecho en una frenada de «Dónde pierdes tiempo» › «Practicar en el coach». En pista "
        "solo te habla de esa curva, pasada a pasada.",
        "Delta por voz al pasar por cada sector (actívalo en ⚙ Ajustes › Coach).",
        "Exportar imagen de una sesión para compartirla.",
    ],
    "1.14.0": [
        "Estrategia en directo: cuándo parar, cuánto repostar y en qué posición volverías.",
        "Banderas: amarilla en todo el circuito, boxes abiertos o cerrados, amarillas por sector y bandera azul.",
        "Resumen de carrera: posición vuelta a vuelta, diferencias y tu ritmo frente a tu clase "
        "(pestaña Carrera › Resumen de carrera).",
    ],
    "1.13.0": [
        "📈 Mi progreso: todos tus circuitos y coches, tu evolución y tu vuelta ideal.",
        "Objetivos de tiempo; en pista, el coach te dice a cuánto estás.",
    ],
    "1.12.0": [
        "⚙ Ajustes: elige uno a uno qué mensajes dicen el spotter, el ingeniero y el coach, y ajusta el spotter "
        "(distancia lateral, solape, pausa entre avisos).",
        "Asistente de bienvenida la primera vez que abres la app.",
        "Las pestañas de cada sesión, agrupadas en Vuelta, Carrera y Coche.",
    ],
}


def _key(v: str) -> tuple:
    return tuple(int(x) for x in v.split(".") if x.isdigit())


def since(old: str | None, new: str) -> list[tuple[str, list[str]]]:
    """Novedades de las versiones posteriores a «old» hasta «new» (la más nueva primero)."""
    lo = _key(old) if old else (0,)
    hi = _key(new)
    return [(v, items) for v, items in sorted(CHANGES.items(), key=lambda kv: _key(kv[0]), reverse=True)
            if lo < _key(v) <= hi]
