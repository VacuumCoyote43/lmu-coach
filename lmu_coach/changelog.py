"""Novedades de cada versión: la app las enseña una vez después de actualizar."""

CHANGES = {
    "1.20.0": [
        "🧾 Debrief de cada sesión: las 3 cosas que más tiempo te darían, ordenadas por lo que ganarías por vuelta, "
        "con un botón para cada una (practicar la curva, abrir el setup, ver la consistencia o fijar el objetivo). "
        "Al aparecer una sesión nueva, abajo a la derecha sale un botón para verlo.",
        "📱 Panel en el móvil o la tablet: abre en el navegador la dirección de ⚙ Ajustes › General (o escanea el QR) "
        "y tendrás delta, sectores, combustible, estrategia, diferencias, temperaturas, banderas y spotter.",
    ],
    "1.19.0": [
        "Voces neuronales de Microsoft Edge para el coach (Álvaro, Elvira, Ximena…): casi humanas. Elígelas en "
        "⚙ Ajustes › General › Voz.",
        "Las frases urgentes (frena, spotter, banderas) se preparan al elegir la voz y suenan al instante; el resto "
        "se genera la primera vez (hace falta internet) y se guarda.",
        "Sin internet, esa frase la dice la voz de Windows, que sigue disponible para elegirla.",
    ],
    "1.18.1": [
        "Ajustes › Radio: barra de progreso al descargar el modelo de Whisper, con los MB que van y los que faltan.",
    ],
    "1.18.0": [
        "La radio con el ingeniero usa Whisper: entiende mucho mejor, también con ruido, sin internet. Descarga el "
        "modelo una vez en ⚙ Ajustes › Radio (el «base», ~145 MB, responde en medio segundo).",
        "Ya no hace falta decir la frase exacta: se busca la más parecida a lo que dices.",
        "El reconocimiento de Windows sigue disponible como alternativa.",
    ],
    "1.17.1": [
        "Ajustes › Radio: barra con el nivel del micrófono en directo, para ver si la app te oye.",
        "La radio usa ahora el reconocimiento de voz moderno de Windows (mucho más preciso, sin internet); el "
        "clásico queda como alternativa.",
        "Si no te entiende, el coach te dice qué ha oído y con qué seguridad, para ajustar la «Seguridad mínima».",
    ],
    "1.17.0": [
        "📻 Radio con el ingeniero: mantén pulsado un botón del volante (o una tecla), pregunta y te contesta. "
        "Tú eliges las frases y qué datos responde cada una (⚙ Ajustes › Radio), entre más de 35: combustible, "
        "energía, estrategia, rivales, neumáticos, presiones, frenos, motor, pista, objetivo…",
        "🛠 Editor de setups: parte del reglaje que tienes cargado en LMU, cámbialo dentro de los límites de tu "
        "coche (o aplica las sugerencias del asistente) y guárdalo para cargarlo en el garaje.",
        "🧪 Comparar setups (A/B): dos sesiones con el mismo coche y circuito, tu ritmo real y curva a curva, y qué "
        "cambiaba del reglaje.",
    ],
    "1.16.1": [
        "Asistente de reglaje más realista: ya no propone bajar lo que está al mínimo (como la presión) ni subir lo "
        "que está al máximo, ni tocar ajustes que tu coche no permite cambiar.",
        "Cada cambio sugerido muestra el valor que llevas ahora, y si dos sugerencias piden mover lo mismo en "
        "sentidos opuestos, se queda la más importante.",
    ],
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
