# Prueba de humo Q02 · flujo completo contra una base separada

Fecha: 2026-09-29 · Modelo: `lstm6class-20260928_141021` (`MODEL_RUN_DIR` = `checkpoints/20260928_141021`) · Validación 1 (tocado simulado, D-12).

## Entorno

Aislado de la base y el Redis de la validación:

| Componente | Configuración |
|---|---|
| PostgreSQL 16 | contenedor propio `sabre-humo-pg`, puerto 5434, base `sabre_humo` (migrada con `alembic upgrade head`) |
| Redis | `redis-server` propio en el puerto 6390, sin persistencia |
| `STORAGE_DIR`, `EVIDENCE_DIR` | directorios temporales propios |
| Fog, Cloud | procesos locales contra esa base y ese Redis (`uvicorn fog.main:app`, `python -m cloud.main`) |

Sesión: evento `piloto` "Prueba de humo Q02", árbitro y operador de prueba (`scripts/crear_sesion_validacion.py`), modelo activo registrado con `scripts/registrar_modelo.py`.

## Datos de entrada

Un clip por clase, el primero (orden alfabético) de `dataset/dataset trimmed/test_trimmed/<clase>/`. Luces de `dataset/labels/luz_annotations.csv` (`has_luz_X` = frame > 0). `t_tocado_ms` = round(primer frame de luz / fps · 1000) (criterio indicado por el autor; la API solo lo guarda, no recorta con él). Brazo armado: el anotado en Label Studio (proyecto 5).

| Clip | Frames (30 fps) | luz A / B | `t_tocado_ms` | Brazos A/B |
|---|---|---|---|---|
| AttackA_0007 | 15 | 8 / 9 | 267 | right / right |
| AttackB_0006 | 18 | 0 / 7 | 233 | left / right |
| ContrattackA_0002 | 27 | 13 / 0 | 433 | right / right |
| ContrattackB_0001 | 28 | 14 / 17 | 467 | right / right |
| RiposteA_0021 | 27 | 16 / 0 | 533 | right / right |
| RiposteB_0004 | 27 | 15 / 13 | 433 | right / right |

Nota: el CSV `trimmed_annotations.csv` trae frames de luz distintos en algunos clips (p. ej. AttackA_0001: 6 en `luz_annotations.csv`, 7 en `luz_A_trimmed`). La prueba usa `luz_annotations.csv`, como se pidió.

## Flujo verificado por clip

Configurar combate → subir clip (síncrono: pose, features, Redis, Cloud, sugerencia) → veredicto del árbitro → cierre de la revisión y registro auditable → línea en el log de evidencia.

Convención del veredicto de la prueba: `clase_final` = clase real del clip; `decision` = `mantener` si coincide con la sugerida, `cambiar` si no.

## Resultados por clip

Latencias medidas por el cliente (`ms_clip` = `POST /matches/{id}/clip` completo) y por el sistema (`latencia_ms` de `clasificacion`, la que usa L02; `inferencia` = `latencia_inferencia_ms` que publica Cloud).

| Clip | Sugerida | Confianza | Clase final | Decisión | `latencia_ms` (sistema) | `ms_clip` (cliente) | Inferencia BiLSTM | Veredicto |
|---|---|---|---|---|---|---|---|---|
| AttackA_0007 | AttackB | 0.534 | AttackA | cambiar | 3918 | 3930 | 950 ms (arranque en frío) | 7 ms |
| AttackB_0006 | AttackB | 0.973 | AttackB | mantener | 3345 | 3353 | 23 ms | 7 ms |
| ContrattackA_0002 | ContrattackA | 0.496 | ContrattackA | mantener | 5193 | 5201 | 22 ms | 7 ms |
| ContrattackB_0001 | RiposteB | 0.354 | ContrattackB | cambiar | 5333 | 5343 | 22 ms | 7 ms |
| RiposteA_0021 | AttackA | 0.444 | RiposteA | cambiar | 5006 | 5014 | 11 ms | 7 ms |
| RiposteB_0004 | RiposteB | 0.436 | RiposteB | mantener | 4990 | 4998 | 10 ms | 7 ms |

`POST /matches/config`: 4–13 ms por clip. Los 6 clips quedaron disponibles (ninguno "no disponible").

## Exportación L02 (`scripts/exportar_evidencia.py --evento <id>`)

Generó `resumen.json`, `revisiones.csv` (6 filas) y `resumen.md`; `GET /validaciones/{evento_id}/resumen` devuelve el mismo contenido.

| Métrica (V1, N = 6) | Valor | Umbral |
|---|---|---|
| Latencia de la sugerencia, mediana / p95 / máx | 4998 / 5333 / 5333 ms | p95 ≤ 60 000 ms: cumple (RNF-04) |
| % ≤ 60 s | 100 % | — |
| κ de Cohen sistema-árbitro | 0.40 (aceptable) | ≥ 0.61: no cumple |
| Concordancia | 50 % (3/6) | — |
| Conciliación base vs. JSONL | 6 vs. 6, sin faltantes ni sobrantes | — |
| `fn_verificar_auditoria` | íntegra, 0 alteradas | — |

V2 no tiene revisiones (`tocado.fuente = favero` no se usó). Estos valores describen una prueba de humo de 6 clips: **no son evidencia de RNF-03 ni de RNF-06** (RNF-03 se mide offline sobre el test set con N = 10; RNF-06 en las sesiones piloto).

## Comprobaciones de integridad

- Segundo `POST /revisiones/{id}/veredicto` sobre la misma revisión: **409**.
- `UPDATE sabre.veredicto ...` directo en la base: rechazado con "Los registros de auditoría no pueden modificarse" (RNF-05).
- `GET /auditoria/verificar`: `{"integra": true, "alteradas": []}`.
- Logs de Fog y Cloud: 0 líneas `ERROR`.

## Reproducibilidad

Segunda corrida con `scripts/prueba_humo.py` sobre otro evento (en caliente): las 6 sugerencias y confianzas son idénticas a las de la primera corrida; latencia `latencia_ms` mediana 7157 ms, p95 7605 ms; inferencia 34, 10, 19, 14, 13 y 14 ms. La latencia del clip varió entre corridas (mediana 4998 → 7157 ms) sin cambio de código; no se investigó la causa.

## Hallazgos

1. **F-027 (≤ 50 ms de inferencia)**: cumple en caliente (10–34 ms) pero la primera inferencia tras arrancar Cloud tomó 950 ms. Con un solo clip en frío el presupuesto se excede; Cloud no hace calentamiento previo.
2. **Latencia de inferencia sin persistir**: `latencia_inferencia_ms` viaja en el stream de Cloud pero `clasificacion` no tiene columna para guardarla; solo la mide esta prueba desde Redis. Sin ella no se puede auditar F-027 a partir de la base.
3. **L02, punto 3**: el prompt L02 pedía copiar la evidencia del modelo a `EVIDENCE_DIR/modelo/`. La exportación no crea esa carpeta; la evidencia del modelo va dentro de `resumen.json` (`modelo`: métricas de la versión activa y `tabla_m01`) y `resumen.md` solo remite a él.
4. **Métrica registrada del modelo**: `modelo_version.f1_macro_test` = 0.5249 (F1 macro sistema del run desplegado, `best_loss`); la cifra reportable para RNF-03 es la media de la serie M01, 0.4856 ± 0.0322 (N = 10).

---

# Segunda corrida (Q03) · precalentamiento y latencia de inferencia persistida

Fecha: 2026-09-30 · Mismo modelo (`lstm6class-20260928_141021`), mismos 6 clips, mismas convenciones y mismo entorno aislado que la primera corrida (base `sabre_humo` en el puerto 5434, ahora migrada a `0004`; Redis en el 6390; evento nuevo "Humo Q03", modelo activo ya registrado). La primera corrida de arriba se conserva sin cambios.

## Qué cambió respecto a la primera corrida

- Cloud precalienta el modelo al arrancar (F-027): una inferencia con ceros de forma (3, 192), cuyo resultado se descarta. Línea de log al arrancar: `modelo precalentado en 486 ms`.
- `clasificacion.latencia_inferencia_ms` (migración `0004`) guarda la latencia de inferencia que publica Cloud; es campo 17 de L01 y se resume en L02.
- Fog exige `DATABASE_URL` al arrancar.

## Resultados por clip

`inferencia` = `latencia_inferencia_ms` leída **de la base** (coincide con el stream de Redis y con el campo 17 del JSONL y del CSV).

| Clip | Sugerida | Confianza | Clase final | Decisión | `latencia_ms` (sistema) | `ms_clip` (cliente) | Inferencia BiLSTM | Veredicto |
|---|---|---|---|---|---|---|---|---|
| AttackA_0007 | AttackB | 0.534 | AttackA | cambiar | 2943 | 2955 | **26 ms** (primer clip) | 13 ms |
| AttackB_0006 | AttackB | 0.973 | AttackB | mantener | 3363 | 3371 | 22 ms | 7 ms |
| ContrattackA_0002 | ContrattackA | 0.496 | ContrattackA | mantener | 5153 | 5160 | 23 ms | 7 ms |
| ContrattackB_0001 | RiposteB | 0.354 | ContrattackB | cambiar | 5371 | 5379 | 21 ms | 7 ms |
| RiposteA_0021 | AttackA | 0.444 | RiposteA | cambiar | 5082 | 5090 | 12 ms | 7 ms |
| RiposteB_0004 | RiposteB | 0.436 | RiposteB | mantener | 5022 | 5030 | 11 ms | 7 ms |

Las 6 sugerencias y confianzas son idénticas a las de la primera corrida. Los 6 clips quedaron disponibles. La inferencia del primer clip fue 26 ms (en la primera corrida, sin precalentamiento, fue 950 ms). No se investigó la variación de `latencia_ms` entre corridas.

## Exportación L02

| Métrica (V1, N = 6) | Valor | Umbral |
|---|---|---|
| Latencia de la sugerencia, mediana / p95 / máx | 5052 / 5371 / 5371 ms | p95 ≤ 60 000 ms: cumple (RNF-04) |
| Latencia de inferencia, mediana / p95 / máx | 21.5 / 26 / 26 ms | p95 ≤ 50 ms: cumple (F-027) |
| % de inferencias ≤ 50 ms | 100 % | — |
| κ de Cohen sistema-árbitro | 0.40 (aceptable) | ≥ 0.61: no cumple |
| Concordancia | 50 % (3/6) | — |
| Conciliación base vs. JSONL | 6 vs. 6, sin faltantes ni sobrantes | — |
| `fn_verificar_auditoria` | íntegra, 0 alteradas | — |

V2 no tiene revisiones. Como en la primera corrida, son valores de una prueba de humo de 6 clips: **no son evidencia de RNF-03 ni de RNF-06**, y la p95 de inferencia sobre 6 clips tampoco demuestra F-027 en una sesión piloto.

`revisiones.csv` y el JSONL traen 17 campos, con `latencia_inferencia_ms` al final. `resumen.md` y `resumen.json` rotulan `f1_macro_test` = 0.5249 como "checkpoint desplegado (test)" y remiten a la media de la serie M01 (0.4856 ± 0.0322, N = 10) como cifra reportable de RNF-03.

Logs de Fog y Cloud: 0 líneas `ERROR`.

## Limitación: anotaciones de luz de `trimmed_annotations.csv`

`dataset/lstm_6class/train.py` y `evaluate.py` leen `dataset/labels/luz_annotations.csv` (686 clips: 482 train, 99 val, 105 test), así que ese archivo es la referencia de luces del modelo, de esta prueba y del sistema. `dataset/labels/trimmed_annotations.csv` trae otras luces para los mismos clips y no se usa.

Comparación (solo lectura, sin modificar `dataset/`): `trimmed_annotations.csv` tiene 482 clips, todos de train según `luz_annotations.csv`; ningún clip de val ni de test. En 480 de los 482 los frames de luz (`luz_A`/`luz_B` frente a `luz_A_trimmed`/`luz_B_trimmed`) son distintos; solo `AttackA_0053` y `ContrattackB_0019` coinciden. No se investigó la causa de la diferencia.

| Grupo | Clips |
|---|---|
| Difiere solo el número de frame (misma luz encendida en A y en B) | 459 |
| Difiere además qué luces están encendidas (`> 0` en uno y `0` en el otro) | 21 |
| Sin diferencia | 2 |

Las 21 con distinta luz encendida: AttackA_0010, 0054, 0064, 0065, 0090, 0116, 0119, 0120, 0122, 0156, 0197; AttackB_0004, 0050, 0078, 0090, 0130, 0156, 0185, 0198; ContrattackA_0041; RiposteA_0049. La lista completa de los 480 clips con ambos valores está en `docs/evidencia/luz_diferencias_trimmed.csv`.

Consecuencias documentadas:
- Los 6 clips de esta prueba son de test y no están en `trimmed_annotations.csv`: la diferencia no los afecta. (El ejemplo AttackA_0001 de la primera corrida es un clip de train.)
- El filtro Favero del sistema, la evaluación offline (`evaluate.py`) y esta prueba usan `luz_annotations.csv`. Cualquier uso de `trimmed_annotations.csv` daría luces distintas en 480 clips de train, y en 21 de ellos con otra luz encendida.
- No se corrigió ninguno de los dos archivos.

## Hallazgos de la primera corrida: estado

1. F-027 en frío: resuelto con el precalentamiento (primera inferencia 26 ms).
2. Latencia de inferencia sin persistir: resuelto con la migración `0004` (persistida, campo 17 de L01 y resumen L02).
3. Evidencia del modelo en `resumen.json`: sin cambios.
4. Métrica registrada del modelo: sin cambios; `f1_macro_test` = 0.5249 se mantiene y ahora se rotula como "checkpoint desplegado (test)".
