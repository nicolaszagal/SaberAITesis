# Guía de ejecución — Backend SABRE.AI

## 1. Requisitos previos

- Python 3.10+ (verificado con 3.10).
- Redis corriendo y accesible (broker entre Fog y Cloud). Sin Redis, ni Fog ni
  Cloud arrancan.
- `dataset/yolov8x-pose.pt`, `dataset/lstm_4class/checkpoints/best_model.pt` y
  `dataset/lstm_4class/feature_stats.npz` presentes en el repo (rutas por
  defecto en `shared/config.py`, todas override-ables por env var).

## 2. Instalación

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# torch primero, siguiendo https://pytorch.org/get-started/locally/
# según tu plataforma (CPU/CUDA/MPS) — no incluido en requirements.txt
# porque el wheel correcto depende del hardware.
pip install torch

pip install -r requirements.txt
```

`ultralytics` no tiene versión pinneada en `requirements.txt` (no se pudo
verificar en el entorno donde se construyó este backend). Si ya tenés una
versión fijada para `dataset/lstm_4class/05_extract_features.py`, usar esa
misma para evitar divergencias de comportamiento entre tracking de
entrenamiento y producción.

## 3. Variables de entorno (todas opcionales, ver `shared/config.py`)

| variable                | default                                         | uso |
|-------------------------|-------------------------------------------------|-----|
| `REDIS_URL`             | `redis://localhost:6379/0`                      | conexión Fog y Cloud |
| `YOLO_POSE_MODEL_PATH`  | `dataset/yolov8x-pose.pt`                       | modelo de pose (Fog) |
| `LSTM_CHECKPOINT_PATH`  | `dataset/lstm_4class/checkpoints/best_model.pt` | checkpoint LSTM (Cloud) |
| `FEATURE_STATS_PATH`    | `dataset/lstm_4class/feature_stats.npz`         | mean/std de estandarización (Fog) |
| `FAVERO_LUZ_TIMEOUT_S`  | `2.0`                                           | espera máxima de la luz Favero antes de clasificar sin ella |
| `CLOUD_CONSUMER_NAME`   | `cloud-worker-1`                                | nombre de consumidor en el grupo `cloud_workers` (relevante si se levanta más de una instancia de Cloud) |

## 4. Levantar los servicios

Cloud y Fog son procesos independientes; ambos requieren Redis arriba.

```bash
# Terminal 1 — Cloud (consumidor + clasificador)
cd backend
python -m cloud.main

# Terminal 2 — Fog (API Gateway WebRTC)
cd backend
python -m uvicorn fog.main:app --host 0.0.0.0 --port 8001
```

Si `python -m cloud.main` falla con `redis.exceptions.ConnectionError`,
es porque Redis no está corriendo — confirmar el prerequisito de la sección 1
(`redis-server` o el contenedor equivalente) antes de levantar Cloud o Fog.

Swagger UI de Fog: `http://localhost:8001/docs` (generado automáticamente por
FastAPI a partir de `fog/infrastructure/api/routes.py` y
`fog/infrastructure/api/schemas.py`). El WebSocket (`/ws/veredicto/{match_id}`)
no aparece ahí porque OpenAPI no documenta WebSockets — el contrato de sus
mensajes está en `CONTRATO_API.md` sección 6.

Cloud no expone HTTP; es un loop de consumo de Redis (`python -m cloud.main`)
sin servidor.

## 5. Tests

```bash
cd backend
python3 -m pytest tests/ -v
```

28 tests, todos con fakes (sin Redis, sin modelos reales, sin
`ultralytics` instalado) — cubren `application/` de Fog y Cloud,
`InMemoryMatchRepository`, `New192FeatureExtractor`, `try_lock_ids` y
`FaveroHardMaskPolicy`. `LSTM4ClassAdapter` se prueba con un checkpoint
sintético (misma arquitectura, pesos aleatorios) para no depender del
checkpoint real de producción en un test unitario.

No cubierto por estos tests (pendiente, ver tarea "Smoke test end-to-end"):
`YoloV8PoseAdapter` (requiere `ultralytics` + modelo real) y el flujo
completo WebRTC -> Redis -> Cloud -> WebSocket con un clip real del dataset.

## 6. Limitaciones conocidas de esta entrega

- Sin CI configurado (decisión explícita: tests corren manualmente).
- `MatchRepositoryPort` solo tiene implementación en memoria
  (`InMemoryMatchRepository`) — no persiste entre restarts de Fog.
- Sin integración física con la luz Favero real; el front debe simularla y
  reportarla vía `POST /webrtc/{match_id}/luz` (ver `CONTRATO_API.md`).
- Smoke test end-to-end con clip real del dataset todavía pendiente.
