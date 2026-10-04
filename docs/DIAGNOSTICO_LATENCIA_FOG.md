# Diagnóstico de latencia de Fog en Docker (2026-10-04)

## Síntoma
- Clips de más de ~55 frames no terminaban la extracción de pose y la revisión quedaba como "no disponible" (`motivo=timeout`).
- El tiempo E2E de la carga de clip superaba los 60 s (`CLIP_UPLOAD_TIMEOUT_S`, RF-13 / RNF-09).
- Carpeta de prueba: 43 clips de `seoulsabre2026/male` (1280x720, 29–89 frames); unos 12 superaban el plazo.

## Causa raíz
YOLOv8x-pose corre solo en CPU y, dentro del contenedor de Fog, es unas 6 veces más lento que en el equipo anfitrión.

| Entorno | CPUs visibles | Hilos de torch | Tiempo por frame | Clip de 88 frames |
|---|---|---|---|---|
| Fog nativo (Apple M4) | 10 | 4 | 0,18 s | 16 s |
| Fog en Docker (Colima por defecto) | 2 | 1 | 1,04 s | 92 s |

- Ultralytics fija los hilos de torch en `cpu_count - 1` al primer `predict()`; con 2 CPUs queda en 1. Forzar 2 hilos solo mejora ~15 %.
- En el contenedor no hay MPS (GPU de Apple).

## Descartado
- Lectura de video con cv2: funciona en los 43 clips (~0,05 s por clip).
- Cloud: el veredicto tarda ~10 ms.
- `CAP_PROP_FRAME_COUNT` sobreestima los frames de estos clips (cuenta paquetes de preroll con PTS negativo). No afecta: el lector cuenta los frames realmente leídos.

## Decisión
Operar en modo piloto con **Fog nativo y Cloud, Redis, PostgreSQL y frontend en Docker** (`docker-compose.nativo.yml` + `scripts/fog_nativo.sh`, ver DOCK02). No se cambia el modelo ni la extracción de features, para conservar la paridad con el entrenamiento.

Verificación por `POST /matches/{id}/clip`:

| Clip | Frames | E2E |
|---|---|---|
| test_male_39_b | 89 | 16,4 s |
| test_male_40 | 88 | 16,7 s |
| test_male_45 | 86 | 16,0 s |
| test_male_01 | 49 | 9,1 s |

## Notas operativas
- Con el override nativo, levantar con el nombre de proyecto existente para no crear volúmenes nuevos:
  `docker-compose -p sabre -f docker-compose.yml -f docker-compose.nativo.yml up -d postgres redis cloud frontend`.
- Fog en Docker con la VM de Colima por defecto (2 CPUs) no cumple el plazo de 60 s con clips largos. Si se vuelve a Docker, subir las CPUs de Colima y volver a medir.
- Reinicio de la instancia de validación: `TRUNCATE` de las tablas de datos (los triggers de inmutabilidad de `registro_auditoria`, `veredicto` y `clasificacion` bloquean `DELETE`), conservando `evento`, `usuario` y `modelo_version`, y vaciado de `datos/storage` y `datos/evidencia`. Hacer antes un `pg_dump`.
