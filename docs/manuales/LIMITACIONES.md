# Limitaciones conocidas de SABRE.AI

Para el revisor: esta lista separa lo que es **un límite conocido y documentado** de lo que sería **un error**. Si algo de lo que ve coincide con un punto de esta página, no hace falta reportarlo como defecto. Cada punto dice de dónde sale la cifra. Ninguna cifra de esta página fue estimada: se copió de los documentos citados.

## 1. Exactitud del modelo (RNF-03 no se cumple)

| Dato | Valor | Fuente |
|---|---|---|
| Umbral de aceptación (D-01, RNF-03) | F1 macro ≥ 0,65 en 6 clases, como media de N = 10 corridas | `docs_claude/contexto_sabre.md`, tabla de requisitos |
| Media de la serie de 10 corridas (M01, F1 macro del sistema, es decir, tras el filtro Favero) | **0,4856 ± 0,0322** | `contexto_sabre.md`, sección 8 |
| Exactitud (accuracy) de la serie | 0,5096 ± 0,0327 | ídem |
| Corrida individual desplegada (`20260928_141021`) | F1 macro del sistema 0,5249 | `dataset/lstm_6class/results/20260928_141021_metrics.json`; el sistema lo muestra como `f1_macro_test` en `GET /modelo/activo` |
| Clasificador al azar entre 6 clases | 0,167 | referencia de `contexto_sabre.md` |

Qué significa para usted: **espere sugerencias equivocadas** (la cifra de la serie es la reportable para RNF-03; el 0,5249 es una sola corrida elegida por su exactitud de validación). El sistema solo sugiere y el árbitro decide (RNF-01). Que una sugerencia sea errónea no es un fallo del software.

La extracción de features de Fog reproduce la de entrenamiento con una diferencia residual aceptada como limitación: con el brazo armado anotado, 97 de 104 predicciones coinciden con las del CSV de entrenamiento y el F1 macro pasa de 0,5249 a 0,5380 (`docs/evidencia/diagnostico_discrepancia.md`). La causa de la diferencia no está confirmada.

## 2. El análisis corre en CPU y toma segundos

- Fog ejecuta YOLOv8x-pose y el seguimiento en CPU (`FOG_DEVICE=cpu`). El objetivo del sistema es una sugerencia en ≤ 60 s (D-08, RNF-04).
- **Medido en ESTRES01** (MacBook Air M4, 10 núcleos, 16 GB, sin GPU): con una pista, p50 = 14,6 s y p95 = 14,8 s por clip (n = 3, clips recortados a 76 fotogramas); la pose son ≈ 13,5 s de esos. Cloud tarda ≈ 10 ms. Fuente: `docs/evidencia/estres/ESTRES01_2026-11-19.md`.
- **Medido en la guía de instalación anterior** (Docker en Colima con 2 o 4 CPU): de 23 a 47 s por clip. Un equipo más lento o con menos núcleos tardará más. Las cifras de su equipo, medidas en la instalación en limpio de DOC01, están en `GUIA_EJECUCION.md`, sección A.7.
- La primera sugerencia tras arrancar Fog tarda más, porque Fog carga YOLO al arrancar y Cloud precalienta el modelo (`modelo precalentado en N ms`). Espere unos 20 s tras `uvicorn` antes del primer clip.
- Un clip con más fotogramas tarda más: el clip de 60 fps de ESTRES01 (151 fotogramas) necesitó ≈ 28 s solo en la pose.
- Si el análisis pasa de 60 s, la pantalla muestra "Clasificación no disponible" con el motivo `timeout`. Es el comportamiento previsto (RNF-09), no un cuelgue.

## 3. Un solo clip a la vez (lock de YOLO) y sin multipista

- El modelo de pose se usa detrás de un candado (`threading.Lock`) y Fog atiende con 2 hilos (`ThreadPoolExecutor(max_workers=2)`). Con varios clips simultáneos se hacen cola.
- ESTRES01 midió **1 a 4 pistas en paralelo**: p95 de 14,8 s (1 pista), 39,4 s (2), 51,2 s (3) y 59,7 s (4) en ráfaga, con n = 3 a 12. Con 4 pistas, **RNF-04 no se cumple de forma fiable** (1 de 12 clips pasó de 60 s en la ráfaga y 6 de 110, el 5,5 %, en la prueba sostenida).
- No hay soporte multipista: RF-29, F-018 y F-019 son WON'T. Use una sola sesión y un clip a la vez.

## 4. La señal Favero no existe en `main`; su resolución es de ≈ 42 ms

- En `main` **no hay aparato Favero, ni captura automática, ni Edge**: salieron del alcance por la solicitud de cambio del 20/11/2026 (D-12). Las luces se marcan a mano sobre el clip y el instante marcado centra la ventana del clip (D-19: 2,0 s antes y 0,5 s después).
- El código del Edge y del lector Favero está en la rama `future/edge-favero`, no en `main`, y no se puede verificar con esta instalación.
- Cuando se use el aparato real, su señal serie tiene una incertidumbre de **41,67 ms** por diseño del protocolo (una trama de 10 bytes a 2400 baudios), que ninguna calibración quita. El análisis y la propuesta sobre RF-06 (≤ 16 ms) están en `docs/hardware/limite_resolucion_favero.md` de esa rama, marcado allí como "sin medir" (falta el aparato real).

## 5. La línea del arma no se dibuja (D-18)

Los trazos de pose muestran el esqueleto, la extensión del brazo y la trayectoria de las extremidades de ambos tiradores. **No se dibuja la línea del arma**: YOLOv8-pose no detecta la hoja y el sistema no dibuja trazos inventados (CU-08). La parte de RF-18 sobre la línea del arma queda fuera. Los trazos se muestran sobre fondo negro, sin video (D-14).

## 6. El razonamiento es determinista, no un LLM (D-15)

El razonamiento son plantillas fijas armadas con la atención del modelo y eventos medidos sobre la pose. Puede aparecer como "Respaldada por la pose", "No concluyente", "Evidencia discordante" o "Evidencia insuficiente". Las revisiones anteriores a F-035 muestran "Esta revisión es anterior al registro de razonamiento" (D-17): no se recalculan.

## 7. Ningún clip se conserva después de la sesión (D-22)

Los clips viven solo mientras dura la sesión. Al cerrar la sesión se borran los archivos (después de un respaldo verificado, que **no incluye clips**). La base conserva el hash del clip (`clip.sha256`) y los metadatos, no el clip. Por eso, tras cerrar una sesión, la pantalla ya no puede reproducir el clip de una revisión pasada: es lo previsto.

## 8. Pérdida de la base de la Validación 1 (DEF-31)

La base de la Validación 1 (evento del 04/10/2026) vivía en un volumen de Docker sin respaldo y se perdió al reemplazar el motor de Docker. **Sobrevivieron** el registro JSONL de L01 (`datos/evidencia/<evento_id>.jsonl`) y los `.npz` y clips de `datos/storage/`; **se perdieron** las filas que los unen (revisiones, clasificaciones, veredictos y la cadena de auditoría), de las que depende el registro inalterable de RF-22 y F-034. El JSONL es la evidencia de esa validación. Corrección (FIX03): `scripts/respaldar_sesion.sh` respalda y verifica cada sesión. El detalle del defecto está en la tabla de defectos de `docs_claude/contexto_sabre.md`.

Consecuencia para el revisor: la base que usted crea al instalar está vacía. No contiene los resultados de la Validación 1 y no hay que esperar que los muestre.

## 9. Funciones fuera de alcance (WON'T)

| Función | Estado |
|---|---|
| RF-27 Vista de la sugerencia y el veredicto para atletas o pantalla pública (D-02, D-03) | WON'T |
| RF-28 / F-009 Reportes post-competencia por atleta o sesión (D-10) | WON'T (el CSV de la sesión se obtiene con `scripts/exportar_evidencia.py`) |
| RF-29 / F-018 / F-019 Procesamiento de varias pistas en paralelo | WON'T |
| RF-30 Actualización dinámica del reglamento (D-05: FIE 2026 fijo) | WON'T |
| F-036 / RNF-07 Pruebas de reprocesamiento y consistencia | Descartadas |
| RF-03 a RF-06 Captura con dos cámaras, buffer circular, señal Favero y sincronización | Fuera de `main` (solicitud del 20/11/2026) |
| Asistente de video (D-09) y registro de qué tirador pidió el VAR (D-04) | Fuera de alcance |
| Entrenar un modelo nuevo desde las revisiones (CU-14, T-018) | Trabajo futuro |

## 10. Otros límites del uso

- Solo sable y 6 clases (RNF-17). Línea, florete y espada están fuera.
- Video H.264, ≥ 720p y ≥ 30 fps (RNF-13). Un clip de menor resolución puede dar "No se pudo detectar a ambos tiradores en el clip."
- Tamaño máximo del clip: 200 MB por defecto (`CLIP_MAX_MB`). Más de eso responde 413.
- Con la señal marcada a mano, una luz mal marcada cambia la sugerencia (el filtro Favero descarta las clases del tirador sin luz). El instante se guarda para la auditoría.
- Solo hay versión web. La reproducción de video y la descarga del resumen funcionan en el navegador de escritorio (se probó con Google Chrome).
- Fog guarda las sesiones de procesamiento en memoria (`InMemoryMatchRepository`): se pierden al reiniciar. Lo que se audita está en PostgreSQL.
