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
  veredicto (sección 5) y al reportar la luz Favero (sección 3). Si no se envía, Fog
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

## 4. Fog → Cloud: `fog:features` (Redis Stream)

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

## 5. Cloud → Fog: `cloud:verdicts:{match_id}` (Redis Stream)

Una entrada por veredicto:

| campo | tipo | descripción |
|---|---|---|
| `match_id` | str | |
| `action_class` | str | una de `AttackA, AttackB, ResponseA, ResponseB` |
| `confidence` | str | probabilidad softmax de la clase ganadora (post arbitraje de luz), `"0.0"`-`"1.0"` |
| `fencer` | str | `"ROJ"` si la clase termina en `A`, `"VER"` si termina en `B` (mapeo fijo v1) |
| `ts` | str | timestamp ISO |

`action_class` ya viene resuelto por `FaveroHardMaskPolicy`: si exactamente una luz se
encendió, el lado imposible queda con probabilidad 0 y se re-normaliza/re-argmax antes
de publicar. Si ambas luces o ninguna se encendieron (caso ambiguo), el veredicto crudo
del LSTM se publica sin cambios.

Fog mantiene una tarea de fondo por `match_id` activo que hace `XREAD` bloqueante sobre
este stream y reenvía el resultado por WebSocket en cuanto llega.

## 6. Fog → Front: WebSocket de veredicto

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

## 7. Notas y desviaciones respecto a los diagramas de arquitectura

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
  resultado de `LSTM4ClassAdapter` ya arbitrado por `FaveroHardMaskPolicy` (sección 5),
  no la salida cruda del LSTM. Las reglas FIE completas (t.101-t.106, prioridad de
  ataque/cobertura/etc.) quedan para una versión posterior — `ArbitrationPolicyPort`
  está diseñado para admitir una implementación más rica sin tocar el resto del sistema.
- **Luz Favero**: sin integración física con el aparato real. El front debe simular/
  capturar la señal y reportarla vía `POST /webrtc/{match_id}/luz` (sección 3).
- **Mapeo A/B ↔ ROJ/VER**: fijo (`A=ROJ`, `B=VER`) para v1, confirmado por Nicolas. No
  configurable por combate todavía.

## 8. Pendiente del lado del front (fuera de esta entrega)

Carlos necesita agregar en `var-esg`:
1. Captura del video subido manualmente como `MediaStreamTrack` y armado del
   `RTCPeerConnection` (oferta SDP) hacia `POST /webrtc/offer`.
2. Envío de `weapon_side_A/B` (o UI para configurarlos; por defecto `"right"`/`"right"`).
3. Captura/reporte de la luz Favero vía `POST /webrtc/{match_id}/luz` antes de que
   expire `FAVERO_LUZ_TIMEOUT_S` (sección 3).
4. Cliente WebSocket a `/ws/veredicto/{match_id}` y mapeo de `action`/`fencer`/
   `confidence` a los componentes existentes (`ActionPanel`, `HistorialPanel`, etc.),
   reemplazando los datos de `mock.ts`.
