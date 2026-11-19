# Contrato de integración — Edge (front) ↔ Fog ↔ Cloud

Versión v1 (carga manual de clips de acción; un combate admite N revisiones). Sigue
`arquitectura_diagramas.html` con dos adaptaciones documentadas en la sección final.

## 0. Autenticación (DEPLOY05)

Fog tiene un **usuario maestro único**. Toda ruta exige `Authorization: Bearer <token>`,
salvo `GET /health` y `POST /auth/login`. Sin token, con token vencido o con firma alterada
responde **401** (`{"detail": "No autenticado"}`, cabecera `WWW-Authenticate: Bearer`).
Las secciones siguientes no repiten el encabezado.

### POST /auth/login

Cuerpo: `{"usuario": "...", "password": "..."}` (`usuario` ≤ 128 y `password` ≤ 256
caracteres; más es **422**). Respuesta **200**:
```json
{"access_token": "<jwt>", "expires_in": 28800}
```
JWT HS256 firmado con `AUTH_JWT_SECRET`, claims `sub`, `iat`, `exp` (8 h), `jti`.

| Código | Cuándo |
|---|---|
| 200 | Credenciales correctas. |
| 401 | Usuario o contraseña incorrectos. Mismo cuerpo en ambos casos: `{"detail": "Credenciales inválidas"}`. |
| 429 | La IP acumuló 5 fallos en 15 min y queda bloqueada 15 min (también si la contraseña es correcta). Cabecera `Retry-After` en segundos. |
| 503 | Redis (contador de intentos) no responde. |

La IP del bloqueo es la última entrada de `X-Forwarded-For` solo cuando Fog tiene
`PROXY_SHARED_TOKEN` (la petición ya pasó por el proxy de confianza); en otro caso es la IP
del socket.

### GET /auth/me

Con token válido responde **200** `{"usuario": "<sub>"}`; el frontend lo usa para validar la
sesión. **401** si el token ya no sirve.

### Cierre de sesión y limitación

El logout lo hace el cliente borrando el token. **No hay lista de revocación**: un token
robado sigue siendo válido hasta que vence (8 h). Se acepta como limitación del MVP; la
mitigación es la vida corta del token y rotar `AUTH_JWT_SECRET` (invalida todos los tokens).

### Otros códigos de seguridad

| Código | Cuándo |
|---|---|
| 403 | Con `PROXY_SHARED_TOKEN` definido, la petición no trae `X-Proxy-Token` igual a ese valor (aplica a todas las rutas, incluidas `/health` y `/auth/login`). Cuerpo `{"detail": "Acceso denegado"}`. |
| 401 | Falta de token, token vencido o alterado (toda ruta salvo las públicas). |
| 429 | Bloqueo por intentos de login (ver arriba). |

### Endurecimiento

- **CORS** cerrado: solo los orígenes de `CORS_ORIGINS` (sin comodines; vacío en el despliegue
  remoto, donde el navegador usa el mismo origen), métodos `GET, POST, OPTIONS`, cabeceras
  `Authorization` y `Content-Type`, sin credenciales.
- **Cabeceras** en toda respuesta: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, `Cache-Control: no-store`.
- Con `ENTORNO=remoto`: `/docs`, `/redoc` y `/openapi.json` responden **404** y
  `/ws/veredicto/{revision_id}` no existe (WebRTC no se usa en la Validación 1).
- `/health` solo devuelve `ok` o `error` por componente (`fog`, `redis`, `postgres`).
- **WebSocket — solo local, temporal.** En remoto (`ENTORNO=remoto`) la ruta
  `/ws/veredicto/{revision_id}` no existe. En local el navegador no puede enviar
  `Authorization`, así que se acepta el token en la query
  (`/ws/veredicto/{revision_id}?token=<jwt>`); sin token válido se cierra con 1008 antes de
  aceptar. Reemplazarlo por autenticación por primer mensaje queda pendiente y sin release asignado (ver
  `Tesis/prompts/FUTURO/PENDIENTE_V2_websocket_camara.md`); no usar `?token=` en ningún entorno
  accesible desde internet.

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
  "alias_B": "Verde",
  "weapon_side_B": "left"
}
```

| campo | obligatorio | notas |
|---|---|---|
| `evento_id` | sí | debe existir en `sabre.evento` (404 si no) |
| `pista` | sí | texto no vacío |
| `arbitro_id` | sí | debe existir en `sabre.usuario` (404 si no). Se guarda también como `configurado_por` (el login es de un usuario maestro único, sección 0: no identifica al árbitro ni al operador) |
| `alias_A/B` | no | alias del tirador (minimización de datos). Vacío u omitido: `"Tirador A"` / `"Tirador B"` |
| `weapon_side_A/B` | **sí, sin valor por defecto** | `"right"` → `diestro`, `"left"` → `zurdo`. Se guarda en `combate.brazo_a/b` y `tirador.brazo_habitual`. Sin él: 422 y no se crea nada |

Menor de edad y consentimiento no se reciben (V01b): el backend guarda ambos tiradores con
`es_menor = true`, `consentimiento_firmado = false`, `consentimiento_fecha = NULL` y
`firmante = NULL`, valor conservador: en V1 los consentimientos se gestionan en papel fuera del
sistema y el sistema no registra uno que no existe. Los campos antiguos (`es_menor_*`, `consentimiento_*`, `firmante_*`) se ignoran si llegan.

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

Ninguno de los dos crea ni modifica nada (`POST`/`PUT`/`DELETE` responden 404/405). Los datos iniciales los
precarga la migración Alembic 0005 (V01), idempotente por nombre: eventos "Evento de prueba"
(`formativo`, ensayos) y "Validación 1" (`piloto`, sesión real), y usuarios "Árbitro de prueba"
(`arbitro`) y "Operador de prueba" (`operador`). Para uso técnico, `scripts/crear_sesion_validacion.py
--evento "<nombre>" --fecha YYYY-MM-DD --arbitro "<nombre>" --operador "<nombre>"` crea otros
(evento `piloto`, idempotente por nombre; código 1 si el evento existe con otro tipo).

## 1.3 Consultas de solo lectura (CU-07, CU-12)

Ninguno crea ni modifica nada (`POST`/`PUT`/`DELETE` responden 404/405). Exigen JWT como el
resto de las rutas (sección 0). Las clases usan siempre los nombres del modelo (sección 1).

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

`GET /revisiones/{revision_id}/pose` (F-031, CU-08, D-14) — keypoints crudos de A y B para
dibujar sus esqueletos en un modal con fondo negro, sin video. Protegida por JWT como el resto
y con `Cache-Control: no-store`. Sale del `.npz` de la clasificación (sección 8.1), no del video.
```json
{ "revision_id": "uuid", "fps": 30.0, "frame_w": 1280, "frame_h": 720,
  "frame_inicio": 0, "frame_tocado": 25, "n_frames": 38, "conf_min_keypoint": 0.3,
  "tiradores": {
    "A": { "color": "ROJ", "brazo": "diestro",
           "xy": [ [[315.6, 302.4], [313.8, 296.5], "... 17 pares"], "... un arreglo por frame" ],
           "conf": [ [0.133, 0.015, "... 17 valores"], "..." ],
           "detectado": [true, true, "..."],
           "angulo_codo": [100.1, 94.6, null, "..."] },
    "B": { "color": "VER", "brazo": "zurdo", "...": "..." } },
  "motivo": null }
```
- `xy` en píxeles del frame, a 1 decimal. `conf` a 3 decimales. Todos los arreglos de
  `tiradores` miden `n_frames`.
- `frame_inicio`: el `.npz` solo guarda los frames desde que Fog fija las identidades A/B
  (`lock_frame`), así que su índice `i` es el frame `frame_inicio + i` del clip. Para ubicar
  el tocado en los arreglos, el índice es `frame_tocado - frame_inicio`. `frame_tocado` y `fps`
  son los de `tocado_clip` y `clip`.
- `conf_min_keypoint`: la confianza mínima del extractor de features (`CONF_THR` de
  `shared/feature_extractor.py`, igual a la de `dataset/05_extract_features.py`). Un keypoint
  por debajo de ese valor no se dibuja.
- `angulo_codo`: ángulo hombro-codo-muñeca del brazo armado declarado en el combate, en grados y
  sin estandarizar, calculado con `valid_pt` y `angle_three_points` del extractor (el valor que
  recibe el modelo antes de la estandarización, sin la interpolación de saltos). `null` si el
  tirador no fue detectado en el frame o alguno de los tres keypoints no pasa `CONF_THR`.
- La línea del arma no se dibuja ni se entrega (D-18).
- Sin trazos (timeout o pose incompleta, `.npz` vacío): **200** con `n_frames: 0`,
  `tiradores: null` y `motivo` igual al `motivo_no_disp` de la clasificación.
- **404** si la revisión, su clip o su `.npz` no existen; **422** si `revision_id` no es uuid
  (a diferencia de `GET /revisiones/{id}`, que responde 404); **401** sin token.
- **409** si la revisión no tiene clasificación o si el SHA-256 del `.npz` no coincide con
  `keypoints_sha256` (se registra en el log técnico `fog.application` y no se sirven datos).
  Los dos 409 se distinguen por `codigo`, no por el texto de `detail` (que puede cambiar):
  `{"detail": "la revisión aún no tiene una clasificación registrada", "codigo": "sin_clasificacion"}`
  y `{"detail": "keypoints alterados", "codigo": "keypoints_alterados"}`.

`GET /revisiones/{revision_id}/razonamiento` (F-035, F-008, CU-09, D-15 a D-17) — una o dos
frases cortas que explican la sugerencia. Se calculó al clasificar y se sirve tal como se
guardó en `evidencia` (D-16); no recalcula nada. Protegida por JWT y con
`Cache-Control: no-store`. Los campos `null` se omiten.
```json
{ "revision_id": "uuid", "estado": "respaldada",
  "frases": ["ROJ inició la extensión del brazo 133 ms antes que VER.",
             "Criterio FIE t.101.2-4: la extensión del brazo precede al ataque."],
  "criterio_fie": { "articulo": "t.101.2-4", "clase": "AttackA" }, "confianza": 0.74,
  "ventana_atencion": { "desde_ms": -620, "hasta_ms": -180 }, "frame_clave": 131,
  "eventos": [
    { "tipo": "tocado", "frame_idx": 143, "t_ms": 0 },
    { "tipo": "inicio_extension_brazo", "tirador": "A", "frame_idx": 118, "t_ms": -800,
      "censurado_inicio": false },
    { "tipo": "inicio_extension_brazo", "tirador": "B", "frame_idx": 122, "t_ms": -667,
      "censurado_inicio": false },
    { "tipo": "inicio_desplazamiento", "frame_idx": 110, "t_ms": -1100, "censurado_inicio": false } ],
  "params_version": "1" }
```
- `estado`: `respaldada`, `discordante`, `no_concluyente`, `insuficiente` (ver CU-09 en
  `contexto_sabre.md`), `no_calculado` (el cálculo del razonamiento falló al clasificar: la
  clasificación se guardó igual, sin `frases` ni `eventos`; el fallo queda en el log técnico como
  `razonamiento.error` y como una fila `criterio_fie` con ese estado), `no_registrado` (solo
  revisiones anteriores al registro de razonamiento, D-17: sin `frases`, `criterio_fie` ni
  `eventos`) o `no_disponible` (la clasificación no está disponible:
  trae `motivo`, el `motivo_no_disp`, y no hay razonamiento).
- Las frases salen de plantillas fijas (D-15), con a lo sumo 2 frases y 220 caracteres (U6). El
  tirador se nombra solo por su color (`ROJ` o `VER`), sin la letra A/B; los tiempos van en ms o en s con coma decimal.
  El texto no afirma que el modelo decidió ni que aplicó una regla FIE: el BiLSTM no aplica reglas.
- `eventos[].frame_idx` es el frame del clip (el mismo eje que `frame_inicio` de `/pose`) y
  `t_ms` los milisegundos respecto al tocado (negativo = antes). `inicio_extension_brazo` sale
  del `angulo_codo` crudo de `/pose` (no del interpolado que recibe el modelo): un hueco de
  detección da `insuficiente`, no un inicio rellenado. Antes de buscar la subida se aplica una
  mediana móvil de 3 frames al ángulo crudo; los trazos de `/pose` siguen mostrando el ángulo
  crudo. `censurado_inicio: true` en `inicio_extension_brazo` indica que el brazo armado ya estaba
  extendido (≥ 135°) en el primer frame válido del tirador, a partir de `frame_inicio`: la
  extensión empezó **antes del clip** y `frame_idx` es ese primer frame. Un inicio censurado
  precede a cualquier inicio observado; si lo están los dos, el estado es `no_concluyente`.
- `inicio_desplazamiento` es **un solo evento sin `tirador`** (acercamiento mutuo): con la
  corrección DEF-27 la velocidad relativa del CM es idéntica para A y B, así que **no identifica
  quién se desplaza primero**, y **no entra en las plantillas**. `censurado_inicio: true` indica que el
  umbral ya se superaba en los primeros 3 frames de la secuencia: el inicio real es anterior y
  `frame_idx` es el primero de la secuencia.
- `ventana_atencion` y `frame_clave` (el frame de mayor peso de atención) faltan si Cloud no
  envió `atencion`. `criterio_fie.clase` usa el vocabulario del modelo (`AttackA`, ...).
- **404** si la revisión no existe; **422** si `revision_id` no es uuid; **401** sin token;
  **409** `{"detail": "la revisión aún no tiene una clasificación registrada", "codigo":
  "sin_clasificacion"}` si la revisión no tiene clasificación. Aquí no aparece
  `keypoints_alterados`: este endpoint lee `evidencia`, no el `.npz`.

`GET /auditoria/verificar` — resultado de `sabre.fn_verificar_auditoria()` sin filtrar, con
200 en ambos casos: `{ "integra": true, "alteradas": [] }` o
`{ "integra": false, "alteradas": [ { "seq": 3, "esperado": "<hash>", "guardado": "<hash>" } ] }`.

`GET /modelo/activo` — `{ "nombre": "...", "num_clases": 6, "f1_macro_test": 0.4856,
"kappa_piloto": null }`; las métricas son las registradas en `modelo_version` (null si no
se registraron). **404** si no hay versión activa.

`GET /validaciones/{evento_id}/resumen` (L02, T-017, RNF-03, RNF-06) — resumen de la sesión de
validación de un evento, con el mismo contenido que el `resumen.json` de
`scripts/exportar_evidencia.py`. Se calcula desde PostgreSQL sobre las revisiones **con
veredicto** del evento; el JSONL de L01 no es la fuente (solo se concilia). Exige JWT (sección 0);
no hay regla de autorización por rol documentada. **404** si el evento no existe,
**422** si `evento_id` no es uuid. Solo lectura.
```json
{ "evento_id": "uuid", "generado_en": "2026-09-29T20:00:00+00:00",
  "conciliacion": { "n_base": 10, "n_jsonl": 9, "jsonl_presente": true, "lineas_ilegibles": 0,
                    "faltantes_en_jsonl": ["<revision_id>"], "sobrantes_en_jsonl": [] },
  "integridad": { "fn_verificar_auditoria": "ok", "integra": true,
                  "registros_alterados": 0, "seq_alterados": [] },
  "validacion": { "n_revisiones": 8, "disponibles": 7,
        "no_disponibles": { "n": 1, "por_motivo": { "pose_incompleta": 1, "confianza_baja": 0,
          "clase_fuera_mvp": 0, "timeout": 0, "sin_senal_favero": 0, "mensaje_invalido": 0 } },
        "latencia": { "n_total": 8, "n_disponibles": 7, "n_no_disponibles": 1,
                      "sin_medicion": 0, "mediana_ms": 48, "max_ms": 55, "p95_ms": null,
                      "p95_excede_umbral": true, "pct_le_60s": 87.5,
                      "umbral_ms": 60000, "cumple": false },
        "latencia_inferencia": { "n_disponibles": 7, "n_medidas": 7, "sin_medicion": 0,
                                 "mediana_ms": 14, "p95_ms": 34, "max_ms": 34,
                                 "pct_le_50ms": 100.0, "umbral_ms": 50, "cumple": true },
        "kappa": { "n": 6, "calculable": true, "kappa": 0.3333, "banda": "aceptable",
                   "umbral": 0.61, "cumple": false, "motivo": null },
        "concordancia": { "n": 6, "pct": 66.67 },
        "matriz_confusion": { "clases": ["AttackA", "AttackB", "ContrattackA", "ContrattackB",
                                         "RiposteA", "RiposteB"],
                              "filas": "sistema", "columnas": "arbitro",
                              "matriz": [[2, 0, 0, 0, 0, 1], "... 6 filas de 6"] } },
  "modelo": { "nota": "Referencia offline: F1 macro se mide sobre el test set, no en la sesión. ...",
              "activo": { "nombre": "...", "num_clases": 6, "f1_macro_test": 0.5249,
                          "f1_macro_test_rotulo": "checkpoint desplegado (test)",
                          "kappa_piloto": null },
              "modelos_en_revisiones": ["..."], "tabla_m01": "## Tabla resumen — ...\n..." } }
```
Definiciones (solo las de `docs_claude/protocolo_validacion.md`):
- **Validación**: única (κ sistema-árbitro). Un solo bloque `validacion` con todas las revisiones con veredicto del evento; `tocado.fuente` no separa el resumen.
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
- **Latencia de inferencia** (`latencia_inferencia`, F-027): `clasificacion.latencia_inferencia_ms`
  (la del campo 16 de L01), el tiempo del clasificador por clip en Cloud. Solo sobre las
  revisiones **disponibles** (las no disponibles no tuvieron inferencia): `mediana_ms`, `p95_ms`
  (rango más cercano, ⌈0.95·n⌉-ésimo), `max_ms` y `pct_le_50ms` (sobre las medidas).
  `cumple` = p95 ≤ 50 ms. Una disponible con `latencia_inferencia_ms` nulo (p. ej. anterior a la
  migración `0004`) queda fuera y se cuenta en `sin_medicion`. Sin medidas, todo es null.
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
  F1 no se recalcula en la sesión. `activo.f1_macro_test` es la métrica del **checkpoint
  desplegado (test)** (`f1_macro_test_rotulo`); la cifra reportable de RNF-03 es la media de la
  serie de N = 10 corridas (`tabla_m01`), y así lo dicen `nota` y `resumen.md`. No incluye delta de κ inter-árbitro: su protocolo no está
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
| `t_luz_a_ms` | int | Instante de la luz Favero de A, en ms desde el inicio del clip (RF-02), entre 0 y la duración del clip, ambos incluidos (**422** si no). Omitido = luz de A apagada |
| `t_luz_b_ms` | int | idem para B. **Al menos uno de los dos instantes es obligatorio** (CU-03 flujo 2a; `tocado` lo exige con `CHECK (luz_a OR luz_b)`) |
| `t_tocado_ms` | int | **[OBSOLETO]** instante único. Solo se usa si `t_luz_a_ms` y `t_luz_b_ms` vienen ambos ausentes: queda como instante de cada luz encendida por `has_luz_A/B`. Con los instantes por luz se ignora |
| `has_luz_A` | bool | **[OBSOLETO]** `true` si se encendió la luz de A. Preferir `t_luz_a_ms` |
| `has_luz_B` | bool | **[OBSOLETO]** idem para B |
| `luz_frame_a` | int | **[OBSOLETO]** alias de `has_luz_A`: índice de frame (0-based) en que se prendió la luz de A. Solo se usa si `has_luz_A` y `has_luz_B` vienen ambos ausentes |
| `luz_frame_b` | int | **[OBSOLETO]** alias de `has_luz_B`, misma regla que `luz_frame_a` |

`t_luz_a_ms` y `t_luz_b_ms` son la forma vigente (V02): en un tocado doble las dos luces pueden
encenderse con algunos fotogramas de diferencia. La luz encendida se deduce de que exista su instante, y el servidor calcula
`t_tocado_ms` = el menor de los dos (`tocado.t_tocado_ms`; de él sale `frame_tocado`).
`has_luz_A/B` con `t_tocado_ms` (DEF-14) y `luz_frame_a/b` se mantienen solo como alias obsoletos
durante esta versión para no romper clientes viejos. Los instantes no entran a las features, a la
ventana ni a la entrada del modelo: este solo usa si cada luz está encendida (filtro Favero), así
que la sugerencia es la misma con la forma vigente y con los alias.

**Errores (antes de procesar el video):**

| código | causa |
|---|---|
| `404` | el combate no fue creado (sección 1.1) o `match_id` no es un uuid |
| `422` | ningún instante de luz (ni alias obsoleto), o un instante fuera de `[0, duración del clip]` |
| `503` | no hay versión de modelo activa (`scripts/registrar_modelo.py`) |

Un combate admite N clips: ya no hay `409` por segundo clip.

**Validación del archivo (DEF-13):**

- Si el archivo no abre como video (`cv2.VideoCapture` falla), no informa fps válidos o tiene
  menos de `MIN_FRAMES` frames (3 por defecto): `400` con `detail`.
- Si el archivo pesa más de `CLIP_MAX_MB` (200 MB por defecto,
  configurable por entorno): `413` con `detail`.
- Si `t_luz_a_ms` o `t_luz_b_ms` es negativo o mayor que la duración del clip
  (`round(frames/fps·1000)`): `422` con `detail`. La comprobación ocurre antes de guardar el
  clip y de abrir la revisión, así que no queda clip, tocado ni mensaje en Redis.

**Persistencia (D03, `docs_claude/sabre_ai_schema.sql`):**

1. Al recibir un clip válido, en una transacción: `clip` (`origen='carga'`, `camara='unica'`,
   `uri` + `sha256` del archivo en `STORAGE_DIR`, `fps`, `ancho_px`, `alto_px`,
   `duracion_ms = round(frames/fps·1000)`), `tocado` (`fuente='simulado'`, `luz_a/b`,
   `t_luz_a_ms`, `t_luz_b_ms` y `t_tocado_ms` = el menor de los dos), `tocado_clip` (`frame_tocado = round(t_tocado_ms/1000·fps)`) y
   `revision_var` (`aceptada=true`, `arbitro_id` = árbitro del combate). No se registra qué
   tirador pidió la revisión (D-04).
2. Con el veredicto de Cloud, o con el "no disponible" (pose incompleta, timeout, o
   `disponible=false` de Cloud), se registra `clasificacion` contra el **modelo activo**
   (`modelo_version.activo`): probabilidades post filtro Favero, keypoints crudos de la
   `TrackedSequence` en `.npz` (`keypoints_uri` + `keypoints_sha256`; por tirador
   `{a,b}_xy`, `_conf`, `_box`, `_detected`, más `frame_w/h`, `locked`, `lock_frame`) y
   `latencia_ms` desde la recepción del clip hasta la sugerencia (o hasta el "no disponible") y,
   solo en las disponibles, `latencia_inferencia_ms` (la que informa Cloud; NULL en las no disponibles).
   La API y el dominio usan los nombres del modelo; solo el adaptador de persistencia los
   traduce a los del esquema al guardar (`AttackA` → `AtaqueA`, `ContrattackA` →
   `ContraataqueA`, `RiposteA` → `RiposteA`; igual en las llaves de `probabilidades`) y de
   vuelta al leer. Respeta `UNIQUE (tocado_id, modelo_version_id)` (un tocado por clip, así
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
- **Timeout de extracción** (`motivo="timeout"`, `timed_out=true`, DEF-08): el
  pipeline completo tiene un presupuesto de `CLIP_UPLOAD_TIMEOUT_S` (60 s por
  defecto, RF-13, RNF-09) desde que Fog recibe el clip; la espera del veredicto
  de Cloud se acota además a lo que reste. Si la pose no termina en ese plazo,
  Fog cancela la lectura de frames, guarda el clip, abre la revisión con una
  clasificación **no disponible** (`disponible=false`, `motivo_no_disp="timeout"`,
  keypoints vacíos; `GET /revisiones/{id}` la devuelve en `sugerencia`), no
  publica en Redis y responde 200 con su `revision_id`. La revisión queda abierta:
  el árbitro puede registrar su veredicto (`POST /revisiones/{id}/veredicto`).
- **Cloud no disponible** (`motivo="mensaje_invalido"`, `timed_out=false`): Cloud publicó
  `disponible=false` (sección 6).

### 4.0 Ventana del clip (D-19, cierra DEF-32)

`POST /matches/{match_id}/clip` recorta el clip a
`[t_tocado − VENTANA_PRE_MS, t_tocado + VENTANA_POST_MS]` (2.000 ms antes y 500 ms después, parámetros
`VENTANA_PRE_MS` y `VENTANA_POST_MS` en `shared/config.py`), con `t_tocado` = el menor instante de luz.
El recorte es idempotente con tolerancia de un frame: un clip que ya cubre justo esa ventana no cambia. Si se recorta, el clip guardado es el recortado (su `sha256` es el del
recortado) y los instantes de luz que se registran en `tocado` son relativos a él. La validación de
`t_luz_*_ms` (entre 0 y la duración) se hace contra el clip original.

## 4.1 Cierre de sesión y purga de clips (D-22, política de datos personales)

Ningún clip se conserva después de la sesión. **`POST /sesion/cerrar`** (JWT), cuerpo `{"match_id": "<uuid>"}` (el
combate cuya sesión —su evento— se cierra):

1. ejecuta el respaldo verificado del evento (`scripts/respaldar_sesion.sh`: dump, `.tgz` **sin clips**, manifiesto y
   restauración de prueba);
2. **solo si el respaldo y su verificación pasan**, borra los archivos de clip de esa sesión.

Respuesta 200: `{respaldo, clips_borrados}`. 404 `combate_inexistente` si el combate no existe; 422 si `match_id` no es
un uuid; **500 `respaldo_fallido`** si el respaldo falló: no se borró nada, el `detail` trae la salida del respaldo y se
puede reintentar. Como el almacén direcciona los archivos por hash, un archivo que también usa un clip de otra sesión no
se borra. La base conserva `clip.sha256` y los metadatos, así que la cadena de auditoría sigue verificable
(`fn_verificar_auditoria()` devuelve 0 filas). `scripts/purgar_clips.py --evento <uuid> --confirmar` queda como
herramienta manual.

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
| `latencia_inferencia_ms` | str | duración de `ActionClassifierPort.classify` en ms (auditoría, F-027); Fog la persiste en `clasificacion.latencia_inferencia_ms`. El mensaje `disponible=false` no la trae y queda NULL |
| `modelo` | str | `"lstm_6class/<run_id>/<archivo>"`, derivado de `MODEL_RUN_DIR` (ver `LSTM6ClassAdapter.model_version_name`) |
| `atencion` | str | **opcional** (F-035). JSON de floats a 4 decimales con los pesos de atención del BiLSTM por frame: largo T (el de la secuencia de `fog:features`, índice `t` = frame `lock_frame + t` del clip) y suma ≈ 1. Se calcula en la misma pasada que el veredicto. Si el modelo no usa atención, el campo no se publica |
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
para la auditoría y `atencion` para el razonamiento (campos opcionales: si faltan, se guardan
sin ellos; sin `atencion`, Fog no calcula la ventana de atención y el resto del razonamiento
sigue funcionando).

Fog mantiene una tarea de fondo por revisión activa (`revision_id`) que hace `XREAD`
bloqueante sobre este stream y reenvía el resultado por WebSocket en cuanto llega.

## 7. Fog → Front: WebSocket de veredicto

> **Autenticación: solo local, temporal.** Con `ENTORNO=remoto` esta ruta no existe. En local
> exige el JWT en `?token=` (ver sección 0); reemplazarlo por autenticación por primer
> mensaje queda pendiente y sin release asignado (`Tesis/prompts/FUTURO/PENDIENTE_V2_websocket_camara.md`).

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
| `decision` | `"mantener"`, `"cambiar"` o `"anular"` (acción simultánea, FIE t.106). Describe la relación con la decisión original del árbitro en pista. Cualquier otro valor: 422. El frontend los muestra como "Mantiene", "Cambia" y "Anula" (Historial). La interfaz muestra la sugerencia y pregunta "¿Modifica la clase sugerida?" sin respuesta por defecto (No = la clase sugerida es `clase_final`; Sí = el árbitro elige entre las 6; sin sugerencia elige directamente). La interfaz deduce `decision` y no se la pregunta al árbitro: `"mantener"` si `clase_final` es la clase sugerida, `"cambiar"` si es otra. Sin sugerencia la clase la decide el árbitro, por lo que se deduce `"cambiar"`. La interfaz nunca pregunta "¿Cambia la decisión original en pista?". Nada se preselecciona: cada respuesta es una acción explícita del árbitro (DEF-28) |
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

El snapshot de las revisiones nuevas incluye `justificacion` (`estado`, `frases`, `articulo_fie`,
`params_version`: el razonamiento guardado al clasificar, F-035); el hash lo cubre porque
`fn_verificar_auditoria()` lo calcula sobre el snapshot completo. Las revisiones anteriores
no lo llevan y no se recalculan (D-17).

Respuesta (JSON): `match_id` (el combate de la revisión), `revision_id`, `veredicto_id`,
`decision`, `clase_final`, `arbitro_id`, `registrado_en`, `cerrada_en`, `auditoria_seq`,
`auditoria_hash`.

| código | causa |
|---|---|
| `404` | la revisión (o un `revision_id` que no es uuid) o el árbitro no existen |
| `409` | la revisión ya tiene veredicto (`"codigo": "veredicto_ya_registrado"`); o aún no tiene clasificación registrada (`"codigo": "sin_clasificacion"`; sin ella el registro no podría guardar la versión de modelo, RF-22). Cuerpo: `{"detail": "...", "codigo": "..."}` |
| `422` | `"mantener"` o `"cambiar"` sin `clase_final`; `"anular"` con `clase_final`; `clase_final` fuera de la taxonomía del modelo |

**Etiqueta de reentrenamiento.** La vista `sabre.v_muestras_confirmadas` (migración `0003`)
toma como etiqueta siempre `veredicto.clase_final`, excluyendo `anular`, sin depender de si
el árbitro mantuvo o cambió la acción; `clase_sugerida` es la de la clasificación. La
concordancia sistema-árbitro es `clase_sugerida == clase_final`.

Al cerrarse la revisión, Fog agrega una línea al log de evidencia
`EVIDENCE_DIR/<evento_id>.jsonl` (logger `sabre.evidencia`, L01), armada con lo
ya registrado en la base. Campos, en este orden: `ts` (`veredicto.registrado_en`),
`evento_id`, `revision_id`, `modelo`, `luz_A`, `luz_B`, `disponible`, `motivo`,
`clase_sugerida`, `confianza`, `latencia_ms`, `decision`, `clase_final_arbitro`,
`concordancia` (`clase_sugerida == clase_final_arbitro`; `null` si no disponible
o anulada), `hash_auditoria` y `latencia_inferencia_ms` (campo 16;
`clasificacion.latencia_inferencia_ms`, `null` si no disponible), `t_luz_a_ms` (campo 17) y
`t_luz_b_ms` (campo 18), de `tocado.t_luz_a_ms/t_luz_b_ms` (`null` = luz apagada), también en
`revisiones.csv`. Las clases usan los nombres del modelo. Si la
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
  `evento` (las precarga la migración 0005; `scripts/crear_sesion_validacion.py` crea más; el
  login es de un usuario maestro único, sección 0; sección 1.2) y una versión de modelo activa
  (`scripts/registrar_modelo.py`). La base del compose publica el puerto
  `POSTGRES_HOST_PORT` (5433 por defecto, solo loopback; ver `GUIA_EJECUCION.md`). `tocado.registrado_por` queda nulo (el usuario
  maestro no identifica al operador). La transacción única del veredicto usa
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
| `EVIDENCE_DIR/<evento_id>/razonamiento_v1.md` | análisis descriptivo y de solo lectura del razonamiento de la Validación 1 junto a una muestra de clips de train (EXP03-b); no escribe en `evidencia` ni en la auditoría (D-17); se sobrescribe al reejecutar | `scripts/analizar_razonamiento_v1.py [--evento <id>] [--muestra-train scripts/datos/muestra_train_razonamiento.json]` |

`EVIDENCE_DIR` y `DATABASE_URL` son obligatorios al arrancar Fog: si falta alguna, Fog no
arranca (`RuntimeError` al importar `fog.main`, con el nombre de la variable que falta).
`STORAGE_DIR` se exige al primer uso (carga de clip y registro de clasificaciones).
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
| Trazos de pose en el modal (CU-08, F-031): botón "Ver trazos" (tecla T) en Revisión VAR (Paso 2) y en el detalle del Historial (CU-12); se pide solo al abrir el modal y se guarda por revisión mientras la pantalla siga montada | `GET /revisiones/{revision_id}/pose` |
| Razonamiento (CU-09, F-035, F-008): botón "Ver razonamiento" (tecla J) en Revisión VAR (Paso 2) y en el detalle del Historial (CU-12), que abre un modal; se pide solo al abrir y se guarda por revisión mientras la pantalla siga montada. Muestra las frases tal como llegan, el artículo FIE y los eventos, cada uno con "Ver en trazos" que abre el modal de trazos en su `frame_idx` (un evento con `censurado_inicio` se muestra como "antes del inicio del clip" y abre en el primer frame). Con el razonamiento en caché, la barra de tiempo de los trazos marca los eventos y la ventana de atención | `GET /revisiones/{revision_id}/razonamiento` (los dos 409 de `/pose` y el de `/razonamiento` se distinguen por `codigo`, no por `detail`) |
| Resumen y exportación de la validación (L02) | `GET /validaciones/{evento_id}/resumen` |
| Estado del sistema y modelo | `GET /health`, `GET /modelo/activo` |

La traducción de `action`/`fencer` a las etiquetas de la interfaz está en la sección 7.

Fuera de alcance (solicitud de cambio del 20/11/2026; trabajo futuro en la rama `future/edge-favero`): captura
automática por cámara y señal Favero real. Pendiente: consumo del WebSocket de veredicto si se retoma el flujo WebRTC.
