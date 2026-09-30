# Contrato de integración — Edge (front) ↔ Fog ↔ Cloud

Versión v1 (carga manual de clips de acción; un combate admite N revisiones). Sigue
`arquitectura_diagramas.html` con dos adaptaciones documentadas en la sección final.

## 1. Flujo

```
Front (Edge)  --WebRTC (oferta SDP + config combate)-->  Fog (API Gateway)
Front (Edge)  <--WebSocket (veredicto)--------------------  Fog
Fog           --Redis Stream "fog:features"-------------->  Cloud
Cloud         --Redis Stream "cloud:verdicts:{revision_id}"-->  Fog
```

**Revisiones por clip.** Un combate admite N revisiones: cada clip subido con
`POST /matches/{match_id}/clip` abre su propia `revision_var` (con su `tocado`, su `clip`,
su clasificación y su veredicto) y devuelve su **`revision_id`**. No hay límite de clips por
combate (ya no existe el 409 por segundo clip). El `revision_id` es la clave de todo lo que
sigue al clip: el campo de `fog:features`, el stream de veredicto de Cloud
(`cloud:verdicts:{revision_id}`), `GET /ws/veredicto/{revision_id}` y
`POST /revisiones/{revision_id}/veredicto`. Dos clips del mismo combate tienen
clasificaciones y veredictos independientes. No hay streaming en vivo.

El `match_id` de la API es el **id del combate** (`sabre.combate.id`, uuid) creado en la
sección 1.1. Un `match_id` de un combate que no fue creado responde **404** en
`POST /matches/{match_id}/clip` (sin combate por defecto). Para `/webrtc/offer`, el combate
"existe" al crear su sesión con el `weapon_side_A/B` del body, salvo que el `match_id` ya sea
un combate configurado: entonces se usa su brazo armado guardado.

**Vocabulario de clases.** La API usa siempre los nombres del modelo: `AttackA`, `AttackB`,
`ContrattackA`, `ContrattackB`, `RiposteA`, `RiposteB` (D-06), tanto en las respuestas
(`action`) como en `clase_final`. Los nombres del esquema (`AtaqueA`, `ContraataqueA`, …)
existen solo en la base: la traducción ocurre únicamente en los adaptadores de persistencia
(`fog/infrastructure/persistence/postgres/vocabulario.py`). Un nombre del esquema en la API
es un valor inválido (422).

## 1.1 Configurar combate (CU-01, F-039, RF-07)

`POST /matches/config`

Crea en una sola transacción los dos tiradores (`tirador`, por alias) y el `combate`.

Body (JSON):
```json
{
  "evento_id": "uuid",
  "pista": "P1",
  "arbitro_id": "uuid",
  "alias_A": "Rojo",
  "weapon_side_A": "right",
  "es_menor_A": false,
  "consentimiento_firmado_A": false,
  "consentimiento_fecha_A": null,
  "firmante_A": null,
  "alias_B": "Verde",
  "weapon_side_B": "left",
  "es_menor_B": false
}
```

| campo | obligatorio | notas |
|---|---|---|
| `evento_id` | sí | debe existir en `sabre.evento` (404 si no) |
| `pista` | sí | texto no vacío |
| `arbitro_id` | sí | debe existir en `sabre.usuario` (404 si no). Se guarda también como `configurado_por` (no hay login ni operador identificado) |
| `alias_A/B` | sí | alias del tirador (minimización de datos) |
| `weapon_side_A/B` | **sí, sin valor por defecto** | `"right"` → `diestro`, `"left"` → `zurdo`. Se guarda en `combate.brazo_a/b` y `tirador.brazo_habitual`. Sin él: 422 y no se crea nada |
| `es_menor_A/B` | sí | `tirador.es_menor` es NOT NULL |
| `consentimiento_firmado_A/B` | no (`false`) | RNF-16 |
| `consentimiento_fecha_A/B` | si está firmado | 422 si falta (CHECK del esquema) |
| `firmante_A/B` | si es menor y firmó | 422 si falta (CHECK del esquema) |

Cada configuración crea sus dos tiradores nuevos (el alias no es único en el esquema).

Respuesta (JSON): `{ "match_id": "<id del combate>", "weapon_side_A": "right", "weapon_side_B": "left" }`

`GET /matches/{match_id}` — combate configurado (solo lectura). El frontend guarda únicamente el
`match_id` del combate activo y lo valida con este endpoint al cargar la app. **404** si el combate
no existe o `match_id` no es uuid (`POST`/`PUT`/`DELETE` responden 404/405).
```json
{ "match_id": "uuid", "pista": "P1", "arbitro_id": "uuid", "arbitro": "Nombre Árbitro",
  "alias_A": "Rojo", "weapon_side_A": "right", "alias_B": "Verde", "weapon_side_B": "left" }
```
`weapon_side_A/B` usa los mismos valores que en `POST /matches/config` (`"right"` = diestro,
`"left"` = zurdo).

## 1.2 Catálogos para la pantalla de configuración (solo lectura)

`GET /eventos` — eventos de `sabre.evento`, del más reciente al más antiguo (fecha y nombre):
```json
[ { "id": "uuid", "nombre": "Piloto 1", "fecha": "2026-10-05", "lugar": null, "tipo": "piloto" } ]
```
`tipo` es `piloto`, `formativo` u `oficial`. El `id` se envía como `evento_id` de la sección 1.1.

`GET /usuarios?rol=arbitro` — usuarios de `sabre.usuario` ordenados por nombre:
```json
[ { "id": "uuid", "nombre": "Nombre Árbitro", "rol": "arbitro", "activo": true } ]
```
`rol` es opcional y admite `arbitro`, `operador` o `administrador` (**422** con otro valor); sin
`rol` devuelve todos. El `id` de un árbitro se envía como `arbitro_id` de la sección 1.1.

Ninguno de los dos crea ni modifica nada (`POST`/`PUT`/`DELETE` responden 404/405). Los datos se
siembran fuera de la API con `scripts/crear_sesion_validacion.py --evento "<nombre>" --fecha
YYYY-MM-DD --arbitro "<nombre>" --operador "<nombre>"`: crea el evento (tipo `piloto`) y los
usuarios árbitro y operador (roles del esquema), y muestra sus ids. Es idempotente por nombre
(reutiliza lo que ya existe) y responde con código 1 si el evento existe con un tipo distinto de
`piloto`.

## 1.3 Consultas de solo lectura (CU-07, CU-12)

Ninguno crea ni modifica nada (`POST`/`PUT`/`DELETE` responden 404/405). Sin autenticación
(RF-26 es COULD). Las clases usan siempre los nombres del modelo (sección 1).

`GET /revisiones?evento_id=&desde=&hasta=` — lista resumida, de la más reciente a la más
antigua. Los tres filtros son opcionales; `evento_id` es el evento del combate y
`desde`/`hasta` filtran `revision_var.abierta_en` (ISO 8601, inclusivos; sin zona horaria se
interpreta como UTC). **422** si `evento_id` no es uuid o una fecha no es ISO 8601.
```json
[ { "id": "uuid", "combate_id": "uuid", "abierta_en": "2026-10-01T15:00:00Z", "cerrada_en": null,
    "disponible": true, "clase": "AttackA", "confianza": 0.74,
    "decision": null, "clase_final": null } ]
```
`disponible`, `clase` y `confianza` son la sugerencia (null si aún no hay clasificación);
`decision` y `clase_final` son la decisión del árbitro (null sin veredicto; `clase_final`
también con `anular`).

`GET /revisiones/{id}` — detalle. **404** si la revisión no existe o `id` no es uuid.
```json
{ "id": "uuid", "combate_id": "uuid", "abierta_en": "...", "cerrada_en": null,
  "sugerencia": { "disponible": true, "motivo_no_disp": null, "clase": "AttackA",
                  "tirador": "A", "confianza": 0.74 },
  "probabilidades": { "AttackA": 0.74, "AttackB": 0.0, "ContrattackA": 0.16,
                      "ContrattackB": 0.0, "RiposteA": 0.10, "RiposteB": 0.0 },
  "decision": null, "clase_final": null, "registrado_en": null,
  "auditoria_seq": null, "auditoria_hash": null }
```
`sugerencia` es null si la revisión aún no tiene clasificación; con `disponible=false` trae
`motivo_no_disp` y `clase`/`tirador`/`confianza` en null. `tirador` es `A` o `B`. No incluye
la versión de modelo ni keypoints. `decision`, `clase_final`, `registrado_en`,
`auditoria_seq` y `auditoria_hash` son null hasta el veredicto (sección 7.1).

`GET /auditoria/verificar` — resultado de `sabre.fn_verificar_auditoria()` sin filtrar, con
200 en ambos casos: `{ "integra": true, "alteradas": [] }` o
`{ "integra": false, "alteradas": [ { "seq": 3, "esperado": "<hash>", "guardado": "<hash>" } ] }`.

`GET /modelo/activo` — `{ "nombre": "...", "num_clases": 6, "f1_macro_test": 0.4856,
"kappa_piloto": null }`; las métricas son las registradas en `modelo_version` (null si no
se registraron). **404** si no hay versión activa.

`GET /validaciones/{evento_id}/resumen` (L02, T-017, RNF-03, RNF-06) — resumen de la sesión de
validación de un evento, con el mismo contenido que el `resumen.json` de
`scripts/exportar_evidencia.py`. Se calcula desde PostgreSQL sobre las revisiones **con
veredicto** del evento; el JSONL de L01 no es la fuente (solo se concilia). Sin autenticación
(RF-26 es COULD, no hay regla de autorización documentada). **404** si el evento no existe,
**422** si `evento_id` no es uuid. Solo lectura.
```json
{ "evento_id": "uuid", "generado_en": "2026-09-29T20:00:00+00:00",
  "conciliacion": { "n_base": 10, "n_jsonl": 9, "jsonl_presente": true, "lineas_ilegibles": 0,
                    "faltantes_en_jsonl": ["<revision_id>"], "sobrantes_en_jsonl": [] },
  "integridad": { "fn_verificar_auditoria": "ok", "integra": true,
                  "registros_alterados": 0, "seq_alterados": [] },
  "por_validacion": {
    "V1": { "n_revisiones": 8, "disponibles": 7,
            "no_disponibles": { "n": 1, "por_motivo": { "pose_incompleta": 1, "confianza_baja": 0,
              "clase_fuera_mvp": 0, "timeout": 0, "sin_senal_favero": 0, "mensaje_invalido": 0 } },
            "latencia": { "n_total": 8, "n_disponibles": 7, "n_no_disponibles": 1,
                          "sin_medicion": 0, "mediana_ms": 48, "max_ms": 55, "p95_ms": null,
                          "p95_excede_umbral": true, "pct_le_60s": 87.5,
                          "umbral_ms": 60000, "cumple": false },
            "kappa": { "n": 6, "calculable": true, "kappa": 0.3333, "banda": "aceptable",
                       "umbral": 0.61, "cumple": false, "motivo": null },
            "concordancia": { "n": 6, "pct": 66.67 },
            "matriz_confusion": { "clases": ["AttackA", "AttackB", "ContrattackA", "ContrattackB",
                                             "RiposteA", "RiposteB"],
                                  "filas": "sistema", "columnas": "arbitro",
                                  "matriz": [[2, 0, 0, 0, 0, 1], "... 6 filas de 6"] } },
    "V2": { "...": "misma estructura" } },
  "modelo": { "nota": "Referencia offline: F1 macro se mide sobre el test set, no en la sesión.",
              "activo": { "nombre": "...", "num_clases": 6, "f1_macro_test": 0.4986,
                          "kappa_piloto": null },
              "modelos_en_revisiones": ["..."], "tabla_m01": "## Tabla resumen — ...\n..." } }
```
Definiciones (solo las de `docs_claude/protocolo_validacion.md`):
- **V1/V2**: `tocado.fuente` = `simulado` / `favero`. Las métricas van separadas; no hay total.
- **Disponibilidad y motivos**: `clasificacion.disponible` y `motivo_no_disp` (los seis valores
  del esquema, siempre presentes aunque valgan 0).
- **Latencia**: `clasificacion.latencia_ms` (la misma de L01), que mide desde que se envía el
  clip hasta que la sugerencia está disponible (D-08, RNF-04). Una revisión no disponible no
  tiene sugerencia, así que su `latencia_ms` no cuenta como latencia, pero tampoco se oculta:
  - `mediana_ms` y `max_ms`: solo sobre las revisiones **disponibles**.
  - `pct_le_60s` y `p95_ms`: sobre **todas** las revisiones; una no disponible cuenta como
    > 60 s. `p95_ms` usa el rango más cercano (el elemento ⌈0.95·n⌉-ésimo). Si más del 5 % no
    está disponible, el p95 cae en una no disponible: `p95_ms` es null y `p95_excede_umbral`
    es true (el resumen.md lo muestra como "> 60 s"). Sin revisiones, ambos son null.
  - `cumple` = p95 ≤ 60000 calculado así (RNF-04), es decir, `not p95_excede_umbral`.
  - Denominador: `n_total`, `n_disponibles` y `n_no_disponibles`. Una disponible sin
    `latencia_ms` registrada no se puede medir: queda fuera de todos los cálculos y se cuenta
    en `sin_medicion`.
- **κ de Cohen** sistema-árbitro (`clase_sugerida` vs. `clase_final_arbitro`) sobre las
  revisiones disponibles y no anuladas. `banda` es la de Landis & Koch (< 0 pobre; 0–0.20
  leve; 0.21–0.40 aceptable; 0.41–0.60 moderada; 0.61–0.80 sustancial; 0.81–1.00 casi
  perfecta) y `cumple` es κ ≥ 0.61 (RNF-06). Si N < 2 o hay una sola clase en ambos lados,
  `calculable` es false, `kappa`/`banda`/`cumple` son null y `motivo` lo explica (nunca NaN ni 0).
- **Concordancia** (% de `clase_sugerida == clase_final_arbitro`) y **matriz de confusión** 6 × 6
  (sistema en filas, árbitro en columnas, orden de `clases`) usan el mismo conjunto que κ.
- **Conciliación**: revisiones con veredicto en la base (`n_base`) contra las líneas del JSONL
  de L01 (`n_jsonl`); `faltantes_en_jsonl` y `sobrantes_en_jsonl` son `revision_id` ordenados.
  El JSONL no se corrige.
- **Integridad**: resultado de `sabre.fn_verificar_auditoria()` sobre la cadena completa.
- **Modelo**: métricas registradas de la versión activa (`modelo_version`) y la tabla resumen de
  M01 copiada de `M01_EXPERIMENT_LOG` (null si no está configurado o la sección no es única).
  F1 no se recalcula en la sesión. No incluye delta de κ inter-árbitro: su protocolo no está
  definido.

`GET /health` — `{ "fog": "ok", "redis": "ok", "postgres": "ok" }` (`"error"` por
componente). Redis (PING) y PostgreSQL (`SELECT 1`) tienen 2 s de tiempo límite. **200** si
todo está `ok`; **503** con el mismo cuerpo si alguno falla.

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

- `weapon_side_A/B`: `"right"` o `"left"`. Brazo armado de cada tirador. **Obligatorios,
  sin valor por defecto**: 41/104 clips de test tienen al menos un tirador zurdo
  (contexto_sabre.md sección 8), así que no se analiza un clip sin brazo declarado. Si falta
  alguno, `422`. Tipado como enum cerrado (`Literal["right", "left"]`) en todos los esquemas
  (DEF-13): cualquier otro valor también responde `422` antes de llegar al dominio. Si
  `match_id` ya fue configurado con `POST /matches/config`, se reutiliza esa sesión y su
  brazo armado guardado.
- `match_id`: identificador que el front debe reutilizar al reportar la luz Favero
  (sección 3). Si no se envía, Fog genera uno y lo devuelve en la respuesta. Este flujo
  WebRTC no persiste en la base.

Respuesta (JSON):
```json
{ "sdp": "<SDP answer>", "type": "answer", "match_id": "...", "revision_id": "..." }
```

`revision_id` identifica la sesión: es el que se usa para conectar el WebSocket de veredicto
(sección 7). Este flujo no abre `revision_var`, así que ese `revision_id` es un uuid generado
por Fog para esta oferta, sin fila en la base ni veredicto registrable.

El front debe abrir un `RTCPeerConnection`, agregar **una sola pista de video** (el clip
subido, vía `captureStream()` de un `<video>` o equivalente en RN), generar la oferta,
hacer `POST` a este endpoint, y aplicar la respuesta como `setRemoteDescription`.

Cuando el clip termina de reproducirse y la pista de video llega a su fin (evento
`ended` del track), Fog interpreta eso como "fin del clip" y dispara el procesamiento.
No hace falta cerrar el `RTCPeerConnection` explícitamente, pero es buena práctica
hacerlo tras recibir el veredicto.

## 3. Edge → Fog: señal de luz Favero

`POST /webrtc/{match_id}/luz`

El modelo desplegado (`lstm_6class`) usa la luz Favero como filtro sobre los
logits antes del softmax (equivalente a `apply_favero_logit_mask` de
dataset/lstm_6class/evaluate.py) y, si `luz_size > 0` en el `run_config.json`
del checkpoint activo, también como entrada real del modelo (concatenada
después del pooling, antes de la capa final) — ver
`cloud/infrastructure/classifier/lstm6class_adapter.py`. El checkpoint
desplegado actualmente usa `luz_size=0` (ver sección 8), así que solo se usa
como filtro. El front debe reportar la luz en cuanto el clip termina de reproducirse,
**antes** de que Fog dispare la clasificación; si no llega dentro de
`FAVERO_LUZ_TIMEOUT_S` (2s por defecto, configurable por entorno), Fog continúa sin
luz (`has_luz_A = has_luz_B = false`).

Body (JSON):
```json
{ "has_luz_A": true, "has_luz_B": false }
```

Respuesta (JSON):
```json
{ "match_id": "...", "has_luz_A": true, "has_luz_B": false }
```

Aplica a la sesión WebRTC más reciente del combate (`POST /webrtc/offer`). `404` si el
combate no tiene ninguna sesión en curso.

## 4. Edge → Fog: carga de clip sin WebRTC (CU-02, CU-03, CU-05, CU-06)

`POST /matches/{match_id}/clip` (multipart/form-data)

Alternativa a `POST /webrtc/offer` + sección 3: sube un clip ya grabado
en un solo request, junto con la señal de luz Favero simulada (D-12). A diferencia del
flujo WebRTC, la respuesta es **síncrona**: corre pose+tracking+features,
publica en Redis y espera el veredicto de Cloud (con timeout,
`CLIP_UPLOAD_VERDICT_TIMEOUT_S`, 30 s por defecto) antes de responder. Cada llamada abre
una revisión nueva del combate y devuelve su `revision_id`.

Campos del form (multipart):

| campo | tipo | descripción |
|---|---|---|
| `file` | file | clip de video (MP4/MOV) |
| `t_tocado_ms` | int | **obligatorio.** Instante del tocado simulado en ms desde el inicio del clip (RF-02), entre 0 y la duración del clip, ambos incluidos (**422** si no). No se usa para recortar el clip |
| `has_luz_A` | bool | `true` si se encendió la luz Favero de A |
| `has_luz_B` | bool | idem para B. **Al menos una de las dos luces debe estar encendida** (CU-03 flujo 2a; `tocado` lo exige con `CHECK (luz_a OR luz_b)`) |
| `luz_frame_a` | int | **[OBSOLETO]** alias de `has_luz_A`: índice de frame (0-based) en que se prendió la luz de A. Solo se usa si `has_luz_A` y `has_luz_B` vienen ambos ausentes |
| `luz_frame_b` | int | **[OBSOLETO]** alias de `has_luz_B`, misma regla que `luz_frame_a` |

`has_luz_A/B` es la forma vigente (DEF-14): antes `luz_frame_a/b` se
reducían a un booleano (`is not None`) y se perdía la posibilidad de
reportar el instante del tocado por separado (RF-02 pide luz A, luz B e
instante). `luz_frame_a/b` se mantiene solo como alias obsoleto para no
romper clientes viejos.

**Errores (antes de procesar el video):**

| código | causa |
|---|---|
| `404` | el combate no fue creado (sección 1.1) o `match_id` no es un uuid |
| `422` | falta `t_tocado_ms`, ninguna luz encendida, o `t_tocado_ms` fuera de `[0, duración del clip]` |
| `503` | no hay versión de modelo activa (`scripts/registrar_modelo.py`) |

Un combate admite N clips: ya no hay `409` por segundo clip.

**Validación del archivo (DEF-13):**

- Si el archivo no abre como video (`cv2.VideoCapture` falla), no informa fps válidos o tiene
  menos de `MIN_FRAMES` frames (3 por defecto): `400` con `detail`.
- Si el archivo pesa más de `CLIP_MAX_MB` (200 MB por defecto,
  configurable por entorno): `413` con `detail`.
- Si `t_tocado_ms` es negativo o mayor que la duración del clip
  (`round(frames/fps·1000)`): `422` con `detail`. La comprobación ocurre antes de guardar el
  clip y de abrir la revisión, así que no queda clip, tocado ni mensaje en Redis.

**Persistencia (D03, `docs_claude/sabre_ai_schema.sql`):**

1. Al recibir un clip válido, en una transacción: `clip` (`origen='carga'`, `camara='unica'`,
   `uri` + `sha256` del archivo en `STORAGE_DIR`, `fps`, `ancho_px`, `alto_px`,
   `duracion_ms = round(frames/fps·1000)`), `tocado` (`fuente='simulado'`, `luz_a/b`,
   `t_tocado_ms`), `tocado_clip` (`frame_tocado = round(t_tocado_ms/1000·fps)`) y
   `revision_var` (`aceptada=true`, `arbitro_id` = árbitro del combate). No se registra qué
   tirador pidió la revisión (D-04).
2. Con el veredicto de Cloud, o con el "no disponible" (pose incompleta, timeout, o
   `disponible=false` de Cloud), se registra `clasificacion` contra el **modelo activo**
   (`modelo_version.activo`): probabilidades post filtro Favero, keypoints crudos de la
   `TrackedSequence` en `.npz` (`keypoints_uri` + `keypoints_sha256`; por tirador
   `{a,b}_xy`, `_conf`, `_box`, `_detected`, más `frame_w/h`, `locked`, `lock_frame`) y
   `latencia_ms` desde la recepción del clip hasta la sugerencia (o hasta el "no disponible").
   La API y el dominio usan los nombres del modelo; solo el adaptador de persistencia los
   traduce a los del esquema al guardar (`AttackA` → `AtaqueA`, `ContrattackA` →
   `ContraataqueA`, `RiposteA` → `RiposteA`; igual en las llaves de `probabilidades`) y de
   vuelta al leer. `latencia_inferencia_ms` (sección 6) llega a Fog pero **no se persiste**:
   `clasificacion` no tiene columna para ella. Respeta `UNIQUE (tocado_id, modelo_version_id)` (un tocado por clip, así
   que cada revisión tiene su propia clasificación). La revisión queda abierta
   (`cerrada_en` nulo) hasta el veredicto de la sección 7.1.

Respuesta (JSON):
```json
{
  "match_id": "...",
  "revision_id": "...",
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

`disponible=false` cubre tres casos (DEF-08, DEF-09), distinguidos por `motivo`
(mismos valores de `clasificacion.motivo_no_disp` que la sección 7):

- **Pose incompleta** (`motivo="pose_incompleta"`, `timed_out=false`):
  Fog no pudo extraer features válidas (sin lock A/B, o clip por debajo
  de `MIN_FRAMES`) y nunca publicó en Redis — responde de inmediato, sin
  esperar a Cloud. `fencer`/`action`/`confidence` quedan en `null`.
- **Timeout de Cloud** (`motivo="timeout"`, `timed_out=true`): Fog sí
  publicó features pero Cloud no respondió dentro del timeout
  configurado. `fencer`/`action`/`confidence` quedan en `null`.
- **Cloud no disponible** (`motivo="mensaje_invalido"`, `timed_out=false`): Cloud publicó
  `disponible=false` (sección 6).

## 5. Fog → Cloud: `fog:features` (Redis Stream)

Cada clip procesado por Fog (cada revisión) genera **una sola entrada** en el stream:

| campo           | tipo  | descripción                                                                         |
|-----------------|-------|-------------------------------------------------------------------------------------|
| `match_id`      | str   | id del combate                                                                      |
| `revision_id`   | str   | id de la revisión que origina el clip. **Obligatorio.** Cloud responde en `cloud:verdicts:{revision_id}` |
| `shape`         | str   | `"T,192"` (T = frames reales del clip)                                              |
| `dtype`         | str   |  `"float32"`                                                                        |
| `features`      | bytes | `array.tobytes()` — array `(T,192)` ya en el orden A(96)+B(96), estandarizado con `feature_stats.npz`, con el recorte y la ablación del perfil `FEATURE_PREPROCESSING_PROFILE` de la versión de modelo (igual que en entrenamiento) y con cm_vel_x/y y body_speed relativos al rival (`0.5·(abs_A − abs_B)`, DEF-27)                                                                                           |
| `has_luz_A`     | str   | `"true"`/`"false"`, lo reportado en la sección 3 (o `"false"` si no llegó a tiempo) |
| `has_luz_B`     | str   | idem para B                                                                         |
| `weapon_side_A` | str   | reenviado tal cual                                                                  |
| `weapon_side_B` | str   | reenviado tal cual                                                                  |                
| `ts`            | str   | timestamp ISO de cuándo Fog terminó de extraer                                      |    

Cloud consume con un grupo de consumidores `cloud_workers` (1 worker por pista, según
diagrama). Reconstrucción: `np.frombuffer(features, dtype=dtype).reshape(shape)`.

**Validación y tolerancia a fallos (DEF-09).** `RedisFeatureConsumer` valida cada entrada
antes de reconstruir el array: campos obligatorios presentes (`match_id`, `revision_id`,
`shape`, `dtype`, `features`, `weapon_side_A`, `weapon_side_B`), `dtype == "float32"`,
`shape == "T,192"` con `T >= 1`, y `len(features) == T * 192 * 4` bytes. Una entrada que
no cumple el contrato:

1. Se loguea (una línea, con el motivo).
2. Se publica un veredicto `disponible=false` en `cloud:verdicts:{revision_id}` con
   `motivo_no_disp="mensaje_invalido"` (si el propio `revision_id` no era legible, no hay
   stream donde publicar y no se publica veredicto).
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

## 6. Cloud → Fog: `cloud:verdicts:{revision_id}` (Redis Stream)

Un stream por revisión y una entrada por veredicto; dos clips del mismo combate usan streams
distintos. `disponible` distingue dos formas (igual que
`clasificacion.disponible` en `sabre_ai_schema.sql`):

**`disponible=true`:**

| campo | tipo | descripción |
|---|---|---|
| `revision_id` | str | la revisión del stream (misma clave que `fog:features`) |
| `match_id` | str | id del combate, tal como llegó en `fog:features` |
| `disponible` | str | `"true"` |
| `action_class` | str | una de `AttackA, AttackB, ContrattackA, ContrattackB, RiposteA, RiposteB` |
| `confidence` | str | probabilidad softmax de la clase ganadora (post filtro de luz), `"0.0"`-`"1.0"` |
| `fencer` | str | `"ROJ"` si la clase termina en `A`, `"VER"` si termina en `B` (mapeo fijo v1) |
| `probs` | str | JSON `{"AttackA": 0.61, ...}` — softmax completo, post filtro Favero (auditoría, RF-22) |
| `latencia_inferencia_ms` | str | duración de `ActionClassifierPort.classify` en ms (auditoría, RNF-04) |
| `modelo` | str | `"lstm_6class/<run_id>/<archivo>"`, derivado de `MODEL_RUN_DIR` (ver `LSTM6ClassAdapter.model_version_name`) |
| `ts` | str | timestamp ISO |

**`disponible=false`** (DEF-09, mensaje de `fog:features` inválido — ver sección 5):

| campo | tipo | descripción |
|---|---|---|
| `revision_id` | str | la revisión del stream |
| `match_id` | str | id del combate; se omite si el mensaje inválido no lo traía |
| `disponible` | str | `"false"` |
| `motivo_no_disp` | str | uno de `clasificacion.motivo_no_disp` (`sabre_ai_schema.sql`); hoy solo `"mensaje_invalido"` |
| `ts` | str | timestamp ISO |

`action_class` ya viene resuelto por el filtro Favero de `LSTM6ClassAdapter`
(sobre los logits, antes del softmax): si exactamente una luz se encendió, el
lado imposible queda en probabilidad exactamente 0. Si ambas luces o ninguna
se encendieron (caso ambiguo, D-06), el veredicto crudo del LSTM se publica
sin cambios. `ArbitrationPolicyPort` (implementación activa:
`NullArbitrationPolicy`) no modifica el veredicto todavía — queda reservado
para las reglas de prioridad FIE (t.101-t.106), ver sección 8.

`RedisVerdictSubscriber` (Fog) lee `disponible`: con `"false"` entrega un "no disponible"
con `motivo_no_disp` (se reenvía por el WebSocket de la sección 7 y se registra en
`clasificacion`); con `"true"` conserva además `probs`, `latencia_inferencia_ms` y `modelo`
para la auditoría (campos opcionales: si faltan, se guardan sin ellos).

Fog mantiene una tarea de fondo por revisión activa (`revision_id`) que hace `XREAD`
bloqueante sobre este stream y reenvía el resultado por WebSocket en cuanto llega.

## 7. Fog → Front: WebSocket de veredicto

`GET /ws/veredicto/{revision_id}`: el WebSocket se identifica por revisión, con el
`revision_id` que devuelven `POST /matches/{match_id}/clip` o `POST /webrtc/offer`. Si la
revisión no tiene una sesión activa en Fog (nunca existió, o ya se liberó pasado
`SESSION_TTL_S` desde que se entregó su resultado), el handshake se rechaza con **404** (si el
servidor no soporta respuestas de rechazo, se cierra con código 1008 antes de aceptar). Dos
revisiones del mismo combate tienen WebSockets independientes.

Mensaje que Fog envía cuando el veredicto está listo:
```json
{
  "type": "veredicto",
  "match_id": "...",
  "revision_id": "...",
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
  "revision_id": "...",
  "motivo": "pose_incompleta"
}
```

`motivo` es uno de `clasificacion.motivo_no_disp`
(`sabre_ai_schema.sql`): `pose_incompleta`, `confianza_baja`,
`clase_fuera_mvp`, `timeout`, `sin_senal_favero`, `mensaje_invalido`. Por este WebSocket
Fog produce `pose_incompleta` (los dos únicos errores que devuelve
`FeatureExtractorPort.extract` — sin lock A/B, o secuencia bajo
`min_frames` — mapean a ese motivo) y, en la carga de clip (sección 4), `timeout` cuando
Cloud no responde a tiempo; `confianza_baja` y
`clase_fuera_mvp` son responsabilidad de Cloud y no están implementados
todavía (el umbral de confianza no está documentado). `mensaje_invalido`
(DEF-09) lo produce Cloud cuando una entrada de `fog:features` no respeta
el contrato — llega a Fog vía `cloud:verdicts:{revision_id}` (sección 6) y se reenvía
por este WebSocket como `no_disponible`.

Carlos debe traducir `action` (taxonomía interna en inglés, 6 clases) a las etiquetas en
español que ya usa el front (`actionMapper.ts`, `translateAction`). Esa traducción
**no** vive en el backend porque depende de decisiones de UI/copy que son de Carlos.
Tabla vigente (implementada en `SaberAISoftware/src/application/mappers/actionMapper.ts`):

| `action` (backend) | en español |
|---|---|
| `AttackA` / `AttackB` | "ATAQUE" |
| `ContrattackA` / `ContrattackB` | "CONTRAATAQUE" |
| `RiposteA` / `RiposteB` | "RIPOSTE" |

El tirador se muestra por separado, derivado del sufijo de `action` (`A`/`B`) y de
`fencer` (`ROJ`/`VER`): `formatFencerLabel` arma la etiqueta `"A · ROJ"` / `"B · VER"`.
Esto reemplaza el nombre de atleta simulado que mostraba antes `ActionPanel` (regla 8,
sin datos simulados): no hay todavía una fuente real del nombre del tirador, así que se
muestra el dato real disponible (lado + color) en vez de inventar uno.

`confidence` ya viene en escala 0–1; el front la muestra como % (`mock.ts` usa enteros
0–100, ej. `94`).

## 7.1 Registrar veredicto final (CU-10, CU-11, F-033, F-034, RF-20, RF-21, RF-22)

`POST /revisiones/{revision_id}/veredicto`

Registra la decisión del árbitro sobre **una revisión** (la que devolvió su clip; un combate
admite N y cada una tiene su veredicto). No existe veredicto por combate ni la regla de "la
revisión más reciente": `POST /matches/{match_id}/veredicto` fue eliminado. El sistema solo
sugiere: nunca asigna el punto ni cierra la revisión sin esta decisión (RNF-01, RF-21).

Body (JSON):
```json
{ "decision": "cambiar", "clase_final": "ContrattackB", "arbitro_id": "uuid" }
```

| campo | descripción |
|---|---|
| `decision` | `"mantener"`, `"cambiar"` o `"anular"` (acción simultánea, FIE t.106). Describe la relación con la decisión original del árbitro en pista. Cualquier otro valor: 422. El frontend los muestra como "Mantiene", "Cambia" y "Anula" (Historial). Con `"mantener"` la interfaz envía la clase sugerida como `clase_final`; con `"cambiar"`, la clase que elige el árbitro entre las 6 |
| `clase_final` | la decisión final declarada, siempre. **Obligatoria con `"mantener"` y `"cambiar"`** (también si la clasificación no estuvo disponible) y **prohibida con `"anular"`** (422 en ambos casos). Valores de la taxonomía del modelo: `AttackA`, `AttackB`, `ContrattackA`, `ContrattackB`, `RiposteA`, `RiposteB` (un nombre del esquema como `AtaqueA` es inválido) |
| `arbitro_id` | usuario existente en `sabre.usuario` |

En **una sola transacción**: inserta `veredicto`, cierra `revision_var` (`cerrada_en` =
`veredicto.registrado_en`) e inserta `registro_auditoria` con el snapshot JSON
`{revision, tocado, clasificacion, veredicto, modelo, reglamento, vocabulario}` (`reglamento` =
el de la versión de modelo, `FIE 2026`; `vocabulario` es siempre `"modelo"`: las clases del
snapshot llevan los nombres del modelo). Si
cualquier paso falla no queda nada. El hash y el encadenamiento los calcula la base;
`sabre.fn_verificar_auditoria()` devuelve las filas alteradas (ninguna si la cadena es
íntegra). Veredicto y auditoría son de solo adición (RNF-05): un `UPDATE`/`DELETE` falla con
"Los registros de auditoría no pueden modificarse".

Respuesta (JSON): `match_id` (el combate de la revisión), `revision_id`, `veredicto_id`,
`decision`, `clase_final`, `arbitro_id`, `registrado_en`, `cerrada_en`, `auditoria_seq`,
`auditoria_hash`.

| código | causa |
|---|---|
| `404` | la revisión (o un `revision_id` que no es uuid) o el árbitro no existen |
| `409` | la revisión ya tiene veredicto; o aún no tiene clasificación registrada (sin ella el registro no podría guardar la versión de modelo, RF-22) |
| `422` | `"mantener"` o `"cambiar"` sin `clase_final`; `"anular"` con `clase_final`; `clase_final` fuera de la taxonomía del modelo |

**Etiqueta de reentrenamiento.** La vista `sabre.v_muestras_confirmadas` (migración `0003`)
toma como etiqueta siempre `veredicto.clase_final`, excluyendo `anular`, sin depender de si
el árbitro mantuvo o cambió la acción; `clase_sugerida` es la de la clasificación. La
concordancia sistema-árbitro es `clase_sugerida == clase_final`.

Al cerrarse la revisión, Fog agrega una línea al log de evidencia
`EVIDENCE_DIR/<evento_id>.jsonl` (logger `sabre.evidencia`, L01), armada con lo
ya registrado en la base. Campos, en este orden: `ts` (`veredicto.registrado_en`),
`evento_id`, `revision_id`, `validacion` (`V1` si `tocado.fuente = simulado`,
`V2` si `favero`), `modelo`, `luz_A`, `luz_B`, `disponible`, `motivo`,
`clase_sugerida`, `confianza`, `latencia_ms`, `decision`, `clase_final_arbitro`,
`concordancia` (`clase_sugerida == clase_final_arbitro`; `null` si no disponible
o anulada) y `hash_auditoria`. Las clases usan los nombres del modelo. Si la
escritura falla, el veredicto ya registrado no se revierte; el error queda en el
log técnico.

## 8. Notas y desviaciones respecto a los diagramas de arquitectura

- **Modelo desplegado**: `dataset/lstm_6class/checkpoints/<run_id>/best_model.pt`
  (`run_id` fijado por `MODEL_RUN_DIR`, sin valor por defecto — DEF-15) — 6 clases
  (`AttackA, AttackB, ContrattackA, ContrattackB, RiposteA, RiposteB`, D-06), 192
  features (96 por tirador, incluye bloque biomecánico Fase B) y pooling por atención
  aditiva. Los hiperparámetros (incluido `luz_size`, que decide si la luz Favero
  también es input real del modelo) se leen de `run_config.json` dentro de
  `MODEL_RUN_DIR`, nunca fijos en código — el checkpoint activo puede cambiar tras un
  diagnóstico en curso (docs_claude/contexto_sabre.md sección 8). Reemplaza al pipeline
  de 4 clases (DEF-03 resuelto), que queda descartado.
- **RNF-03 no se cumple con el checkpoint vigente**: F1 macro ≥ 0.65 requerido; media
  documentada de la serie baseline 0.4856 ± 0.0322 (N=10, ver
  docs_claude/contexto_sabre.md sección 8). Decisión pendiente con el asesor.
- **Tracker**: BoT-SORT, una instancia por sesión de clip (`BOTSORT` de Ultralytics, ver
  `fog/infrastructure/pose/yolo_pose_adapter.py`), no ByteTrack ni DeepSORT como decían el
  diagrama de capas y versiones anteriores de este contrato. `dataset/05_extract_features.py`
  usó `model.track(..., persist=True)` con el tracker por defecto de la versión de Ultralytics
  instalada entonces, sin registro de versión: que coincida con BoT-SORT no está confirmado.
- **Detector de pose**: YOLOv8x-pose (no YOLOv8n-pose como indica el diagrama), decisión
  confirmada por Nicolas para mantener fidelidad con el entrenamiento. Sin requisito de
  tiempo real en v1, el costo de latencia es aceptable.
- **Scoring Híbrido FIE**: no implementado en v1. El veredicto que llega al front ya
  tiene el filtro Favero aplicado dentro de `LSTM6ClassAdapter` (sección 6), no la
  salida cruda del LSTM sin filtrar. `ArbitrationPolicyPort` (implementación activa:
  `NullArbitrationPolicy`) no aplica ninguna regla propia todavía. Las reglas FIE
  completas (t.101-t.106, prioridad de ataque/cobertura/etc.) quedan para una versión
  posterior — el puerto está diseñado para admitir esa implementación más rica sin
  tocar el resto del sistema.
- **Luz Favero**: sin integración física con el aparato real. El front debe simular/
  capturar la señal y reportarla vía `POST /webrtc/{match_id}/luz` (sección 3).
- **Mapeo A/B ↔ ROJ/VER**: fijo (`A=ROJ`, `B=VER`) para v1, confirmado por Nicolas. No
  configurable por combate todavía.
- **Persistencia (D03)**: requiere `DATABASE_URL`, `STORAGE_DIR`, filas de `usuario` y
  `evento` sembradas fuera de la API con `scripts/crear_sesion_validacion.py` (no hay login,
  RF-26 es COULD; sección 1.2) y una versión de modelo activa
  (`scripts/registrar_modelo.py`). La base del compose publica el puerto
  `POSTGRES_HOST_PORT` (5433 por defecto, solo loopback; ver `GUIA_EJECUCION.md`). `tocado.registrado_por` queda nulo (no hay
  operador identificado). La transacción única del veredicto usa
  `fog/ports/unidad_de_trabajo.py`.

## 8.1 Almacenamiento y evidencia en disco

Archivos que Fog escribe fuera de la base (rutas fijadas por `STORAGE_DIR` y `EVIDENCE_DIR`,
`GUIA_EJECUCION.md` sección 3). La base solo guarda URI y hash.

| Ruta | Contenido | Escribe |
|---|---|---|
| `STORAGE_DIR/clips/<sha[:2]>/<sha>.<ext>` | clip subido; el nombre es el SHA-256 del archivo, así que el mismo clip no se duplica. `clip.uri` = `local://clips/...`, `clip.sha256` | `POST /matches/{match_id}/clip` |
| `STORAGE_DIR/keypoints/<sha[:2]>/<sha>.npz` | keypoints crudos comprimidos (`{a,b}_xy`, `_conf`, `_box`, `_detected`, `frame_w/h`, `locked`, `lock_frame`); `clasificacion.keypoints_uri` y `keypoints_sha256` | al registrar la clasificación |
| `EVIDENCE_DIR/<evento_id>.jsonl` | una línea por revisión cerrada (campos de la sección 7.1, L01); solo adición, no se corrige | cierre de la revisión |
| `EVIDENCE_DIR/<evento_id>/resumen.json`, `revisiones.csv`, `resumen.md` | exportación de la sesión de validación (L02); se sobrescriben al reejecutar | `scripts/exportar_evidencia.py --evento <id>` |

`EVIDENCE_DIR` es obligatorio al arrancar Fog; `STORAGE_DIR` y `DATABASE_URL` se exigen al
primer uso (carga de clip, catálogos, consultas y `/health`): con Fog arrancado sin
`DATABASE_URL`, esas rutas responden 500 (`/health` incluido, no 503) con
"Falta la variable de entorno DATABASE_URL" en el log.
La evidencia de la sesión no incluye nombres de atletas: se usa el alias de `tirador`. La
evidencia del modelo va dentro de `resumen.json` (`modelo`), no en una carpeta aparte.

## 9. Uso desde el frontend y pendientes

Estado de `SaberAISoftware` (Validación 1). Solo usa REST; **no** abre WebRTC ni el WebSocket
de veredicto ni reporta la luz por `POST /webrtc/{match_id}/luz` (esas secciones quedan como
contrato del flujo WebRTC, fuera de la Validación 1):

| Pantalla / acción | Endpoint |
|---|---|
| Configurar combate (CU-01) | `GET /eventos`, `GET /usuarios?rol=arbitro`, `POST /matches/config`; al cargar la app valida el combate con `GET /matches/{match_id}` |
| Subir clip con luces e instante del tocado (CU-02, CU-03) | `POST /matches/{match_id}/clip` (la respuesta trae la sugerencia o "no disponible") |
| Veredicto (CU-10) | `POST /revisiones/{revision_id}/veredicto` (`clase_final` obligatoria con mantener y cambiar; sin ella con anular) |
| Historial y detalle (CU-12) | `GET /revisiones?evento_id=`, `GET /revisiones/{id}` |
| Resumen y exportación de la validación (L02) | `GET /validaciones/{evento_id}/resumen` |
| Estado del sistema y modelo | `GET /health`, `GET /modelo/activo` |

La traducción de `action`/`fencer` a las etiquetas de la interfaz está en la sección 7.

Pendiente (Validación 2, fuera de esta entrega): captura de las dos cámaras y señal Favero
real; consumo del WebSocket de veredicto si se retoma el flujo WebRTC.
