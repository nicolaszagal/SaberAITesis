# Diagnóstico de la discrepancia entre los .npy de entrenamiento y Fog

Test set de `dataset/lstm_6class` (104 clips), checkpoint `20260928_141021/best_model.pt`.
Script: `backend/scripts/diagnostico_discrepancia.py`. Tablas completas: `diagnostico_discrepancia_tablas.md`.
No se modificó código de producción ni `dataset/`.

## Resumen

1. **Parte de la discrepancia reportada en `sensibilidad_features.md` era un error de esa prueba.** Pasó brazo armado derecha/derecha a Fog, pero los `.npy` se extrajeron con el brazo anotado en Label Studio (pk=5), y 41 de 104 clips tienen al menos un brazo `left`. Con el brazo anotado, Fog coincide con el CSV en 97/104 clips (antes 92/104); los clips que cambian de clase bajan de 12 a 7.
2. **El código de Fog no es la fuente del resto.** Con el mismo clip `test_trimmed` y el mismo brazo, `process_clip` de `05_extract_features.py` (instancia YOLO nueva por clip) y Fog dan features idénticas: max|Δ| = 0 en los 17 clips probados.
3. **Los `.npy` no coinciden con lo que hoy produce ese mismo código sobre el mismo clip**, y la causa de esa diferencia residual **no está confirmada**.
4. No son la causa: el rango de frames, el intercambio A/B ni la posición del frame (detalle abajo).

## 1. Distribución de la diferencia (features normalizadas)

Fog con brazo anotado contra el `.npy`, 104 clips con igual T. Cada valor es media / mediana / p95 / máx **entre clips**.

| Métrica por clip | media / mediana / p95 / máx |
|---|---|
| media de \|Δ\| | 0.097 / 0.052 / 0.298 / 1.003 |
| p95 de \|Δ\| | 0.454 / 0.158 / 2.124 / 6.072 |
| máx de \|Δ\| | 4.873 / 4.719 / 8.487 / 12.51 |

- El máximo (≈5) sobrestima el problema: la media típica por clip es 0.05, unas cien veces menor. Hay pocos valores muy alejados y muchos con diferencia pequeña.
- La diferencia es densa: cerca del 87 % de los valores difieren en más de 1e-4 (tolerancia de la prueba de paridad), aun cuando el máximo sea pequeño.
- **Por grupo de columnas.** Posición, velocidad y paso tienen medias por clip entre 0.03 y 0.11 (mediana), tanto en A como en B. El grupo arma de A era el peor con derecha/derecha (media 0.33, mediana 0.15) y baja a 0.14 (mediana 0.04) con el brazo anotado: es el efecto del punto 1. Bio de A baja de 0.21 a 0.12 por la misma razón. Los grupos de B no cambian.
- **Por posición del frame.** Los primeros 5 frames difieren menos que el resto (media de \|Δ\| 0.047 contra 0.109; p95 0.17 contra 0.51). No es un transitorio de arranque del tracker.
- **Desplazamiento temporal.** Para los 104 clips, la mejor alineación es k=0 (no hay desfase de frames).
- En la reejecución de entrenamiento sobre 17 clips, la media de \|Δ\| por clip es 0.171 (mediana 0.064). Dos de esos clips, `RiposteA_0041` (0.98) y `ContrattackB_0069` (0.86), tienen media cercana a 1 y correlación baja entre el bloque A de Fog y el del `.npy` (ContrattackB_0069: −0.02). Son diferencias estructurales y no ruido.

## 2. Rango de frames

| Comparación | Clips con T(.npy) igual |
|---|---|
| frames de `test_trimmed` (contador y decodificados) | 104/104 |
| rango original de Label Studio pk=2 convertido a real | 104/104 |
| pk=5 `frame_fin_trimmed` + 1 | 104/104 |
| camino "original" con datos de pk=5 (fi=0, ff=round(frame_fin_trimmed·fps/24)) | 0/104 |

- **La premisa "los .npy salen del clip original desde el frame 0 y se recortan a [frame_inicio, frame_fin]" no se sostiene para test.** Para los proyectos 4 y 5, `load_annotations` fija fi=0 y ff=`frame_fin_trimmed`, y `find_video` prefiere `{split}_trimmed/`. Ese camino sobre el original daría un T distinto en los 104 clips.
- Alineación píxel a píxel de `test_trimmed` contra el original en [fi_real, ff_real]: k=0 en los 92 clips medibles (diferencia media de píxeles 0.29 de 255). En 12 clips no se pudo medir porque el trimmed tiene otra resolución (recorte espacial) y no hay coordenadas que coincidan.
- Los `test_trimmed` tienen recorte espacial (`labels/crop_coords.csv`) además del temporal. El camino original de `05_extract_features.py` no lo aplica: sobre 17 clips da media de \|Δ\| 1.07 contra el `.npy`, peor que el camino trimmed (mediana 0.064). **Sin confirmar:** original con recorte espacial aplicado antes del tracking; no se probó.
- Conclusión: el rango de frames coincide y no explica la diferencia. Lo más consistente con los datos es que los `.npy` de test salieron de `test_trimmed`.

## 3. Intercambio A/B

- 0/104 clips tienen A y B intercambiados (distancia con bloques cruzados menor que con bloques directos). En los 17 clips revisados, 0 frames tienen el cruce más cercano.
- En los 12 clips que cambian con derecha/derecha, la clase predicha cambia de lado (A↔B) en 4: AttackA_0198, AttackB_0167, AttackB_0183 y RiposteA_0041. En los otros 8 cambia solo el tipo de acción dentro del mismo lado.
- Por tanto el intercambio de identidad no explica los cambios de clase.

## 4. Tracker y versión de ultralytics

**No queda ningún registro de la versión usada al extraer.**

- `requirements.txt` y `requirements-fog.txt` dejan `ultralytics` sin pin. `constraints.txt` (DEF-19, 2026-09-28) fija 8.4.75 a partir del `.venv` actual, que es posterior a la extracción (2026-06-18).
- `dataset/.venv` (Python 3.13) no tiene ultralytics ni torch. La única instalación de ultralytics en esta máquina es `backend/.venv` (8.4.75).
- `dataset/__pycache__/05_extract_features.cpython-310.pyc` (2026-06-15) indica que la extracción corrió con Python 3.10, que ya no existe aquí.
- Los pesos `yolov8x-pose.pt` traen `version: 8.0.77`. Es la versión con que se entrenaron los pesos, no la del runtime.
- `DATASET_STATUS.md` y `SCRIPTS.md` dicen "ByteTrack", pero `05_extract_features.py` llama a `model.track(frame, persist=True)` sin `tracker=`, así que usó el default de la versión instalada entonces. En 8.4.75 el default es BoT-SORT (`cfg/default.yaml`). La docstring de `yolo_pose_adapter.py` ya documenta esta duda.
- La extracción de test tardó de 20:11 a 21:53 del 2026-06-18 (alrededor de 1 min por clip), contra 4 a 10 s por clip hoy. No es concluyente, pero indica un entorno distinto.

## Causas confirmadas

1. La prueba `sensibilidad_features.py` usó brazo derecha/derecha en Fog; con el brazo anotado, los clips que difieren del CSV bajan de 12 a 7.
2. Fog equivale exactamente al camino de entrenamiento sobre el mismo clip (17 clips, max|Δ| = 0).
3. Rango de frames y A/B no son la causa.

## Sin confirmar

- Qué produce la diferencia residual entre el `.npy` guardado y la reejecución con el código actual (media típica 0.05, con casos estructurales). Candidatos, ninguno probado: otra versión de ultralytics o de su tracker (ByteTrack contra BoT-SORT), otro dispositivo (CPU contra MPS), otra versión de torch/numpy/OpenCV en la extracción original, o un estado distinto del tracker.
- La diferencia estructural de los clips con media cercana a 1 (`RiposteA_0041` y `ContrattackB_0069` en la reejecución; `ContrattackA_0019` con media 0.98 en la comparación con Fog): podría ser otra persona bloqueada como A o B, pero no se verificó.
- La reejecución de entrenamiento cubre 17 clips, no los 104.
- La localización de las diferencias por frame y columna y las pruebas con `tracker="bytetrack.yaml"` y `device="mps"` no se ejecutaron: el entorno de ejecución falló de forma intermitente al final de la sesión.

## Recomendación

Recomiendo **(a) aceptar como limitación documentada, como paso inmediato**, y no hacer (b) ni (c) todavía. Es una recomendación, no una decisión tomada.

- (b) no aplica: Fog ya replica el camino de entrenamiento. Con el mismo clip y el mismo brazo da resultados idénticos.
- (c) se justifica solo si se confirma que la diferencia viene del entorno de extracción original y se quiere reentrenar con features coherentes con Fog. Con la evidencia actual no hay causa confirmada. Costaría reextraer y reentrenar sin saber si el efecto en F1 es relevante: con el brazo anotado, Fog da F1 macro 0.5380 contra 0.5249 del CSV, es decir, no empeora.
- Antes de decidir (c), conviene una prueba corta (unos 17 clips): la reejecución con `tracker="bytetrack.yaml"` y con `device="mps"`. Si alguna reproduce el `.npy`, la causa queda aislada.

Además, hay que corregir `sensibilidad_features.py` para que use el brazo anotado. Sus cifras con derecha/derecha sobrestiman la discrepancia (92/104 contra 97/104).
