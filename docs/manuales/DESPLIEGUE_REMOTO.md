# Despliegue remoto de SABRE.AI (DEPLOY07) · borrador

Estado: preparación local terminada; **Railway aún no creado** (falta `railway login` del autor, publicar `main` y las decisiones de la sección 6). Las secciones 4 y 5 se completan con la evidencia de la Parte D.

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

## 6. Pendiente
Crear servicios, pruebas 1–13 de la Parte D y tabla de controles del Anexo A.
Riesgos aceptados: Fog depende del Mac encendido; JWT sin revocación; plan gratuito con recursos limitados; URL del túnel variable.
