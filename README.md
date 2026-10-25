# LMU Coach

App de escritorio para mejorar tus hotlaps en Le Mans Ultimate: analiza todas tus sesiones y tiene un **modo coach** con overlay en directo.

![Sesión abierta: imagen del coche, vueltas, gráficas frente a la mejor vuelta, trazada y dónde pierdes tiempo en cada frenada](docs/img/app.png)

## Instalar

Descarga `LMU-Coach-Setup-x.y.z.exe` de la pestaña **Releases** y ejecútalo. No pide permisos de administrador ni necesita Python. Crea accesos directos a **LMU Coach** y a **LMU Coach - solo modo coach**.
Windows SmartScreen puede avisar de que es una "app desconocida" porque no está firmada: pulsa *Más información → Ejecutar de todas formas*.

Los datos (vueltas grabadas, referencias fijadas, configuración) se guardan en `%LOCALAPPDATA%\LMU Coach`.

Para regenerar el instalador tras cambiar el código, ejecuta `build.bat` (requiere Python 3.12, PyInstaller e Inno Setup 6).

## Configurar Le Mans Ultimate

Solo hace falta hacerlo una vez, dentro del juego:

1. **Activa la grabación de telemetría.** En los ajustes de LMU, activa **«Automatically Record Telemetry»** (o usa el atajo de teclado **«Telemetry Recording»** cuando estés en pista). Sin esto, LMU no guarda las sesiones en `UserData\Telemetry` y la app no tiene nada que analizar. El modo coach sí funciona sin ello.
2. **Pon el juego en «Ventana sin bordes» (Borderless).** En pantalla completa, el coach no se puede ver encima del juego.
3. **Sal a pista.** Los datos en directo del coach solo llegan con el coche en pista, no en el monitor ni en el garaje. Las sesiones aparecen en la app al terminar de rodar: pulsa ⟳ (buscar sesiones nuevas) en la barra de arriba.

No hay que instalar plugins ni tocar archivos del juego: la app lee la telemetría que LMU ya graba (y guarda una copia propia) y su memoria compartida (`LMU_Data`).

Si algo no funciona, abre **⋯ → 🩺 Diagnóstico** en la app. Comprueba que encuentra la carpeta de LMU (si no, deja elegirla a mano), que hay sesiones grabadas, que la grabación de telemetría está activada y que llegan datos en directo.

Si usas varios monitores, el coach se coloca solo en la pantalla del juego. Puedes arrastrarlo a donde quieras y recuerda la posición.

## Desarrollo

Para ejecutarlo desde el código, en Windows con Python 3.12:

```
pip install -r requirements.txt
python -m lmu_coach.gui        # app de escritorio
python -m lmu_coach            # solo el overlay del coach
python -m lmu_coach --demo     # overlay con un coche simulado
```

Pruebas (no necesitan nada más que Python; las de sesiones reales y la ventana solo se ejecutan si el PC tiene telemetría de LMU, y `build.bat` las pasa antes de generar el instalador):

```
python -m unittest discover -s tests -t .
```

Si algo falla en la app o en el coach, los errores quedan en `%LOCALAPPDATA%\LMU Coach\logs` (`app.log` y `coach.log`); en la app, **⋯ → 🩺 Diagnóstico → 📄 Abrir registro**.

Atajos (usan Python 3.12 instalado para el usuario):

| | |
|---|---|
| `iniciar.bat` | app de escritorio |
| `iniciar.bat coach` | solo el overlay del coach |
| `iniciar.bat demo` | overlay con un coche simulado (sin el juego) |

## La app

- **Inicio**: sin ninguna sesión abierta (o con 🏠), la app enseña tu última sesión, tu objetivo más cercano, lo que has corrido en los últimos 7 días y un botón grande para iniciar el coach. Lo que se usa de vez en cuando (importar sesión, copia de seguridad, diagnóstico) está en el menú **⋯** de arriba a la derecha.
- **Primera vez**: un asistente de bienvenida comprueba que LMU graba la telemetría, deja elegir la voz del coach y dónde se guarda la copia de tus sesiones. Se puede repetir desde ⚙ Ajustes.
- **Sesiones**: lee las que LMU graba en `UserData/Telemetry/*.duckdb`. Puedes filtrar por circuito, coche y tipo de sesión. En morado aparece tu récord para cada coche y circuito. Para ver las sesiones nuevas, pulsa ⟳.
- **Copia propia de tus sesiones** (⋯ → 💾 Copia de seguridad): al buscar sesiones nuevas, la app copia las que LMU ha terminado de grabar a `Documentos\LMU Coach\Sesiones` (se puede cambiar) y lee de ahí. Aunque LMU borre sus archivos, reinstales el juego o cambies de PC (llevándote esa carpeta), no pierdes nada. La carpeta de LMU nunca se modifica.
- **Imagen del coche**: cada sesión muestra la imagen oficial de su decoración (en la lista y en la cabecera), sacada de la propia interfaz de LMU (`Bin/UI.zip`). Si LMU está abierto al usar la app, aprende la lista completa de decoraciones y la guarda, para que también salgan las más nuevas.
- **Vueltas**: tiempo, sectores (los mejores en morado), diferencia con la mejor y estado (válida, invalidada, boxes).
- **Comparar con**: la mejor vuelta de la sesión o tu mejor vuelta histórica con ese coche y circuito.
- **Gráficas por distancia**: delta, velocidad, gas/freno, volante y marcha. Tu vuelta va en azul y la referencia en discontinua. Las frenadas están marcadas como F1, F2…
- **Trazada**: el mapa del circuito se colorea en verde donde ganas tiempo y en rojo donde lo pierdes.
- **Dónde pierdes tiempo**: tabla frenada a frenada con el tiempo ganado o perdido, el punto de frenada, la velocidad mínima, cuándo vuelves a gas a fondo y qué cambiar. Haz clic en una fila para hacer zoom en esa curva.
- **Nombres de las curvas**: las frenadas llevan el nombre real de la curva en los circuitos conocidos (Rettifilo, Copse, S do Senna…). Haz doble clic en una para ponerle tu propio nombre; el coach y la voz también los usan («pierdes dos décimas en Ascari»).
- **Compartir sesiones**:
  - **⬆ Exportar sesión** guarda la sesión abierta en un archivo `.lmusession`, un zip que ocupa más o menos la mitad que el original.
  - **⋯ → ⬇ Importar sesión** carga un archivo que te hayan pasado. También puedes arrastrarlo a la ventana o hacerle doble clic. Se aceptan `.lmusession`, `.zip` y `.duckdb`.
  - Las sesiones importadas salen en naranja con el nombre del piloto, y se pueden filtrar con «Importadas».
  - No cuentan como tu récord. Sí aparecen en «Comparar con», para enfrentar tu vuelta a la de tu amigo.
  - Con **🗑 Quitar importada** se borra la copia de la app. LMU no se toca.
- **Pestañas de análisis** en cada sesión, agrupadas en **🏁 Vuelta** (gráficas, repetición y consistencia), **📊 Carrera** (resumen de carrera, ritmo y relevos, combustible y estrategia) y **🔧 Coche** (neumáticos y frenos, reglaje y asistente de reglaje):
  - **🏁 Resumen de carrera**: posición en tu clase vuelta a vuelta, diferencias con el de delante y el de detrás, paradas, tu mejor vuelta y tu ritmo frente a los de tu clase. Lo apunta el modo coach en directo, porque la telemetría de LMU solo trae tu coche: si el coach estaba abierto durante la carrera, aquí está.
  - **⛽ Combustible y estrategia**: consumo de combustible y energía virtual por vuelta, la media de tus sesiones con ese coche y circuito, y una calculadora de paradas (vueltas por relevo, número de paradas y cuánto cargar en cada relevo).
  - **🔧 Reglaje**: diferencias entre el reglaje de la sesión y el de tu sesión más rápida, o cualquier otra, con los nombres en español.
  - **🎯 Consistencia**: cuánto varía, entre vueltas, tu punto de frenada, la velocidad en el vértice y el tiempo en cada frenada.
  - **🛞 Neumáticos y frenos**: por vuelta y rueda, presión, temperaturas interior/centro/exterior, temperatura máxima del freno y desgaste, con pistas orientativas (presión, caída).
  - **📉 Ritmo y relevos**: tiempos vuelta a vuelta por relevo con su tendencia, cuánto pierdes por vuelta por los neumáticos (descontando el combustible), las vueltas con error y el desgaste de cada eje.
  - **🧠 Asistente de reglaje**: detecta subviraje o sobreviraje por curva y fase (entrada, vértice, salida), cuánto trabajan el ABS y el TC, y las temperaturas de ruedas y frenos. Con eso propone cambios de reglaje ordenados por prioridad. También mira qué valores te dieron mejores tiempos en tus otras sesiones. No usa IA: son reglas de ingeniería aplicadas a tu telemetría. ✓ marca lo que se puede cambiar en series de reglaje fijo.

| Ritmo y relevos | Asistente de reglaje | Combustible y estrategia |
|---|---|---|
| ![Ritmo y relevos](docs/img/ritmo.png) | ![Asistente de reglaje](docs/img/asistente.png) | ![Combustible y estrategia](docs/img/combustible.png) |

- **📈 Mi progreso**: todos los circuitos (por trazado) y coches que has corrido, con cuánto has mejorado. Para cada uno, tu mejor vuelta y tu ritmo medio por día, la **vuelta ideal** con tus mejores sectores de todas las sesiones y un **objetivo de tiempo** («bajar de 1:46,0»). En pista, el coach te dice a cuánto estás de tu objetivo al acabar cada vuelta.
- **🧾 Debrief**: las 3 cosas que más tiempo te darían en esa sesión (curvas donde pierdes, errores, degradación de neumáticos, reglaje, vuelta ideal), ordenadas por lo que ganarías por vuelta y cada una con su botón: practicar la curva con el coach, abrir el setup, ver la consistencia o fijar el objetivo. Cuando aparece una sesión nueva, la app ofrece su debrief abajo a la derecha.
- **🛠 Setup ▾ → Editar setup**: parte del reglaje que tienes cargado en LMU (`TempModFile.svm`) o de cualquier `.svm`, cambia cada ajuste dentro de sus límites reales (sacados de tu última sesión con ese coche), mira qué hace cada cambio y guárdalo en la carpeta del circuito para cargarlo en el garaje. «Aplicar sugerencias del asistente» da un paso en cada cambio que propone el asistente de reglaje. No simula el tiempo por vuelta: para eso está el A/B.
- **🛠 Setup ▾ → Comparar setups (A/B)**: la sesión abierta frente a otra con el mismo coche y circuito. Compara tu ritmo (mediana de las vueltas limpias), tu regularidad y cada curva, y enseña qué cambiaba del reglaje.
- **📷 Imagen**: guarda una imagen de la sesión tal como la ves y la copia al portapapeles, para pegarla en Discord o WhatsApp.
- **🎯 Plan de entrenamiento**: las 3 curvas donde más tiempo pierdes en una vuelta normal frente a tu mejor vuelta, con qué cambiar en cada una (punto de frenada, velocidad de paso, cuándo acelerar). Con «Activar en el coach», el coach te recuerda el objetivo al llegar a esas curvas, en pantalla y por voz.
- **📌 Usar como referencia del coach**: fija la vuelta seleccionada para que el coach la persiga. Con "Quitar", el coach vuelve a usar tu mejor vuelta.

![Plan de entrenamiento](docs/img/plan.png)

## Modo coach (overlay)

![El coach en carrera: posición y diferencias, sectores, aviso de frenada con el objetivo del plan, coche al lado (barra izquierda) y temperaturas; a la derecha, el tiempo al cruzar meta](docs/img/coach.png)

Pulsa **▶ Iniciar modo coach** y entra en pista con LMU en **ventana sin bordes**.

- Delta en directo contra la referencia, con la tendencia (ganando o perdiendo).
- Cuenta atrás hasta cada punto de frenada. Si llegas más rápido que en la referencia, te avisa con "→ frena antes". Si pasas el punto sin frenar, aparece "¡FRENA!".
- Barras de gas y freno, junto a lo que hacías en la referencia en ese mismo punto.
- Feedback al salir de cada frenada.
- **Sectores estilo F1**: el color indica cómo te ha ido en cada sector.
  - Morado: mejor que la referencia.
  - Verde: tu mejor sector de la sesión.
  - Amarillo: más lento.
  - Gris: vuelta no válida.

  El sector en curso muestra el delta en directo, y en la cabecera aparece la **vuelta ideal** (la suma de tus mejores sectores).
- **Combustible y energía**: vueltas restantes de cada uno en la cabecera (⛽ / ⚡), en ámbar o rojo cuando quedan pocas.
- **Avisos por voz** (voces neuronales de Microsoft Edge, casi humanas, o las de Windows; las neurales guardan cada frase la primera vez que la generan, con internet, y las urgentes se preparan al elegir la voz; sin internet usa la de Windows): «frena», cuánto ganas o pierdes en cada frenada y **por qué** («pierdes tres décimas en Parabolica, frenas quince metros antes»), el tiempo de vuelta, si la vuelta se invalida, cuando queda poco combustible y, si lo activas, el delta al pasar por cada sector. Con clic derecho en el overlay se activan o desactivan, y se elige la voz (por ejemplo Pablo, Laura o Helena, según las que tenga Windows) y la velocidad. Al cambiarlas oyes una frase de prueba.
- **Temperaturas en directo**: una franja bajo el coach con la temperatura de cada goma (verde si está en la ventana óptima del compuesto, ámbar si se aleja, rojo si se pasa y azul si está fría) y de cada freno, comparada con lo que alcanza ese coche en tus sesiones. Si los frenos de un eje se pasan mucho, te avisa por voz. Se oculta con clic derecho → «Temperaturas de gomas y frenos».
- **Modo práctica**: en la app, clic derecho en una frenada de «Dónde pierdes tiempo» → «Practicar en el coach». En pista, el coach solo te habla de esa curva: cada pasada, lo que ganas o pierdes, por qué y cuándo es tu mejor pasada.
- **Ingeniero de carrera** (solo en carreras): arriba a la derecha, tu posición en tu clase y las diferencias con el de delante (▲) y el de detrás (▼). Por voz, al empezar cada vuelta, la posición, las diferencias y si recortas o pierdes tiempo con el de delante. También avisa si tienes un coche de tu clase a menos de 1 s, si ganas o pierdes posiciones, si el de delante o el de detrás entra en boxes, si te alcanza un coche de una clase más rápida, y cuando quedan 5 minutos o 1 vuelta. Se desactiva con clic derecho → «Ingeniero de carrera».
  - **Estrategia en directo**: con tu consumo real de combustible y energía y lo que queda de carrera, te dice si llegas al final o cuándo parar, cuánto repostar y en qué posición volverías («Para en dos vueltas, reposta treinta litros. Volverías cuarto»). En el coach aparece «BOX en 2 v».
  - **Banderas**: amarilla en todo el circuito, boxes abiertos o cerrados, relanzamiento, «verde, verde, verde», amarillas por sector y bandera azul.
  - **Resumen al acabar**: «Carrera terminada. Posición tres de doce. Ganas cuatro posiciones». Se guarda para verlo luego en la pestaña Resumen de carrera de esa sesión.
- **Spotter**: avisa por voz cuando tienes un coche al lado («Izquierda», «Derecha», «En medio», «Libre») y marca ese lado del coach con una barra ámbar. Aprende solo qué lado es cuál en las primeras curvas. Se desactiva con clic derecho → «Spotter».
- **📱 Panel en el móvil o la tablet**: actívalo en ⚙ Ajustes › General y abre la dirección (o escanea el QR) en el navegador del móvil, en la misma wifi. Con el coach abierto enseña delta y sectores, última vuelta, combustible y energía, estrategia de parada, diferencias, temperaturas, banderas y el spotter (bordes en rojo). Solo lectura y sin instalar nada.
- **📻 Radio con el ingeniero**: asigna un botón del volante o una tecla en ⚙ Ajustes › Radio, mantenlo pulsado, pregunta («combustible», «cuándo paro», «el de delante»…) y suéltalo: te contesta con los datos del momento. Las frases y lo que responde cada una se editan; las respuestas son plantillas con datos entre llaves (`{combustible}, para {combustible_vueltas}`), con más de 35 datos para elegir. Entiende con **Whisper** (sin internet; el modelo se descarga una vez desde Ajustes, ~145 MB, y responde en ~0,5 s) y busca tu frase más parecida, así que no hace falta decirla exacta. El reconocimiento de voz de Windows queda como alternativa. En Ajustes › Radio hay un medidor del micrófono y un botón para probar qué entiende.
- **Daños**: avisa de golpes que dañan la carrocería, piezas sueltas, pinchazos, ruedas perdidas y motor sobrecalentado, y muestra «⚠ DAÑOS» en el coach.
- **Mensajes ordenados**: los avisos esperan su turno con una pausa entre ellos en vez de pisarse; solo «frena», el spotter y los coches que te alcanzan interrumpen. Los cambios de posición se dicen juntos cuando se estabilizan («Ganas dos posiciones. Posición cinco»).
- **Tiempo de vuelta en grande** durante 6 s al cruzar meta, con la diferencia frente a la referencia. Sale en morado si es tu nueva mejor vuelta y en gris si no es válida.
- Graba automáticamente cada vuelta válida en `data/laps/`.

**Qué referencia usa el coach**:
1. La vuelta que hayas fijado desde la app.
2. Si no hay ninguna fijada, la más rápida entre tus vueltas grabadas por el coach y tu histórico de LMU.

Para mover el overlay, arrástralo. Para cerrarlo, haz clic derecho → Salir, o pulsa Esc.

## ⚙ Ajustes

Todo lo que dice el coach se elige en **⚙ Ajustes**, mensaje a mensaje, con un botón ▶ para oír cada uno. Los cambios se aplican al momento, también con el coach abierto.

- **General**: voz y velocidad, opacidad del overlay, temperaturas y pitido en el punto de frenada.
- **Spotter**: qué avisos dice («Izquierda», «Derecha», «En medio», «Libre», «Libre a la izquierda», el recordatorio «Sigue a la izquierda», «Spotter listo»), si marca el lado en el overlay y cuándo un coche cuenta como «al lado»: distancia lateral máxima, solape y pausa mínima entre avisos.
- **Ingeniero**: cada aviso (posición, coche encima, boxes de rivales, clase más rápida, resumen de vuelta, banderas, estrategia, final de carrera), a partir de qué diferencia avisa del coche de detrás, la antelación del aviso de clase más rápida, el resumen cada cuántas vueltas y el tiempo que pierdes en una parada.
- **Coach**: «frena», objetivos del plan, tiempo por curva y su consejo, delta por sector, tiempo de vuelta, vuelta invalidada y objetivo; y el modo práctica.
- **Coche**: combustible, frenos calientes y cada tipo de daño.

Se guarda en `config.json` (en `%LOCALAPPDATA%\LMU Coach` con la app instalada).

## Técnico

- **Datos en directo**: memoria compartida nativa de LMU (`LMU_Data`). Las estructuras de `lmu_coach/shm_structs.py` están escritas a mano a partir de la documentación que trae el juego en `Support/SharedMemoryInterface`; las cabeceras originales no se redistribuyen. Se lee por sondeo y es compatible con SimHub o CrewChief.
- Proyecto independiente, sin relación con Studio 397 ni Motorsport Games. *Le Mans Ultimate* es una marca de sus respectivos propietarios.
- **Sesiones**: DuckDB. Los resúmenes se guardan en caché en `data/sessions_index.json`.
- **Librerías**: PySide6, pyqtgraph, numpy y duckdb.
