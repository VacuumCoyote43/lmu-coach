# Formato de las repeticiones de LMU (`.Vcr`)

Deducido por ingeniería inversa sobre repeticiones propias (16/10/2026), en modo solo lectura y sin modificar el juego. El lector está en `lmu_coach/vcr.py` y las herramientas de análisis en `tools/vcr/`.

**Validación:** las posiciones del `.Vcr` reproducen la velocidad registrada por la telemetría de LMU con una correlación de **1,0000** y un error mediano de **0,28 km/h** (más de una hora de carrera, 39.118 muestras), y el tiempo coincide **sin desfase**.

## Estructura general

```
cabecera de texto   //[[gMb1.002f (c)2016    ]] [[            ]]\n
"IRSR"              4 bytes
u32                 marcas (0x80000008)
u32                 puntero al bloque final (offset absoluto)
u32                 0
fotogramas …        (desde aquí hasta el bloque final)
bloque final        información de la sesión y participantes
```

## Fotogramas

Van seguidos y en orden de tiempo, a **50 Hz** (Δt = 0,02 s).

| Campo | Tipo | |
|---|---|---|
| tiempo | f32 | tiempo de sesión en segundos: el mismo reloj que la telemetría (`GPS Time`) |
| n | u16 | número de eventos |
| eventos | … | `n` eventos seguidos |

## Eventos

| Byte | Contenido |
|---|---|
| 0 | id del vehículo (plaza) |
| 1 | longitud, bits 0–7 |
| 2 | bit 0: bit 8 de la longitud · bits 1–7: tipo de evento |
| … | datos |

**Tamaño total del evento = longitud (9 bits) + 5.** Con esta regla se recorren el 100 % de los fotogramas de todos los archivos probados, hasta los 2,6 GB de una carrera de 4 h (784.652 fotogramas, 33 millones de posiciones, en ~30 s).

### Estado del coche: tipos `0x10`–`0x1c` (pares), 70 bytes

- **x, y, z en float32 a partir del byte 46**: coordenadas del mundo en metros, con *y* hacia arriba.
- El tipo varía entre `0x10` y `0x1c` según el registro. No cambia la posición del dato, pero probablemente indica qué otros campos van incluidos.
- Pendiente: orientación, velocidades y entradas de los pilotos, que estarán en el resto de los 70 bytes y en otros tipos de evento.

### Otros tipos vistos

`0xb2` (39 B), `0x66` (8 B), `0xb0` (45 B), `0x1e` (29/42 B), `0x48` (18 B), `0xe0`, `0x90`… Sin descifrar todavía: probablemente son sonido, efectos, banderas, etc.

## Bloque final

- **JSON de la sesión:** `{"eventType", "eventTitle", "sceneDesc", "session": "PRACTICE|QUALIFY|RACE", "splitNo", …}`.
- **Archivos del circuito:** `.scn`, `.aiw` y la ruta `Installed\Locations\<circuito>\<versión>\`.
- **Participantes**, una entrada por cada ocupación de plaza:
  - `[3 bytes][u8 id de vehículo]`;
  - 5 cadenas `u8 longitud + texto`: piloto, archivo del coche (`397_26_296GT3`), decoración (hash), equipo y dorsal;
  - datos varios;
  - `[f32 inicio][f32 fin]` del periodo en que ese piloto ocupa la plaza (`-1e32` = hasta el final). **Estos dos tiempos van al final de cada entrada**, justo antes de la cabecera de la siguiente.
  - En resistencia aparecen todos los relevos de cada equipo; en sesiones online, los pilotos que entran y salen.

## Nombres de archivo

LMU codifica los bytes UTF-8 no ASCII como `+~XX`: `Aut+~c3+~b3dromo` = `Autódromo`.
