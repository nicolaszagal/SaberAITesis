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
