# Despliegue remoto de SABRE.AI (DEPLOY07) · borrador

Estado (08/10/2026): proyecto `sabre-ai` en Railway con tres servicios (redis, cloud, frontend) desplegados desde `main`. Frontend público: https://frontend-production-0463.up.railway.app. Fog corre en el Mac (puerto 8011, base `sabre_expo`) y se expone con `scripts/fog_remoto.sh`. Ramas: `main` = producción desplegada; `dev/local` = entorno local para la Validación.

## 1. Arquitectura
Navegador → HTTPS → [Railway] frontend (nginx: estático + `/api`) → HTTPS + `X-Proxy-Token` → [Mac] túnel Cloudflare → Fog → PostgreSQL local.
Fog y Cloud hablan con [Railway] Redis por TLS 1.3 con autenticación mutua. Cloud llega a Redis por la red privada de Railway y no tiene dominio público.

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
- ACL: `user default off`; usuario `sabre` con contraseña aleatoria, solo claves `fog:*`, `cloud:*`, `auth:*` y solo los comandos de Fog y Cloud (`ping hello client|setinfo client|setname xadd xread xreadgroup xack xgroup xautoclaim xlen xtrim expire ttl incr incrby set del`). `redis-py` usa `INCRBY` para `incr`: se descubrió al probar.
- Sin persistencia, `maxmemory 200mb` + `noeviction`, `XADD ... MAXLEN ~ 100` (`STREAM_MAXLEN`) en `fog:features` y su dead-letter.
- Secretos: variables `REDIS_TLS_*_B64` y `REDIS_PASSWORD` → el entrypoint los escribe en `/dev/shm` con permisos 600 y las borra del entorno. Contenedor no root.
- Cliente: `REDIS_URL=rediss://...` + `REDIS_TLS_CA/CERT/KEY` (rutas). Verifica cadena y nombre del servidor. Sin las variables, modo local sin cambios.

Prueba local (puerto 6390): sin TLS → conexión cerrada; TLS sin certificado de cliente → I/O error; certificado sin contraseña → `NOAUTH`; `sabre` con `FLUSHALL`, `KEYS`, `CONFIG`, `GET` de clave ajena → `NOPERM`; TLS 1.2 → alerta `protocol version`.

## 5. Variables (solo en el panel o la CLI de Railway)
| Servicio | Variables |
|---|---|
| redis | `REDIS_PASSWORD`, `REDIS_TLS_CA_B64`, `REDIS_TLS_CERT_B64` (servidor), `REDIS_TLS_KEY_B64` |
| cloud | `REDIS_URL` (`rediss://sabre:…@redis.railway.internal:6379/0`), `REDIS_TLS_CA/CERT/KEY` (rutas; los PEM de Cloud escritos al arrancar) |
| frontend | `FOG_UPSTREAM`, `PROXY_SHARED_TOKEN`, `CLIP_MAX_MB` |
| Fog (Mac) | `ENTORNO=remoto`, `AUTH_USER`, `AUTH_PASSWORD_HASH`, `AUTH_JWT_SECRET`, `PROXY_SHARED_TOKEN`, `CORS_ORIGINS` vacío, `REDIS_URL=rediss://…`, `REDIS_TLS_*` |

PKI: `sh scripts/generar_pki_redis.sh <host-proxy> redis.railway.internal` → `backend/.secrets/redis/` (ignorado por git). Rotación: borrar esa carpeta, regenerar y actualizar las variables; contraseña de Redis, `AUTH_JWT_SECRET` y `PROXY_SHARED_TOKEN` con `openssl rand -base64 48`, cambiando el valor en ambos extremos y reiniciando.

## 6. Verificación (Parte D)
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

## 7. Operación el día de la exposición
1. `sh scripts/fog_nativo.sh` con `ENV_FILE=.secrets/fog_remoto.env` (puerto 8011, base `sabre_expo`).
2. `FOG_HOST_PORT=8011 PROXY_SHARED_TOKEN=… sh scripts/fog_remoto.sh start`: imprime la URL del túnel (cambia en cada arranque).
3. En Railway, servicio frontend: `FOG_UPSTREAM=<URL del túnel>` y reiniciar.
4. Al terminar: `fog_remoto.sh stop`.

## 8. Riesgos aceptados
Fog depende del Mac encendido; JWT sin revocación; plan gratuito con recursos limitados ($1 de crédito al mes); URL del túnel variable; los certificados de Redis vencen al año; la contraseña maestra y el token del proxy viven solo en `backend/.secrets/`.
