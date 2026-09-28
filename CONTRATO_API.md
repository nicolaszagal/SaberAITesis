# Contrato de integración — Edge (front) ↔ Fog ↔ Cloud

Versión v1 (carga manual de un solo clip de acción). Sigue `arquitectura_diagramas.html`
con dos adaptaciones documentadas en la sección final.

## 1. Flujo

```
Front (Edge)  --WebRTC (oferta SDP + config combate)-->  Fog (API Gateway)
Front (Edge)  <--WebSocket (veredicto)--------------------  Fog
Fog           --Redis Stream "fog:features"-------------->  Cloud
Cloud         --Redis Stream "cloud:verdicts"------------->  Fog
```

Un "combate" en v1 = un clip de una sola acción, subido manualmente desde el front.
No hay streaming en vivo ni múltiples acciones por sesión.

## 2. Edge → Fog: señalización WebRTC

`POST /webrtc/offer`

Body (JSON):
```json
{
  "sdp": "<SDP offer>",
  "type": "offer",
  "match_id": "uuid-o-string-unico-por-clip",
  "weapon_side_A": "right",
  "weapon_side_B": "right"
}
```

- `weapon_side_A/B`: `"right"` o `"left"`. Brazo armado de cada tirador. Si no se envía,
  Fog usa `"right"` para ambos (igual que el MVP del dataset).
- `match_id`: identificador que el front debe reutilizar al conectar el WebSocket de
  veredicto (sección 7) y al reportar la luz Favero (sección 3). Si no se envía, Fog
  genera uno y lo devuelve en la respuesta.

Respuesta (JSON):
```json
{ "sdp": "<SDP answer>", "type": "answer", "match_id": "..." }
```

El front debe abrir un `RTCPeerConnection`, agregar **una sola pista de video** (el clip
subido, vía `captureStream()` de un `<video>` o equivalente en RN), generar la oferta,
hacer `POST` a este endpoint, y aplicar la respuesta como `setRemoteDescription`.

Cuando el clip termina de reproducirse y la pista de video llega a su fin (evento
`ended` del track), Fog interpreta eso como "fin del clip" y dispara el procesamiento.
No hace falta cerrar el `RTCPeerConnection` explícitamente, pero es buena práctica
hacerlo tras recibir el veredicto.

## 3. Edge → Fog: señal de luz Favero

`POST /webrtc/{match_id}/luz`

El modelo desplegado (`lstm_4class`) usa la luz Favero como entrada real del modelo
(concatenada después del pooling, antes de la capa final), no solo como regla de
arbitraje. El front debe reportarla en cuanto el clip termina de reproducirse,
**antes** de que Fog dispare la clasificación; si no llega dentro de
`FAVERO_LUZ_TIMEOUT_S` (2s por defecto, configurable por entorno), Fog continúa sin
luz (`has_luz_A = has_luz_B = false`).

Body (JSON):
```json
{ "has_luz_A": true, "has_luz_B": false }
```

Respuesta (JSON):
```json
{ "match_id": "...", "received": true }
```

## 4. Edge → Fog: carga de clip sin WebRTC

`POST /matches/{match_id}/clip` (multipart/form-data)

Alternativa a `POST /webrtc/offer` + sección 3: sube un clip ya grabado
en un solo request, junto con los frames en que se prendió cada luz
Favero (`luz_frame_a`/`luz_frame_b`, índices de frame 0-based, `null`/
omitido si esa luz no se prendió). A diferencia del flujo WebRTC, la
respuesta es **síncrona**: corre pose+tracking+features, publica en
Redis y espera el veredicto de Cloud (con timeout,
`CLIP_UPLOAD_VERDICT_TIMEOUT_S`, 30 s por defecto) antes de responder.

Respuesta (JSON):
```json
{
  "match_id": "...",
  "has_luz_A": true,
  "has_luz_B": false,
  "timed_out": false,
  "disponible": true,
  "motivo": null,
  "fencer": "ROJ",
  "action": "AttackA",
  "confidence": 0.74
}
```

`disponible=false` cubre dos casos (DEF-08), distinguidos por `motivo`
(mismos valores de `clasificacion.motivo_no_disp` que la sección 7):

- **Pose incompleta** (`motivo="pose_incompleta"`, `timed_out=false`):
  Fog no pudo extraer features válidas (sin lock A/B, o clip por debajo
  de `MIN_FRAMES`) y nunca publicó en Redis — responde de inmediato, sin
  esperar a Cloud. `fencer`/`action`/`confidence` quedan en `null`.
- **Timeout de Cloud** (`motivo="timeout"`, `timed_out=true`): Fog sí
  publicó features pero Cloud no respondió dentro del timeout
  configurado. `fencer`/`action`/`confidence` quedan en `null`.

## 5. Fog → Cloud: `fog:features` (Redis Stream)

Cada clip procesado por Fog genera **una sola entrada** en el stream:

| campo           | tipo  | descripción                                                                         |
|-----------------|-------|-------------------------------------------------------------------------------------|
| `match_id`      | str   | igual que el de la oferta                                                           |
| `shape`         | str   | `"T,192"` (T = frames reales del clip)                                              |
| `dtype`         | str   |  `"float32"`                                                                        |
| `features`      | bytes | `array.tobytes()` — array `(T,192)` ya en el orden A(96)+B(96), estandarizado con `feature_stats.npz` y con ablación aplicada en los índices 95/191 (vel_elbow_angle, igual que en entrenamiento)                                                                                           |
| `has_luz_A`     | str   | `"true"`/`"false"`, lo reportado en la sección 3 (o `"false"` si no llegó a tiempo) |
| `has_luz_B`     | str   | idem para B                                                                         |
| `weapon_side_A` | str   | reenviado tal cual                                                                  |
| `weapon_side_B` | str   | reenviado tal cual                                                                  |                
| `ts`            | str   | timestamp ISO de cuándo Fog terminó de extraer                                      |    

Cloud consume con un grupo de consumidores `cloud_workers` (1 worker por pista, según
diagrama). Reconstrucción: `np.frombuffer(features, dtype=dtype).reshape(shape)`.

**Validación y tolerancia a fallos (DEF-09).** `RedisFeatureConsumer` valida cada entrada
antes de reconstruir el array: campos obligatorios presentes (`match_id`, `shape`,
`dtype`, `features`, `weapon_side_A`, `weapon_side_B`), `dtype == "float32"`,
`shape == "T,192"` con `T >= 1`, y `len(features) == T * 192 * 4` bytes. Una entrada que
no cumple el contrato:

1. Se loguea (una línea, con el motivo).
2. Se publica un veredicto `disponible=false` en `cloud:verdicts:{match_id}` con
   `motivo_no_disp="mensaje_invalido"` (si el propio `match_id` no era legible, no hay
   veredicto que publicar).
3. Se mueve a `fog:features:dead` (mismos campos + `motivo` + `entry_id_original`) y se
   hace `XACK` sobre `fog:features` — sin esto, la entrada queda pendiente para siempre y
   `XREADGROUP ">"` nunca vuelve a entregarla tras un reinicio.

Cualquier otra excepción durante el procesamiento de una entrada (clasificador,
arbitraje, publisher) también se captura por mensaje: nunca detiene el loop de Cloud, solo
se pierde el veredicto de esa entrada (queda en el log).

Al arrancar, Cloud reclama con `XAUTOCLAIM` las entradas que quedaron pendientes de un
worker anterior que murió entre `XREADGROUP` y el `XACK` (idle mínimo configurable por
`CLAIM_MIN_IDLE_S`, 60 s por defecto) y las reprocesa con la misma validación antes de
entrar al loop de lectura bloqueante.

## 6. Cloud → Fog: `cloud:verdicts:{match_id}` (Redis Stream)

Una entrada por veredicto. `disponible` distingue dos formas (igual que
`clasificacion.disponible` en `sabre_ai_schema.sql`):

**`disponible=true`:**

| campo | tipo | descripción |
|---|---|---|
| `match_id` | str | |
| `disponible` | str | `"true"` |
| `action_class` | str | una de `AttackA, AttackB, ResponseA, ResponseB` |
| `confidence` | str | probabilidad softmax de la clase ganadora (post arbitraje de luz), `"0.0"`-`"1.0"` |
| `fencer` | str | `"ROJ"` si la clase termina en `A`, `"VER"` si termina en `B` (mapeo fijo v1) |
| `probs` | str | JSON `{"AttackA": 0.61, ...}` — softmax completo, post filtro Favero (auditoría, RF-22) |
| `latencia_inferencia_ms` | str | duración de `ActionClassifierPort.classify` en ms (auditoría, RNF-04) |
| `modelo` | str | `shared.config.MODEL_VERSION_NAME` — nombre de la versión del modelo activo |
| `ts` | str | timestamp ISO |

**`disponible=false`** (DEF-09, mensaje de `fog:features` inválido — ver sección 5):

| campo | tipo | descripción |
|---|---|---|
| `match_id` | str | |
| `disponible` | str | `"false"` |
| `motivo_no_disp` | str | uno de `clasificacion.motivo_no_disp` (`sabre_ai_schema.sql`); hoy solo `"mensaje_invalido"` |
| `ts` | str | timestamp ISO |

`action_class` ya viene resuelto por `FaveroHardMaskPolicy`: si exactamente una luz se
encendió, el lado imposible queda con probabilidad 0 y se re-normaliza/re-argmax antes
de publicar. Si ambas luces o ninguna se encendieron (caso ambiguo), el veredicto crudo
del LSTM se publica sin cambios.

**Pendiente (fuera de esta entrega):** `RedisVerdictSubscriber` en Fog
(`fog/infrastructure/messaging/redis_verdict_subscriber.py`) todavía asume que toda
entrada de este stream trae `action_class`/`confidence`/`fencer` y no lee `disponible` —
una entrada `disponible=false` le va a lanzar `KeyError`. Fog necesita un cambio
correspondiente para manejar este caso antes de que DEF-09 sea visible end-to-end en el
front; no está incluido acá porque no toca ninguno de los archivos de Cloud de esta
entrega.

Fog mantiene una tarea de fondo por `match_id` activo que hace `XREAD` bloqueante sobre
este stream y reenvía el resultado por WebSocket en cuanto llega.

## 7. Fog → Front: WebSocket de veredicto

`GET /ws/veredicto/{match_id}` (el front se conecta antes o inmediatamente después de
enviar la oferta WebRTC, usando el mismo `match_id`).

Mensaje que Fog envía cuando el veredicto está listo:
```json
{
  "type": "veredicto",
  "match_id": "...",
  "fencer": "ROJ",
  "action": "AttackA",
  "confidence": 0.74
}
```

Si la clasificación no está disponible (DEF-08: pose incompleta, sin
lock A/B o clip demasiado corto), Fog no publica nada en el stream
`fog:features` — nunca le llega a Cloud — y responde de inmediato por
este mismo WebSocket:
```json
{
  "type": "no_disponible",
  "match_id": "...",
  "motivo": "pose_incompleta"
}
```

`motivo` es uno de `clasificacion.motivo_no_disp`
(`sabre_ai_schema.sql`): `pose_incompleta`, `confianza_baja`,
`clase_fuera_mvp`, `timeout`, `sin_senal_favero`, `mensaje_invalido`. Hoy Fog solo puede
producir `pose_incompleta` (los dos únicos errores que devuelve
`FeatureExtractorPort.extract` — sin lock A/B, o secuencia bajo
`min_frames` — mapean a ese motivo); `confianza_baja` y
`clase_fuera_mvp` son responsabilidad de Cloud y no están implementados
todavía (el umbral de confianza no está documentado). `mensaje_invalido`
(DEF-09) lo produce Cloud cuando una entrada de `fog:features` no respeta
el contrato — hoy solo llega a Fog vía `cloud:verdicts:{match_id}`
(sección 6); todavía no se reenvía por este WebSocket (ver pendiente en
sección 6).

Carlos debe traducir `action` (taxonomía interna en inglés, 4 clases) a las etiquetas en
español que ya usa el front (`mock.ts`: "ATAQUE AL PECHO", "PARADA-RESPUESTA",
"CONTRAATAQUE EN TIEMPO", etc.). Esa traducción **no** vive en el backend porque depende
de decisiones de UI/copy que son de Carlos. Tabla sugerida:

| `action` (backend) | sugerido en español |
|---|---|
| `AttackA` / `AttackB` | "ATAQUE" |
| `ResponseA` / `ResponseB` | "RESPUESTA" |

`ResponseA`/`ResponseB` unifica lo que en el dataset original eran dos carpetas
distintas (`ContrattackA/B` y `RiposteA/B`) bajo una sola clase del modelo
(`dataset/lstm_4class/lstm_dataset.py`, `FOLDER_TO_CLASS`). El backend no distingue
contraataque de riposte; si el front necesita esa distinción para el copy, requiere
reentrenar con esa separación, no es un cambio de capa de presentación.

`confidence` ya viene en escala 0–1; el front la muestra como % (`mock.ts` usa enteros
0–100, ej. `94`).

## 8. Notas y desviaciones respecto a los diagramas de arquitectura

- **Modelo desplegado**: `dataset/lstm_4class/checkpoints/best_model.pt` — 4 clases
  (`AttackA, AttackB, ResponseA, ResponseB`), 192 features (96 por tirador, incluye
  bloque biomecánico Fase B), luz Favero como entrada real del modelo (no solo regla de
  arbitraje) y pooling por atención aditiva. Reemplaza al pipeline anterior de 6 clases/
  182 features, que queda completamente descartado (no se despliega ni se mantiene).
- **Tracker**: se usa ByteTrack vía `model.track(..., persist=True)` de Ultralytics
  (igual que `dataset/lstm_4class/05_extract_features.py`), no DeepSORT como indica el
  diagrama de capas. Motivo: consistencia con el pipeline que generó los datos de
  entrenamiento — cambiar de tracker puede cambiar el comportamiento de asignación de
  IDs A/B.
- **Detector de pose**: YOLOv8x-pose (no YOLOv8n-pose como indica el diagrama), decisión
  confirmada por Nicolas para mantener fidelidad con el entrenamiento. Sin requisito de
  tiempo real en v1, el costo de latencia es aceptable.
- **Scoring Híbrido FIE**: no implementado en v1. El veredicto que llega al front es el
  resultado de `LSTM4ClassAdapter` ya arbitrado por `FaveroHardMaskPolicy` (sección 6),
  no la salida cruda del LSTM. Las reglas FIE completas (t.101-t.106, prioridad de
  ataque/cobertura/etc.) quedan para una versión posterior — `ArbitrationPolicyPort`
  está diseñado para admitir una implementación más rica sin tocar el resto del sistema.
- **Luz Favero**: sin integración física con el aparato real. El front debe simular/
  capturar la señal y reportarla vía `POST /webrtc/{match_id}/luz` (sección 3).
- **Mapeo A/B ↔ ROJ/VER**: fijo (`A=ROJ`, `B=VER`) para v1, confirmado por Nicolas. No
  configurable por combate todavía.

## 9. Pendiente del lado del front (fuera de esta entrega)

Carlos necesita agregar en `var-esg`:
1. Captura del video subido manualmente como `MediaStreamTrack` y armado del
   `RTCPeerConnection` (oferta SDP) hacia `POST /webrtc/offer`.
2. Envío de `weapon_side_A/B` (o UI para configurarlos; por defecto `"right"`/`"right"`).
3. Captura/reporte de la luz Favero vía `POST /webrtc/{match_id}/luz` antes de que
   expire `FAVERO_LUZ_TIMEOUT_S` (sección 3).
4. Cliente WebSocket a `/ws/veredicto/{match_id}` y mapeo de `action`/`fencer`/
   `confidence` a los componentes existentes (`ActionPanel`, `HistorialPanel`, etc.),
   reemplazando los datos de `mock.ts`.
