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

PKI: la genera `scripts/rotar_secretos.sh` (llama a `generar_pki_redis.sh redis.railway.internal localhost`; `REDIS_SAN_HOSTS` cambia los nombres) → `backend/.secrets/redis/` (ignorado por git).

**Rotación (procedimiento usado en SEC01, 06/11/2026)**
1. Desde `backend/`: `sh scripts/rotar_secretos.sh`. Mueve lo vigente a `.secrets/_retirado_2026-10-27/` y genera `AUTH_JWT_SECRET`, `PROXY_SHARED_TOKEN`, `POSTGRES_PASSWORD`, la PKI completa (CA incluida) y la contraseña de Redis; pide la contraseña maestra por `getpass` (mínimo 16 caracteres) y escribe el hash. Actualiza `POSTGRES_PASSWORD` en `.env` y regenera `.secrets/fog_remoto.env`. Imprime solo nombre, longitud y huella.
2. `REDIS_HOST_REMOTO=host:puerto sh scripts/rotar_secretos.sh --forzar` rota de nuevo todo menos el hash de la contraseña (para cambiarla, borrar `.secrets/auth_password_hash.env` antes). Sin esa variable, `REDIS_URL_REMOTO` queda en `PENDIENTE:6379`.
3. Pegar en el panel de Railway los valores nuevos (redis: `REDIS_PASSWORD` y `REDIS_TLS_*_B64` de servidor; cloud: `REDIS_URL` y `REDIS_TLS_*` de `cloud.*`; frontend: `PROXY_SHARED_TOKEN`), sin imprimirlos en la terminal ni en chats.
4. Reiniciar Fog: el JWT anterior pasa a dar 401 y el token de proxy anterior, 403.
5. Al cerrar el incidente, el autor borra `_retirado_2026-10-27/`. Registro: `docs/seguridad/INCIDENTE_2026-10-21_railway.md`.

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

### Segundo hallazgo: el frontend caía sin túnel
nginx resolvía `FOG_UPSTREAM` al arrancar; con el túnel cerrado el contenedor fallaba (`host not found in upstream`) y Railway lo detenía. Ahora el nombre se resuelve en cada petición (`resolver` + variable): sin túnel, `/` y `/healthz` responden 200 y `/api/` responde 502. Prueba: `SaberAISoftware/deploy/railway/probar_nginx.sh` (falló antes del cambio, pasa después).

## 7. Operación el día de la exposición

Todo se ejecuta en el Mac del autor. `BACKEND` = `/Users/darkarcher/Documents/Claude/Projects/Tesis/Software/backend`. Los comandos de los pasos 2 a 4 se escriben en **dos terminales** abiertas en esa carpeta (`cd BACKEND`).

Servicios en la nube (Railway: frontend, cloud, redis) quedan encendidos y no se tocan. Lo único que se arranca y se apaga a mano es **Fog + el túnel**. Fog usa la base `sabre_expo` (no la `sabre` del piloto).

### 1. Antes de empezar (una vez, 10 min antes)
Desde cualquier terminal, en `BACKEND`:
1. Docker (Colima) encendido y PostgreSQL arriba:
   ```bash
   docker ps --format '{{.Names}} {{.Status}}' | grep sabre-postgres-1
   ```
   Si no aparece: `colima start` y luego
   `docker compose -f docker-compose.yml -f docker-compose.nativo.yml up -d postgres`.
2. Sesión de Railway: `railway whoami` debe mostrar el usuario. Si no: `railway login`.
3. Mac conectado a corriente y a internet. No tocar el Fog antiguo del puerto 8001 (es del piloto).

### 2. Terminal 1: arrancar Fog (se queda abierta)
```bash
cd /Users/darkarcher/Documents/Claude/Projects/Tesis/Software/backend
ENV_FILE=.secrets/fog_remoto.env sh scripts/fog_nativo.sh
```
Espere hasta ver `Uvicorn running on http://0.0.0.0:8011` (30–60 s: aplica migraciones y carga el modelo de pose). No cierre esta terminal: cerrarla apaga Fog.

### 3. Terminal 2: verificar Fog y abrir el túnel
```bash
cd /Users/darkarcher/Documents/Claude/Projects/Tesis/Software/backend
curl -s -H "X-Proxy-Token: $(cat .secrets/proxy_token.txt)" localhost:8011/health
```
Debe responder `{"fog":"ok","redis":"ok","postgres":"ok"}`. Si `redis` no es `ok`, revise que el servicio redis de Railway esté Online (`railway service list`). Luego:
```bash
FOG_HOST_PORT=8011 PROXY_SHARED_TOKEN=$(cat .secrets/proxy_token.txt) sh scripts/fog_remoto.sh start
```
Imprime `URL del túnel de Fog: https://xxxx.trycloudflare.com` y lanza `caffeinate` (el Mac no se suspende). **La URL cambia en cada arranque.** También queda guardada en `datos/fog_remoto_url.txt`.

### 4. Terminal 2: apuntar el frontend de Railway al túnel nuevo
```bash
railway variable set --service frontend FOG_UPSTREAM="$(cat datos/fog_remoto_url.txt)"
```
(sin barra final). Cambiar la variable reinicia el frontend; tarda ~1 min. Espere a `Online`:
```bash
railway service list | grep -A1 frontend
```
Alternativa por el panel: railway.com → proyecto `sabre-ai` → servicio `frontend` → Variables → `FOG_UPSTREAM` → Deploy.

### 5. Comprobar la cadena completa
```bash
curl -s https://frontend-production-0463.up.railway.app/api/health
```
Debe responder `{"fog":"ok","redis":"ok","postgres":"ok"}`. Si responde 502, ver la tabla de problemas. Después abra https://frontend-production-0463.up.railway.app e ingrese con el usuario `arbitro` y la contraseña de `.secrets/auth_maestro.txt`. Haga una prueba con un clip antes de la exposición.

### 6. Durante la exposición
- Dejar las dos terminales abiertas y el Mac despierto.
- El clip se procesa en Fog (6–8 s en las pruebas); si el Wi-Fi del recinto es lento, usar datos móviles en el Mac o compartir internet.

### 7. Al terminar
1. Terminal 2: `sh scripts/fog_remoto.sh stop` (cierra túnel y `caffeinate`).
2. Terminal 1: `Ctrl+C` (apaga Fog).
3. El frontend de Railway seguirá en línea (muestra el login, `/api` responde 502 hasta el próximo túnel). Para no gastar crédito, puede pausar los tres servicios en el panel de Railway.

### Problemas frecuentes
| Síntoma | Causa | Solución |
|---|---|---|
| `/api/...` responde 502 o el login dice error de conexión | El túnel está cerrado o `FOG_UPSTREAM` tiene una URL vieja | Repetir pasos 3 y 4; confirmar que la URL de `datos/fog_remoto_url.txt` es la que está en Railway (`railway variable list --service frontend`) |
| `/api/...` responde 403 | `PROXY_SHARED_TOKEN` distinto entre Railway y Fog | El valor de `.secrets/proxy_token.txt` debe ser el de la variable del servicio `frontend` |
| Login responde 429 | 5 intentos fallidos desde su IP (bloqueo de 15 min) | Esperar 15 min |
| Login responde 401 con la contraseña correcta | Fog se arrancó sin `.secrets/fog_remoto.env` | Reiniciar Fog con el comando del paso 2 |
| `fog_nativo.sh` dice que postgres no responde en 127.0.0.1:5436 | PostgreSQL de Docker apagado | Paso 1.1 |
| `Address already in use` | Otro Fog usa el puerto | Confirmar que no queda un Fog remoto previo: `lsof -iTCP:8011 -sTCP:LISTEN` y cerrarlo con Ctrl+C en su terminal |
| La sugerencia tarda más de 60 s o no llega | Cloud caído o Redis sin conexión | `railway service list` (cloud y redis `Online`); `railway logs --service cloud` |

## 8. Riesgos aceptados
Fog depende del Mac encendido; JWT sin revocación; plan gratuito con recursos limitados ($1 de crédito al mes); URL del túnel variable; los certificados de Redis vencen al año; la contraseña maestra y el token del proxy viven solo en `backend/.secrets/`.
