# Plan: leer las repeticiones de LMU (`.Vcr`)

**Objetivo:** sacar de los archivos de repetición de LMU (`UserData\Replays\*.Vcr`) la posición y la velocidad de **todos los coches** de la sesión a lo largo del tiempo. Con eso, la pestaña «Repetición» puede mostrar a los rivales y la app puede analizar carreras completas (huecos, adelantamientos, ritmo de cada coche).

**Restricción:** solo lectura. No se modifica el juego ni sus archivos.

## Lo que sabemos hoy

| | |
|---|---|
| Formato | gMotor de rFactor 2: cabecera de texto `//[[gMb1.002f (c)2016 ]]`, después bloques binarios (`IRSR`…) |
| Documentación pública | **Ninguna.** Ni siquiera en la comunidad de rFactor 2 hay un lector conocido; un autor de una herramienta para rFactor 1 pidió la estructura de rF2 y no la consiguió |
| Cifrado | **No parece cifrado:** entropía ~6 bits/byte y zlib lo reduce al 32 % |
| Compresión | Propia, no gzip/zlib. Casi no hay texto legible (ni nombres de pilotos ni de coches), así que probablemente son **valores cuantizados o deltas empaquetados a nivel de bits** |
| Tamaño | Libres ~1 MB; carreras hasta **2,6 GB**, así que el lector tiene que leer por partes sin cargar el archivo entero en memoria |
| Ventaja clave | Para tus propias sesiones tenemos **la telemetría `.duckdb` de la misma sesión**: posición, velocidad y tiempos exactos de tu coche. Son datos conocidos con los que buscar dónde y cómo están codificados en el `.Vcr` |

## Resultado de la Fase 0 (16/10/2026): el camino corto no sirve

Medido con `tools/replay_probe.py` sobre una repetición de carrera de 44 coches, primero parada y después **avanzando a mitad de carrera** (30 s en cada caso):

- El *scoring* publica **los 44 participantes** (piloto, coche, `mControl = 3`, repetición), pero con las **posiciones de parrilla congeladas**: tiempo de sesión 0, vuelta 0 y fase de juego 9 ("pausa").
- La **telemetría está vacía** (0 coches).
- No cambia nada mientras la repetición avanza: LMU rellena la memoria compartida **una vez al cargar la repetición** y no la actualiza durante la reproducción.

**Conclusión:** para tener los coches en movimiento hay que leer el `.Vcr` (Fases 1–5). Lo que sí aprovechamos es que la **lista de participantes al cargar la repetición** es un dato conocido para la Fase 3 (identificar nombres de pilotos y coches dentro del `.Vcr`).

## Fase 0 — Comprobar si hace falta (½ día)

Antes de invertir semanas, probar el **camino corto**: reproducir una repetición dentro de LMU y ver si la memoria compartida (`LMU_Data`) publica los datos de **todos los coches** mientras se ve.

- Si **sí** → «grabar repetición»: la app captura los datos mientras LMU reproduce la repetición, aunque sea a velocidad acelerada. Son unos 3–4 días de trabajo y aguanta las actualizaciones del juego. **Probablemente el plan termine aquí.**
- Si **no** → seguir con la Fase 1.

Revisar también el EULA de LMU sobre ingeniería inversa. Leer tus propios archivos para uso personal suele estar bien, pero si se publica un lector conviene confirmarlo.

## Fase 1 — Estructura del contenedor (2–4 días)

Meta: saber dónde empieza y acaba cada bloque y cada fotograma, y cómo se marca el tiempo.

1. **Repeticiones controladas.** Grabar sesiones mínimas para comparar:
   - A: 20 s parado en boxes;
   - B: 1 vuelta tú solo;
   - C: la misma vuelta con 1 IA;
   - D: igual que B pero de doble duración.
2. Herramienta propia en `tools/vcr/` que:
   - trocea el archivo por marcas de bloque y mide entropía y tamaño de cada trozo;
   - compara A, B, C y D: qué crece con la duración (fotogramas) y qué con el número de coches (estado por coche).
3. Localizar la **cabecera de sesión** (circuito, número de coches y pilotos) y la **frecuencia de fotogramas**.

✅ **Punto de decisión:** si al acabar no se distinguen fotogramas ni bloques por coche, **parar**. El formato sería demasiado opaco para el esfuerzo.

## Fase 2 — Decodificar el estado de cada coche (1–2 semanas)

Meta: posición (x, y, z) y orientación de cada coche en cada fotograma.

1. Alinear en el tiempo la repetición B con su `.duckdb`: sabemos dónde estaba tu coche en cada instante.
2. **Búsqueda por correlación** (script): probar codificaciones típicas sobre los bytes de cada fotograma y quedarse con la que encaje con la trayectoria conocida:
   - float32 o float16;
   - int16 escalado;
   - deltas respecto al fotograma anterior;
   - fotogramas clave cada N fotogramas con deltas entre medias;
   - campos de bits.
3. Validar con la sesión C: la segunda trayectoria decodificada (la IA) tiene que ser una vuelta coherente sobre el trazado.

✅ **Punto de decisión:** tu trayectoria reconstruida debe quedar a menos de 1 m de la de la telemetría. Si no se consigue, parar.

## Fase 3 — Identidades y eventos (3–5 días)

Nombres de pilotos y coches (los fragmentos como `PORT`/`IMAO` sugieren texto codificado o con algún desplazamiento), número de vuelta, entradas a boxes, banderas. Se cruzan con los resultados de la sesión que LMU guarda en `UserData\Log\Results` (XML legible) para confirmar.

## Fase 4 — Robustez (2–3 días)

- Lectura por partes para los archivos de 2,6 GB, con progreso y cancelación.
- Probar todos tus circuitos, los tipos de sesión (P/Q/R) y varias versiones del juego.
- **Detectar la versión del formato** y avisar en lugar de mostrar datos erróneos si LMU lo cambia.

## Fase 5 — Integrarlo en la app (3–4 días)

- «Importar repetición»: convertir el `.Vcr` a un archivo propio rápido de leer (duckdb), una sola vez.
- La pestaña «Repetición» muestra todos los coches, con etiquetas de piloto y la clasificación en ese momento.
- Análisis de carrera: huecos con el de delante y el de detrás, ritmo por vuelta de cada rival, comparación de tu vuelta con la de cualquier rival de esa sesión.

## Resumen

| Fase | Esfuerzo | Riesgo |
|---|---|---|
| 0 Camino corto (memoria compartida) | ½ día | bajo — decide si el resto hace falta |
| 1 Contenedor | 2–4 días | medio |
| 2 Estado por coche | 1–2 semanas | **alto** |
| 3 Identidades y eventos | 3–5 días | medio |
| 4 Robustez | 2–3 días | medio |
| 5 Integración | 3–4 días | bajo |

**Total por el camino largo:** unas 3–5 semanas de trabajo a ratos, con dos puntos de decisión. El mayor riesgo es que una actualización de LMU cambie el formato y obligue a revisar las Fases 2 y 3.

**Recomendación:** empezar por la **Fase 0**. Si la memoria compartida publica todos los coches durante la repetición, tendrás el mismo resultado en días en lugar de semanas, y aguantará las actualizaciones del juego.
