# Despliegue remoto de SABRE.AI (DEPLOY07 y DEPLOY09)

Estado (13/11/2026): tras el incidente de Railway del 21/10/2026 el despliegue se rehízo con Tailscale (DEPLOY09). En Railway solo hay dos servicios, `frontend` y `cloud`, en el proyecto `sabre-ai-tailscale`; no hay servicio Redis ni URL pública de Fog. Fog, Redis y PostgreSQL corren en el Mac del autor. Al cierre de la verificación los dos servicios de Railway se detuvieron para no gastar el crédito Free. Registro del incidente: `docs/seguridad/INCIDENTE_2026-10-21_railway.md`.

## 1. Arquitectura
Navegador → HTTPS → [Railway] `frontend` (nginx: estático + `/api`) → `127.0.0.1:18001` → [tailnet, WireGuard] → `mac:8001` → Fog (`127.0.0.1:8011`) → PostgreSQL local.
[Railway] `cloud` → `localhost:6379` (reenviador `socat` + `tailscale nc`) → [tailnet] → `mac:6379` → Redis nativo (`127.0.0.1:6390`, TLS 1.3 con mTLS y ACL). Fog usa el mismo Redis por `localhost:6390`.

- Cada contenedor se une a la tailnet con Tailscale **1.104.4** fijo, en modo userspace (sin `NET_ADMIN`), con una clave efímera, preaprobada y de 7 días: `tag:frontend` para el frontend y `tag:cloud` para Cloud. Sin `TS_AUTHKEY` el frontend no arranca, y Cloud arranca en modo local.
- La política de la tailnet (`deploy/tailscale/politica.hujson`) deja a `tag:frontend` llegar solo a `mac:8001` y a `tag:cloud` solo a `mac:6379`.
- `tailscale serve` publica esos dos puertos a la tailnet solo mientras dura la ventana que abre `scripts/fog_remoto.sh start --horas N` (N de 1 a 8); no hay Funnel.
- Los reenviadores de cada imagen apuntan a un único puerto: el de Cloud a `mac:6379` y el del frontend a `mac:8001`.

## 2. Clasificación de la información que viaja por Redis
| Stream | Productor | Contenido | Dato personal |
|---|---|---|---|
| `fog:features` | Fog | `match_id`, `revision_id`, matriz de features T×192 (float32), lado armado, luces A/B, marca de tiempo | No: sin video, sin imagen, sin nombres |
| `fog:features:dead` | Cloud | entrada rechazada y motivo | No |
| `cloud:verdicts:<revision_id>` | Cloud | clase sugerida, confianza, probabilidades, modelo, motivo si no disponible | No |
| `auth:fallos:<ip>`, `auth:bloqueo:<ip>` | Fog | contador y bloqueo por IP del login | IP (TTL de 15 min) |

Los identificadores son UUID; los alias de los tiradores y el video nunca salen de Fog.

## 3. Medición previa (Parte A)
- Memoria de Cloud (`docker stats`, registrada en DEPLOY05b, `GUIA_INSTALACION.md`): 274 MiB en reposo y 162 MiB procesando la prueba de humo (pico 274 MiB ≈ 287 MB < 450 MB): cabe en 0.5 GB. No se repitió.
- Imagen de Cloud (`sabre-cloud:local`): 1.43 GB en disco local (torch CPU); imagen del frontend: 93.6 MB.
- Plan (docs.railway.com/reference/pricing/plans, 08/10/2026): Free = 0.5 GB RAM, 1 vCPU, volumen 0.5 GB y **$1 de crédito al mes**. Tres servicios siempre encendidos pueden agotarlo: ver decisiones pendientes.

## 4. Controles de Redis (implementados y verificados en local)
- `port 0`, `tls-port 6379`, `tls-protocols TLSv1.3`, `tls-auth-clients yes` (mTLS con CA propia de 1 año; certificados de cliente separados para Fog y Cloud).
- ACL (SEC02, vigente en DEPLOY09): `user default off` y un usuario por nodo, `fog` y `cloud`, cada uno con su contraseña aleatoria y permisos mínimos (`fog`: `XADD fog:features` y lectura de `cloud:verdicts:*`; `cloud`: lectura del grupo de `fog:features` y escritura en `fog:features:dead` y `cloud:verdicts:*`). Histórico de DEPLOY07: usuario `sabre` con contraseña aleatoria, solo claves `fog:*`, `cloud:*`, `auth:*` y solo los comandos de Fog y Cloud (`ping hello client|setinfo client|setname xadd xread xreadgroup xack xgroup xautoclaim xlen xtrim expire ttl incr incrby set del`). `redis-py` usa `INCRBY` para `incr`: se descubrió al probar.
- Sin persistencia, `maxmemory 200mb` + `noeviction`, `XADD ... MAXLEN ~ 100` (`STREAM_MAXLEN`) en `fog:features` y su dead-letter.
- Secretos: variables `REDIS_TLS_*_B64` y `REDIS_PASSWORD` → el entrypoint los escribe en `/dev/shm` con permisos 600 y las borra del entorno. Contenedor no root.
- Cliente: `REDIS_URL=rediss://...` + `REDIS_TLS_CA/CERT/KEY` (rutas). Verifica cadena y nombre del servidor. Sin las variables, modo local sin cambios.

Prueba local (puerto 6390): sin TLS → conexión cerrada; TLS sin certificado de cliente → I/O error; certificado sin contraseña → `NOAUTH`; `sabre` con `FLUSHALL`, `KEYS`, `CONFIG`, `GET` de clave ajena → `NOPERM`; TLS 1.2 → alerta `protocol version`.

## 5. Variables (solo en el panel de Railway, como *sealed*, o en `backend/.secrets/`)
| Servicio | Variables | Notas |
|---|---|---|
| cloud | `TS_AUTHKEY` (`tag:cloud`), `REDIS_URL` (`rediss://cloud:…@localhost:6379/0`), `REDIS_TLS_CA_B64`, `REDIS_TLS_CERT_B64` (`cloud.crt`), `REDIS_TLS_KEY_B64` (`cloud.key`), `RAILWAY_DOCKERFILE_PATH=cloud/Dockerfile` | `ENTORNO=remoto` lo fija el entrypoint al detectar `TS_AUTHKEY` |
| frontend | `TS_AUTHKEY` (`tag:frontend`), `PROXY_SHARED_TOKEN`, `RAILWAY_DOCKERFILE_PATH=deploy/railway/Dockerfile` | `FOG_UPSTREAM` quedó fijo en la imagen (`http://127.0.0.1:18001`); `CLIP_MAX_MB` tiene valor por defecto |
| Fog (Mac) | `ENTORNO=remoto`, `AUTH_USER`, `AUTH_PASSWORD_HASH`, `AUTH_JWT_SECRET`, `PROXY_SHARED_TOKEN`, `REDIS_URL_REMOTO` (`rediss://fog:…@localhost:6390/0`), `REDIS_TLS_*`, `POSTGRES_PASSWORD` | todo en `.secrets/fog_remoto.env` |

No van a Railway: `ca.key`, `server.*`, `fog.*`, `postgres_password.txt` y `auth_*`. Con `ENTORNO=remoto`, Cloud y Fog se niegan a arrancar si falta `REDIS_URL`, si no empieza por `rediss://` o si falta alguna de `REDIS_TLS_CA/CERT/KEY` (`shared/config.py: require_redis_remoto`), y el frontend si falta `PROXY_SHARED_TOKEN`.

Para cargar un valor sin verlo: `sh scripts/copiar_secreto.sh NOMBRE` lo copia al portapapeles e imprime su huella; `--vaciar` limpia el portapapeles. Las claves de Tailscale las crea el autor en el panel de Tailscale. Los proyectos nuevos de Railway ignoran `railway.json`: el Dockerfile se elige por `RAILWAY_DOCKERFILE_PATH` y la política de reinicio (On Failure, 3 reintentos) se fija en el panel de cada servicio.

PKI: la genera `scripts/rotar_secretos.sh` (llama a `generar_pki_redis.sh localhost`; `REDIS_SAN_HOSTS` cambia los nombres) → `backend/.secrets/redis/` (ignorado por git). El certificado del servidor lleva solo `localhost`.

**Rotación (procedimiento usado en SEC01, 06/11/2026)**
1. Desde `backend/`: `sh scripts/rotar_secretos.sh`. Mueve lo vigente a `.secrets/_retirado_2026-10-27/` y genera `AUTH_JWT_SECRET`, `PROXY_SHARED_TOKEN`, `POSTGRES_PASSWORD`, la PKI completa (CA incluida) y la contraseña de Redis; pide la contraseña maestra por `getpass` (mínimo 16 caracteres) y escribe el hash. Actualiza `POSTGRES_PASSWORD` en `.env` y regenera `.secrets/fog_remoto.env`. Imprime solo nombre, longitud y huella.
2. `REDIS_HOST_REMOTO=host:puerto sh scripts/rotar_secretos.sh --forzar` rota de nuevo todo menos el hash de la contraseña (para cambiarla, borrar `.secrets/auth_password_hash.env` antes). Sin esa variable, `REDIS_URL_REMOTO` queda en `PENDIENTE:6379`.
3. Pegar en el panel de Railway los valores nuevos (redis: `REDIS_PASSWORD` y `REDIS_TLS_*_B64` de servidor; cloud: `REDIS_URL` y `REDIS_TLS_*` de `cloud.*`; frontend: `PROXY_SHARED_TOKEN`), sin imprimirlos en la terminal ni en chats.
4. Reiniciar Fog: el JWT anterior pasa a dar 401 y el token de proxy anterior, 403.
5. Al cerrar el incidente, el autor borra `_retirado_2026-10-27/`. Registro: `docs/seguridad/INCIDENTE_2026-10-21_railway.md`.

## 6. Verificación de DEPLOY09 (13/11/2026, diseño Tailscale)
| # | Prueba | Resultado |
|---|---|---|
| 1 | `curl -I` al frontend | 200, HSTS, CSP, `nosniff`; `server: railway-hikari` (sin versión de nginx) |
| 2 | App sin login | Solo aparece la pantalla de login (navegador) |
| 3 | `/api/eventos`, `/api/matches/x` y `/api/revisiones` sin token | 401 de Fog, por la tailnet |
| 4 | 6 logins fallidos con `X-Forwarded-For` distinto en cada intento | 401 ×5 y 429 al 6.º |
| 5 | Fog sin URL pública | Sin Funnel; 8011 y 6390 solo en `127.0.0.1`; LAN e IP pública con los puertos cerrados (evidencia débil: depende del router) |
| 6 | Preflight CORS desde `https://ejemplo.com` | 400 sin `Access-Control-Allow-Origin` |
| 7 | Redis del Mac fuera de la tailnet | Misma evidencia que la 5 |
| 8 | Cloud sin dominio público | `railway domain list -s cloud`: sin dominios |
| 9 | Flujo completo con un clip real de 4,77 MB | Sugerencia `ContrattackA` (confianza 0,897) en 15,3 s; subida sola de 4,77 MB: 8,2, 10,9 y 13,1 Mbit/s en tres intentos. Ruta frontend→Mac y Cloud→Mac: **directa** (~96–99 ms), no por DERP. Ver nota sobre el clip |
| 10 | `fn_verificar_auditoria()` | 0 filas |
| 11 | Logs de Fog | `auth.login_fallo` con IP y usuario; ningún secreto vigente ni JWT en el log. No se probó `auth.login_ok` (la verificación no usó la contraseña maestra) |
| 12 | Sustituida por 5 y 18 | |
| 13 | Latencia | Ver la prueba 9 |
| 14 | JWT, `X-Proxy-Token`, contraseñas de Redis y certificados anteriores | 401, 403, rechazo de autenticación y rechazo TLS |
| 15 | ACL | `cloud` no escribe `fog:features` ni lee streams ni ejecuta `FLUSHALL`; `fog` no escribe en `cloud:verdicts` |
| 16 | `XADD` a mano a `cloud:verdicts:<id inexistente>` | Se acepta, pero Fog solo lee los streams de las revisiones que espera, así que no registra nada. El descarte (sin sesión pendiente o modelo distinto) existe en el código y lo cubren las pruebas de `tests/fog/test_forward_verdict.py` |
| 17 | Redis vaciado a mitad de los 6 logins | El 6.º da 429 (limitador local) |
| 18 | `fog_remoto.sh start --horas 1` | Se cerró solo (con la hora comprimida a 45 s por la variable de pruebas) |
| 19 | Límite de uso en Railway | **Decisión del autor: límite = crédito Free de 1 USD; no se configuró ningún tope en dólares ni alerta.** Consumo medido en el proyecto anterior: 1,01 USD en unos 7 días con los servicios encendidos sin uso, y el crédito se agotó. La documentación de Railway (docs.railway.com/reference/usage-limits, 13/11/2026) dice que los límites de uso están disponibles "for all subscription plans" y describe una alerta por correo (límite blando) que se puede configurar sin límite duro; **no se probó en el plan Free** y esa documentación no dice qué pasa al agotar el 1 USD de Free (no se verificó que los servicios se apaguen). Su límite duro mínimo es de 10 USD, mayor que el tope de 5 USD de DEPLOY09 |
| T1 | Aislamiento por etiqueta, medido desde los contenedores | `tag:cloud`: mac:6379 alcanzable; mac:8001, 5432 y 22 bloqueados. `tag:frontend`: mac:8001 alcanzable; mac:6379, 5432 y 22 bloqueados |
| T2 | Revocar una clave y borrar el nodo | A las 18:21 (Lima) se revocó la clave de `tag:cloud` y se borró el nodo. La primera sonda (18:22:39) ya no obtuvo respuesta de Cloud: el corte ocurrió en **menos de 1 min 39 s** (límite pedido: 5 min). Pasados 5 min el nodo **no volvió a unirse** a la tailnet (un solo arranque, sin reinicio) |

Notas:
- **Clip de la prueba 9:** es un clip recortado (54 fotogramas) recodificado a mayor bitrate. Los clips originales de varios MB (300+ fotogramas) superan el plazo de extracción de 60 s de Fog y se rechazan (ver DEF-32 en `contexto_sabre.md`).
- **Cloud queda colgado sin error** si pierde la tailnet: el cliente de Redis no tiene tiempo de espera, el proceso no sale ni escribe errores y Railway no lo reinicia. No hay healthcheck. Queda pendiente.
- Las pruebas 4 y 17 bloquean la IP de quien las hace durante 15 min.
- Datos de la verificación: se creó un evento y un árbitro de prueba en `sabre_expo`; al terminar se recreó la base vacía y se borraron los 5 ficheros de la prueba en `datos/`. El material del piloto de octubre no se tocó.

### Verificación de DEPLOY07 (arquitectura anterior, solo histórico)
| # | Prueba | Resultado |
|---|---|---|
| 1 | `curl -I` al frontend | 200; `strict-transport-security`, `content-security-policy`, `x-content-type-options: nosniff`, `referrer-policy`, `permissions-policy`; `server: railway-hikari` (sin versión de nginx) |
| 2 | App sin login | **Pendiente de confirmación visual** (el build exige token; no se probó con navegador) |
| 3 | `/api/eventos` y `/api/revisiones` sin token | 401 (`/api/health` es público por diseño) |
| 4 | 6 logins fallidos con `X-Forwarded-For` falsificado distinto en cada intento | 401 ×5 y 429 al sexto; el bloqueo es por la IP real |
| 5 | Túnel `/health` sin `X-Proxy-Token` | 403 |
| 6 | Preflight CORS desde `https://ejemplo.com` | 400 sin `Access-Control-Allow-Origin` |
| 7 | `redis-cli` al TCP proxy (`maglev.proxy.rlwy.net:33093`) | sin TLS: conexión cerrada; TLS sin certificado de cliente: error de E/S; certificado sin contraseña: `NOAUTH`; `sabre` con `FLUSHALL`: `NOPERM`. TLS 1.3 de extremo a extremo con verificación del certificado propio: el proxy no termina TLS |
| 8 | Cloud sin dominio público | `railway domain list --service cloud`: sin dominios |
| 9 | Flujo completo con 2 clips | Por el frontend público: login, configuración y clip → sugerencia (AttackA_0007: AttackB 0.53; RiposteB_0004: RiposteB 0.44). Desde datos móviles: **pendiente** (lo hace el autor) |
| 10 | `fn_verificar_auditoria()` en `sabre_expo` | 0 filas (2 revisiones) |
| 11 | Logs de Fog | `auth.login_ok` / `auth.login_fallo` con IP real y usuario; 0 apariciones de contraseñas, tokens o hashes |
| 12 | `fog_remoto.sh stop` | la URL del túnel responde 530 |
| 13 | Latencia de 2 clips (cliente → frontend → túnel → Fog → Redis → Cloud → respuesta) | 6.0 s y 7.9 s (límite D-08: 60 s) |

Imagen del frontend: 93.6 MB; `/usr/share/nginx/html` solo contiene el build (`_expo`, `index.html`…), sin `node_modules`.

### Hallazgo durante la verificación
Detrás de nginx y del túnel, Cloudflare añade la IP de salida de Railway a `X-Forwarded-For`; Fog tomaba la última entrada y todos los clientes compartían un solo bloqueo (cinco fallos de cualquiera bloqueaban al árbitro). Corregido con `PROXY_SALTOS_CONFIANZA=2` (el cliente es la penúltima entrada) y una prueba que falla sin el cambio.

### Segundo hallazgo: el frontend caía sin túnel
nginx resolvía `FOG_UPSTREAM` al arrancar; con el túnel cerrado el contenedor fallaba (`host not found in upstream`) y Railway lo detenía. Ahora el nombre se resuelve en cada petición (`resolver` + variable): sin túnel, `/` y `/healthz` responden 200 y `/api/` responde 502. Prueba: `SaberAISoftware/deploy/railway/probar_nginx.sh` (falló antes del cambio, pasa después).

## 7. Operación el día de la exposición (diseño Tailscale)

Todo se ejecuta en el Mac del autor, en `backend/`. Fog, Redis nativo y la ventana de la tailnet se arrancan y se apagan a mano; los servicios de Railway se encienden solo durante la sesión (plan Free: crédito de 1 USD).

### 1. Antes de empezar (10 min antes)
1. Docker (Colima) y PostgreSQL arriba: `docker ps --format '{{.Names}} {{.Status}}' | grep sabre-postgres-1`. Si no: `colima start` y `docker compose -f docker-compose.yml -f docker-compose.nativo.yml up -d postgres`.
2. Tailscale conectado (`tailscale status`) y sesión de Railway (`railway whoami`).
3. Claves de Tailscale vigentes (7 días): si caducaron, crear dos nuevas (`tag:cloud` y `tag:frontend`, efímeras, preaprobadas) y pegarlas como `TS_AUTHKEY` *sealed* en cada servicio.

### 2. Arrancar el Mac
```bash
sh scripts/redis_nativo.sh start
ENV_FILE=.secrets/fog_remoto.env sh scripts/fog_nativo.sh     # terminal aparte; ~30-60 s
set -a; . .secrets/fog_remoto.env; set +a
sh scripts/fog_remoto.sh start --horas 3                     # abre la ventana en la tailnet
```
La base `sabre_expo` se crea vacía con `CREATE DATABASE sabre_expo` si no existe; Fog aplica las migraciones al arrancar.

### 3. Encender Railway
Desde la carpeta de cada repo (`backend/` para Cloud y `SaberAISoftware/` para el frontend), con el proyecto `sabre-ai-tailscale` enlazado: `railway up -s cloud --ci` y `railway up -s frontend --ci`. Comprobar en los logs de cada servicio que aparezca **una sola vez** `tailnet lista` y, en Cloud, `Cloud escuchando 'fog:features'`. Si un servicio se reinicia, detenerlo (`railway down -s <servicio> -y`) y revisar el error antes de insistir.

### 4. Comprobar la cadena completa
`curl -s https://<dominio del frontend>/api/health` debe responder `{"fog":"ok","redis":"ok","postgres":"ok"}`. Después ingresar desde el navegador con el usuario del árbitro. El dominio actual del frontend es `frontend-production-23fc2e14.up.railway.app` (un dominio nuevo cada vez que se crea el servicio).

### 5. Al terminar
1. `railway down -s cloud -y` y `railway down -s frontend -y` (despliegues en `REMOVED`).
2. `sh scripts/fog_remoto.sh stop` (cierra la ventana; avisa si falta respaldar revisiones: `sh scripts/respaldar_sesion.sh --evento <uuid>`).
3. Apagar Fog (`Ctrl+C`) y `sh scripts/redis_nativo.sh stop`.

### Problemas frecuentes
| Síntoma | Causa y solución |
|---|---|
| Cloud se reinicia con `Connection closed by server` | `REDIS_URL` falta o no empieza por `rediss://`; con `ENTORNO=remoto` ahora falla con un mensaje que nombra la variable |
| Cloud o frontend no se unen a la tailnet | `TS_AUTHKEY` caducada, revocada o sin cargar. Una variable nueva en Railway queda pendiente hasta aplicar **Deploy** en el panel |
| Handshake TLS a Redis expira, aunque `tailscale ping` responde | MTU. Las imágenes fijan `TS_DEBUG_MTU=1100`; ver riesgos aceptados |
| La sugerencia sale `no disponible` por `timeout` con un clip largo | Fog agota el plazo de extracción de 60 s (DEF-32) |
| `/api/` responde 502 | La ventana de la tailnet está cerrada o Fog no corre |

## 8. Riesgos aceptados
- **Fog depende del Mac encendido**, con Redis nativo, PostgreSQL y la ventana de la tailnet abiertos.
- **`TS_DEBUG_MTU=1100`:** es una variable de depuración de Tailscale, ligada a la versión 1.104.4 y sin garantía de compatibilidad. Sin ella, con el MTU por defecto (1280), las respuestas del Mac de 1300 bytes o más no llegaban a Railway y el handshake TLS a Redis expiraba (medido: respuestas de hasta 1000 bytes pasaban, y 3000 bytes pasan con 1100). La causa probable está en la red del Mac, pero no se verificó. **Volver a probarla si cambia la versión de Tailscale** (en el contenedor o en el Mac) o la red.
- **Plan Free de Railway:** el crédito de 1 USD al mes se agota en unos 7 días con los servicios encendidos sin uso (medido en el proyecto anterior). No hay tope ni alerta configurados; se mitiga apagando los servicios al terminar cada sesión. La documentación describe alertas por correo (límite blando) y no aclara si el plan Free las admite ni qué ocurre al agotarse el crédito: verificarlo en el panel antes de depender de ello.
- **Cloud puede colgarse sin error** si pierde la tailnet o Redis (sin tiempo de espera ni healthcheck); no se reinicia solo.
- **Cloud puede inundar Redis** con streams propios (escribe en `fog:features:dead` y en `cloud:verdicts:*`); Redis tiene `maxmemory 200mb` con `noeviction`.
- **Cuenta de Railway tratada como afectada** por el incidente del 21/10/2026: todo valor anterior se descartó y nada se reutilizó.
- JWT sin revocación; los certificados de Redis vencen a los 365 días (13/11/2027); la contraseña maestra y el token del proxy viven solo en `backend/.secrets/`.
