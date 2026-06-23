# Plan de refactor a DDD/SOLID — Fog + Cloud

Requisitos y plan de trabajo previo al desarrollo, levantados por entrevista con Nicolas
(2026-06-20). No incluye código — es la base para el refactor que sigue.

## 1. Decisiones confirmadas

| Tema | Decisión |
|---|---|
| Modelo a desplegar | `lstm_4class` (4 clases, 192 features, luz Favero como input real del modelo vía `luz_size=2`). Reemplaza al pipeline viejo de 6 clases/182 features, que se descarta del backend. |
| Checkpoint | `dataset/lstm_4class/checkpoints/best_model.pt` (criterio val loss). Accuracy real documentada: 53.8% sin regla de máscara Favero (luz no disponible o ambigua), 66.3% con la regla hard (`apply_favero_mask`, requiere señal real de luz). Ninguna fuente da exactamente "62%" — la cifra a citar en la tesis es una de estas dos según el escenario, no un número intermedio inventado. |
| Luz Favero | Se integra en v1. El aparato Favero comunica el toque vía RJ11 a una capturadora en el nodo Edge (lector serial + sincronizador, según `arquitectura_diagramas.html`). Esa pieza queda fuera de este trabajo (la construye Carlos/front), pero el contrato Edge→Fog se extiende para recibir `has_luz_A`/`has_luz_B`. |
| Alcance del refactor | Evolucionar `backend/` existente (extraer puertos alrededor de la lógica ya verificada), no reescribir desde cero. |
| Profundidad DDD | 4 capas por servicio: `domain/`, `application/`, `ports/`, `infrastructure/`. `shared/` solo para lo realmente común (config, constantes de wire-format) — sin entidades de dominio compartidas entre Fog y Cloud (son bounded contexts separados). |
| Límite ML/features | `FeatureExtractorPort` es un puerto independiente de `ActionClassifierPort` (no encapsulado dentro del clasificador), pese a que en la práctica un extractor solo es válido para el modelo entrenado con él. Justificado por el historial real del proyecto (ablaciones, cambios 182→192) — ya hay más de una implementación real, no es abstracción especulativa. |
| Scoring híbrido FIE | Se define `ArbitrationPolicyPort` ahora. Implementación inicial: solo aplica la máscara hard de luz Favero (`apply_favero_mask`). Las reglas de prioridad FIE t.101-t.106 quedan como una implementación futura del mismo puerto, sin tocar el resto del sistema. |
| Persistencia | Fuera de alcance por ahora, pero con `MatchRepositoryPort` definido y una única implementación `InMemoryMatchRepository`. Agregar MongoDB después es swap de adaptador. |
| Wiring de adaptadores | Contenedor de DI (ej. `dependency-injector`) en vez de composition root manual. Confirmar versión exacta del paquete al implementar (no asumir). |
| Adaptador legacy (182/6 clases) | Se descarta. Solo se mantiene el pipeline nuevo (192/4 clases/luz) como implementación real de los puertos. |
| Testing | Unitarios por puerto/adaptador (con datos reales del dataset donde aplique) + el smoke test end-to-end ya pendiente (tarea #6), usando fakes para aislar (`FakePoseEstimator`, `FakeRedis`, etc.). Sin CI por ahora. |
| Fecha límite | Ninguna fijada. El plan se ordena por dependencias lógicas, no por sprint. |

## 2. Arquitectura objetivo

### 2.1 Puertos (interfaces)

**Fog**

| Puerto | Entrada | Salida | Reemplaza hoy |
|---|---|---|---|
| `PoseEstimatorPort` | lista de frames (ndarray BGR) | `TrackedSequence` (keypoints + ids A/B por frame, ya con `try_lock_ids` aplicado) | lógica YOLO+tracking embebida en `feature_extractor.py` |
| `FeatureExtractorPort` | `TrackedSequence`, `weapon_side_A/B` | `ExtractedFeatures` (`sequence: ndarray (T,192)`, `stats: dict`) | resto de `feature_extractor.py` (cálculo biomecánico) |
| `MatchRepositoryPort` | `Match` (entidad) | — | `MATCHES: dict` global en `fog/main.py` |
| `FeatureStreamPublisherPort` | `match_id`, `ExtractedFeatures`, `LuzSignal \| None`, lados de arma | — | `redis_client.xadd(...)` directo en `_process_match` |
| `VerdictStreamSubscriberPort` | `match_id` | `Verdict` | `_wait_for_verdict` con `xread` directo |

**Cloud**

| Puerto | Entrada | Salida | Reemplaza hoy |
|---|---|---|---|
| `FeatureStreamConsumerPort` | — | stream de `(match_id, ExtractedFeatures, LuzSignal\|None, lados)` | `xreadgroup` directo en `run()` |
| `ActionClassifierPort` | `ExtractedFeatures`, `LuzSignal \| None` | `RawVerdict` (clase + confianza + probs) | `load_model`/`infer` en `cloud/main.py` |
| `ArbitrationPolicyPort` | `RawVerdict`, `LuzSignal \| None` | `Verdict` (final) | nada hoy (el raw verdict se publica tal cual) |
| `VerdictPublisherPort` | `match_id`, `Verdict` | — | `redis_client.xadd(...)` directo |

`LuzSignal` = value object `{has_luz_A: bool, has_luz_B: bool}`.

### 2.2 Estructura de carpetas

```
backend/
  fog/
    domain/            # Match, TrackedSequence, ExtractedFeatures, WeaponSide
    application/        # ProcessIncomingMatch (caso de uso orquestador)
    ports/               # PoseEstimatorPort, FeatureExtractorPort, MatchRepositoryPort,
                         # FeatureStreamPublisherPort, VerdictStreamSubscriberPort
    infrastructure/
      pose/              # YoloV8PoseAdapter (ByteTrack vía ultralytics .track)
      features/          # New192FeatureExtractor (lstm_4class, con luz)
      persistence/       # InMemoryMatchRepository
      messaging/         # RedisFeaturePublisher, RedisVerdictSubscriber
      webrtc/            # AiortcFrameSource
      api/               # routers FastAPI (offer, ws veredicto, luz-event)
    composition.py       # contenedor DI, lee config
    main.py               # solo arma la app FastAPI con el contenedor

  cloud/
    domain/             # Verdict, RawVerdict, ActionClass, LuzSignal
    application/         # ClassifyAndPublishVerdict (caso de uso orquestador)
    ports/                # ActionClassifierPort, ArbitrationPolicyPort,
                          # FeatureStreamConsumerPort, VerdictPublisherPort
    infrastructure/
      classifier/         # Lstm4ClassAdapter (192 features, 4 clases, luz)
      arbitration/         # FaveroHardMaskPolicy
      messaging/            # RedisFeatureConsumer, RedisVerdictPublisher
    composition.py
    main.py

  shared/
    config.py            # igual que hoy, actualizado a los nuevos defaults
    wire_format.py        # constantes de los streams Redis (nombres, encoding)
```

### 2.3 Punto abierto a resolver en implementación (no requiere decisión de Nicolas ahora)

Cómo viaja `has_luz_A/B` desde Edge a Fog: el evento de toque ocurre *durante* la reproducción
del clip, no se conoce al momento de `POST /webrtc/offer`. Propuesta: nuevo endpoint
`POST /webrtc/{match_id}/luz` que Edge llama una vez sincronizado el evento RJ11 con el video;
Fog combina ese valor con `ExtractedFeatures` antes de publicar a `fog:features`, con default
`{False, False}` tras un timeout corto (mismo criterio que usa el dataset para clips sin
anotación de luz). Validar con Carlos al implementar el lado de Edge.

## 3. Cambios pendientes al contrato externo (`CONTRATO_API.md`)

No se aplican todavía — quedan listados para cuando se implemente:

1. Sección 6 ("Notas y desviaciones"): corregir el modelo desplegado (4 clases/192 features/
   con luz, no el de 6 clases) y la cifra de accuracy real (53.8%/66.3% según escenario, no
   68.6%).
2. Nuevo endpoint `POST /webrtc/{match_id}/luz` (sección 2 o nueva sección).
3. Stream `fog:features` (sección 3): `shape` pasa a `"T,192"`; agregar campos `has_luz_A`,
   `has_luz_B`.
4. Stream `cloud:verdicts` (sección 4): `action_class` pasa a una de
   `AttackA, AttackB, ResponseA, ResponseB` (ya no 6 clases).
5. Nota sobre `ArbitrationPolicyPort`: el veredicto que llega al front ya pasó por la máscara
   hard de luz cuando hay señal; documentar que sin señal de luz el veredicto es el crudo del
   LSTM (53.8% esperado, no 66.3%).
6. Sección 7 (pendiente del front/Edge): agregar la lectura RJ11 + sincronización + llamada al
   nuevo endpoint de luz como responsabilidad de Edge.

## 4. Plan de trabajo (orden por dependencias)

1. Definir value objects y entidades de dominio (`domain/` en ambos servicios) — sin
   dependencias externas, base de todo lo demás.
2. Definir los puertos (`ports/`) como clases abstractas/`Protocol`, con sus firmas exactas.
3. Implementar adaptadores de infraestructura envolviendo el código ya verificado:
   `YoloV8PoseAdapter` + `New192FeatureExtractor` (a partir de `feature_extractor.py`,
   adaptado a 192 features con bloque bio incluido), `Lstm4ClassAdapter` (a partir de
   `lstm_classifier.py` apuntando a `lstm_4class/models/lstm_classifier.py`),
   `FaveroHardMaskPolicy` (a partir de `apply_favero_mask`), adaptadores Redis
   (a partir de `fog/main.py`/`cloud/main.py` actuales), `InMemoryMatchRepository`.
4. Armar `composition.py` por servicio (contenedor DI) y reducir `main.py` a solo exponer la
   app FastAPI / loop de Cloud usando el contenedor.
5. Actualizar `shared/config.py` a los nuevos defaults (checkpoint, dims, num_classes=4).
6. Tests unitarios por puerto/adaptador con datos reales del dataset.
7. Aplicar los cambios listados en la sección 3 a `CONTRATO_API.md`.
8. Smoke test end-to-end con un clip real (tarea #6 ya existente).
9. `requirements.txt` + guía de ejecución (tarea #7 ya existente), incluyendo la nueva
   dependencia de DI.

## 5. Riesgos y pendientes abiertos

- La integración RJ11/Edge depende de Carlos; sin ella, producción corre en el escenario
  "sin luz" (53.8%), no el de 66.3%.
- Las reglas FIE t.101-t.106 (Scoring Híbrido completo) quedan sin implementación real, solo
  el puerto definido.
- La varianza entre corridas del LSTM de 4 clases (ver memoria `project_fase_b_lstm_variance`)
  sigue sin explicarse — el 66.3%/53.8% es de una corrida, no un promedio de varias.
