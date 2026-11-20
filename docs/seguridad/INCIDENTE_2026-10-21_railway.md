# Incidente Railway (21/10/2026): registro de evidencia, contención y rotación

Registro de SEC01. Mapeo orientativo a ISO/IEC 27001:2022 Anexo A (5.24 a 5.28); **no declara cumplimiento** de la norma.
Nunca se anotan valores de secretos: solo nombres, longitudes y huellas (`sha256` truncado a 8 caracteres).

## 1. Cronología
Las horas están en UTC; Lima = UTC−5.

| Fecha | Hecho | Fuente |
|---|---|---|
| 08/10/2026 | Última prueba remota archivada (`datos/archivo_prueba_remota/`, log del 05 al 08/10) | Archivo local |
| 10/10/2026 01:32 UTC | Arranque del túnel de Fog (`fog_remoto_url.txt` y `.pid`). `stop` no se ejecutó | Declarado en `prompts/SEGURIDAD/00_README_INCIDENTE.md`; los archivos ya no existen, no verificable |
| 21/10/2026 | Railway detecta acceso no autorizado a los sistemas donde guarda las variables de entorno; algunas se obtuvieron descifradas. Pide rotar todas las variables y revisar logs | [blog.railway.com/p/security-disclosure-wednesday-october-21st](https://blog.railway.com/p/security-disclosure-wednesday-october-21st) |
| 22/10/2026 | Cobertura de prensa | techcrunch.com (22/10/2026) |
| 21/10/2026 en adelante | Estado oficial del incidente | [status.railway.com/incident/QH8L8B3E](https://status.railway.com/incident/QH8L8B3E) |
| 27/10/2026 | El autor consulta las fuentes y abre el plan SEC (README del incidente) | README del incidente |
| Antes de SEC01 (fecha no registrada) | Contención del paso 0 completa, según el autor: túnel detenido, Redis público y despliegues de cloud y frontend retirados, cuenta Railway y GitHub asegurados | Declarado por el autor |
| 06/11/2026 | SEC01: evidencia (Parte A) y rotación completa (Parte B) | Este documento |
| 10/11/2026 | Railway publica el informe completo del incidente (escape del aislamiento en la infraestructura de builds y configuración OIDC errónea; alcance de hasta 1,85 % de los workspaces; 353 historiales de build leídos, "sealed variables included"; informe forense externo y denuncia al FBI aún en curso) | [blog.railway.com/p/incident-report-october-security-incident](https://blog.railway.com/p/incident-report-october-security-incident) |
| 13/11/2026 | DEPLOY09: segunda rotación, rediseño con Tailscale y verificación | Sección 11 de este documento |

La causa no fue publicada. Railway la atribuye a una campaña contra plataformas, no a la vulnerabilidad de PHP de la misma semana; SABRE.AI no usa PHP.

## 2. Activos afectados
Variables que estuvieron en Railway (inventario confirmado por el autor el 06/11/2026 con el contenido de cada servicio):

| Servicio | Variable | Qué permite a quien la tenga |
|---|---|---|
| frontend | `PROXY_SHARED_TOKEN` + `FOG_UPSTREAM` | Llegar a la API de Fog en el Mac sin pasar por el nginx; falta un JWT |
| cloud | `REDIS_URL` (usuario `sabre` y contraseña), `REDIS_TLS_CA/CERT/KEY` (cliente) | Conectarse a Redis por el TCP proxy: leer features y sugerencias, inyectar veredictos, borrar los contadores de bloqueo de login |
| redis | `REDIS_PASSWORD`, `REDIS_TLS_CERT_B64` y `REDIS_TLS_KEY_B64` (servidor), `REDIS_TLS_CA_B64` (solo certificado) | Suplantar al servidor Redis |
| frontend | `CLIP_MAX_MB` | Sin impacto |

**No estuvieron en Railway:** `AUTH_JWT_SECRET`, `AUTH_PASSWORD_HASH`, la clave de la CA de Redis y `POSTGRES_PASSWORD`.

## 3. Cadena de ataque posible (peor caso)
Token de proxy + URL del túnel + Redis para borrar el bloqueo de login, lo que permitiría fuerza bruta sin límite sobre la contraseña maestra; con un JWT válido, leer revisiones, clips y alias de tiradores en el Mac, o subir clips que procesan ffmpeg, OpenCV y YOLO en el Mac. Requiere que el túnel haya seguido vivo; no se puede comprobar (ver 4.1).

## 4. Evidencia recogida (Parte A, solo lectura, 06/11/2026)
| # | Control | Resultado |
|---|---|---|
| 4.1 | Túnel | `cloudflared` no corre; `fog_remoto_url.txt` y los `.pid` ya no existen. **Limitación:** Fog loguea a stdout y no existe log histórico de Fog ni del túnel para el 10/10 al 21/10; no se puede probar si el túnel estuvo activo en esa ventana. El único log de túnel archivado es del 05 al 08/10 |
| 4.2 | Revisiones, clips y veredictos en PostgreSQL desde el 10/10 | **No verificable.** La base real ya no existe: no quedan contenedores ni volumen con nombre del proyecto, y no hay respaldo (`RESPALDO_DIR` y `datos/respaldo_prohibido` vacíos). Ver DEF-31 en `docs_claude/contexto_sabre.md` para la pérdida anterior de la base de la Validación 1 |
| 4.3 | `fn_verificar_auditoria()` | **No verificable**, por lo mismo |
| 4.4 | Clips en `datos/storage` y `datos/evidencia` | 98 clips; 0 archivos creados o modificados desde el 10/10; último cambio 09/10/2026 22:11 (hora local). Los mtime son indicio, no prueba |
| 4.5 | Logs de Railway | No existen (el autor confirmó que no había nada que exportar) |
| 4.6 | Variable por servicio | Ver sección 2 |
| 4.7 | Secretos en el historial de git | `git log --all -p` en backend, frontend y repo raíz, con patrones de claves PEM, `rediss://usuario:clave@`, `$argon2` y asignaciones de `secret`/`token`/`password` de 16 o más caracteres: sin coincidencias. `gitleaks` y `ggshield` no estaban instalados y no se instalaron |

## 5. Acciones de contención (paso 0, a cargo del autor)
Cierre del túnel con `fog_remoto.sh stop`; eliminación del TCP proxy de Redis; retiro de los despliegues de cloud y frontend sin borrar el proyecto; cambio de contraseña, 2FA y revocación de tokens en la cuenta Railway; revisión de GitHub y del Mac. Fechas exactas no registradas.

## 6. Rotación (Parte B, 06/11/2026, rama `fix/SEC01`)
Script idempotente `scripts/rotar_secretos.sh`. Lo anterior se movió a `.secrets/_retirado_2026-10-27/` (permisos 700; incluye todas las generaciones de la PKI, `auth_maestro.txt`, `clave_prueba.txt`, el `fog_remoto.env` y el `proxy_token.txt` anteriores y una copia del `.env`). El autor lo borra al cerrar el incidente.

| Secreto | Longitud | Huella nueva |
|---|---|---|
| `AUTH_PASSWORD_HASH` (huella de la línea `AUTH_PASSWORD_HASH='…'`) | 118 | `ca2bb747` |
| `AUTH_JWT_SECRET` | 64 | `3b79c767` |
| `PROXY_SHARED_TOKEN` | 64 | `d2aee4f1` |
| `POSTGRES_PASSWORD` | 32 | `e8b774e2` |
| `REDIS_PASSWORD` (usuario `sabre`) | 62 | `b456c3b4` |
| PKI Redis: CA | n/a | `225f24d2` |
| PKI Redis: servidor | n/a | `e41f105b` |
| PKI Redis: cliente Fog | n/a | `ce20cdd4` |
| PKI Redis: cliente Cloud | n/a | `79468976` |

Notas: la PKI se reemplazó completa, incluida la CA (válida 365 días desde el 06/11/2026). El certificado de servidor lleva como nombres `redis.railway.internal` y `localhost`. `POSTGRES_PASSWORD` dejó de ser el valor de ejemplo de `.env.example`. La contraseña maestra nueva (mínimo 16 caracteres, ahora exigido por `crear_hash_password.py`) la tecleó el autor y no se guarda en disco.

**Verificación (06/11/2026):** Fog arranca en local con los secretos nuevos sobre un PostgreSQL vacío (migraciones aplicadas); `/eventos` responde 401 con un JWT firmado con el secreto anterior, 200 con uno firmado con el nuevo, y 403 con el token de proxy anterior. `pytest tests/` da 445 pasan y 2 saltadas (línea base de `main` con la misma base: 438 pasan y 3 saltadas); ruff sin hallazgos en ambos.

### 6.0 Verificación de la contraseña de PostgreSQL en el volumen real (FIX05, 19/11/2026)
Se probó contra el volumen real (`sabre-postgres-1`, puerto 5436) sin imprimir las contraseñas: la de `.secrets/postgres_password.txt` es **aceptada** y la antigua `sabre_local` es **rechazada**; la del `.env` era idéntica a la de `.secrets`. La rotación de SEC01 sí estaba aplicada en el volumen (no hizo falta `ALTER ROLE`). Desde FIX05 la contraseña tiene una sola fuente, `.secrets/postgres_password.txt`: se quitó del `.env` y los scripts la leen de ahí (`scripts/verificar_clave_postgres.sh` repite esta comprobación). Nota: durante FIX05 la herramienta de IA imprimió por error el valor que había en el `.env` (idéntico al de `.secrets`); queda en el historial de esa conversación y conviene rotarla.

### 6.1 Segunda rotación (DEPLOY09, 13/11/2026, `rotar_secretos.sh --forzar`)
Se rotó de nuevo todo menos el hash de la contraseña maestra, antes de cargar nada en el proyecto nuevo de Railway. Lo vigente pasó a `.secrets/_retirado_2026-10-27/forzado_<marca de tiempo>/`. La contraseña del rol `sabre` de PostgreSQL se actualizó con `ALTER ROLE` para que coincida con el archivo, y se comprobó la conexión por TCP.

Antes de esta rotación, el 13/11, se generaron a mano las contraseñas por usuario de Redis (`fog` `37b4e5e4`, `cloud` `20752ee9`) porque `.secrets/redis/` era anterior a SEC02 y solo tenía una contraseña; también quedaron retiradas.

| Secreto | Longitud | Huella vigente |
|---|---|---|
| `AUTH_PASSWORD_HASH` (sin cambio) | 118 | `ca2bb747` |
| `AUTH_JWT_SECRET` | 64 | `7d7f5083` |
| `PROXY_SHARED_TOKEN` | 64 | `53da32cf` |
| `POSTGRES_PASSWORD` | 32 | `194f5342` |
| `REDIS_PASSWORD_FOG` | 63 | `daa8f614` |
| `REDIS_PASSWORD_CLOUD` | 64 | `e254ba6f` |
| PKI Redis: CA | n/a | `39d53027` |
| PKI Redis: servidor | n/a | `971f33f9` |
| PKI Redis: cliente Fog | n/a | `efeb71a7` |
| PKI Redis: cliente Cloud | n/a | `178ef876` |

La PKI vigente (CA válida 365 días desde el 13/11/2026) lleva `localhost` como único nombre del servidor: en el diseño Tailscale Cloud alcanza Redis por un reenviador local de su contenedor, sin hostname público.

## 7. Indicadores revisados y resultado
Sin indicadores de compromiso en lo revisable: sin clips nuevos en disco, sin secretos en git, túnel cerrado. Lo no revisable (4.1 a 4.3, 4.5) impide descartar compromiso: no se puede demostrar que nadie inyectó revisiones o veredictos en la base anterior.

### 7.1 Consumo del proyecto anterior (panel Usage, revisado el 13/11/2026)
Total de 1,01 USD: memoria 0,99 USD (4.260 GB-minuto, unos 430 MB constantes), CPU 0,02 USD y tráfico de salida 0,0006 USD (10 MB). 4.260 GB-minuto entre 0,43 GB son unos 9.900 minutos: el crédito del plan Free se agotó en unos 7 días con los servicios encendidos sin uso.
- **Descarta** que alguien haya usado los contenedores: con 10 MB de salida en una semana no se extrajeron datos por ahí.
- **No descarta** el robo de variables, que ocurrió del lado de Railway y no aparece en el panel.
- Railway notificó por correo al autor que su cuenta se vio afectada; el autor no halló pruebas propias de ello. Se trata como cuenta afectada.

## 8. Riesgos residuales
- La ventana del 10/10 al 21/10 queda sin evidencia (sin logs de Fog, del túnel ni de Railway; sin base).
- Railway sigue sin tener los valores nuevos: el autor los pega en el panel después de SEC02. Hasta entonces el despliegue remoto no funciona, y `REDIS_URL_REMOTO` en `fog_remoto.env` apunta a `PENDIENTE:6379`. Si el nuevo TCP proxy tiene otro nombre, hay que reemitir el certificado de servidor.
- Durante SEC01 los valores anteriores de las variables de Railway se pegaron en la conversación con la herramienta de IA. Estaban comprometidos por el incidente y ya están rotados; el historial de esa conversación los conserva.
- Redis sigue con un único usuario (`sabre`); SEC02 lo separa.
- El respaldo de la base sigue sin definirse (`RESPALDO_DIR` vacío).

## 9. Lecciones aprendidas
- Los secretos que salen del Mac (Railway) deben ser los mínimos y de mínimo alcance; lo que no sale (JWT, hash, clave de la CA, base) limitó el daño posible.
- El túnel se dejó abierto 11 días sin que nada lo señalara; el cierre debe ser parte del procedimiento y verificable.
- Sin logs persistentes de Fog ni respaldo de la base no hay forma de probar qué pasó; exportar logs y respaldar son parte de la respuesta, no extras.
- `docker compose` y `testcontainers` fallaban en silencio en colima; el plugin no estaba instalado (se usó `docker-compose`).

## 10. Mapeo orientativo a ISO/IEC 27001:2022, Anexo A
| Control | Cómo lo recoge este registro |
|---|---|
| 5.24 Planificación y preparación de la gestión de incidentes | README del incidente y plan SEC01/SEC02 |
| 5.25 Evaluación y decisión sobre eventos de seguridad | Secciones 2, 3 y 7 |
| 5.26 Respuesta a incidentes | Secciones 5 y 6 |
| 5.27 Aprendizaje de los incidentes | Sección 9 |
| 5.28 Recopilación de evidencia | Sección 4 y la carpeta `_retirado`, conservada hasta el cierre |

## 11. Cierre (DEPLOY09, 13/11/2026)

**Qué se rotó.** Segunda rotación completa (sección 6.1) antes de cargar nada en Railway; los valores del proyecto anterior no se reutilizaron y el proyecto anterior se borró. Las claves de Tailscale usadas en las pruebas se revocaron y sus nodos se borraron.

**Arquitectura nueva.** En Railway solo `frontend` y `cloud`, unidos a una tailnet con Tailscale 1.104.4 y claves efímeras con etiqueta (`tag:frontend`, `tag:cloud`). No hay servicio Redis ni TCP proxy público, y Fog no tiene URL pública: Redis nativo (TLS 1.3, mTLS, ACL por usuario), Fog y PostgreSQL corren en el Mac y se publican a la tailnet solo durante una ventana con vencimiento. Detalle en `docs/manuales/historico/DESPLIEGUE_REMOTO_DEPLOY09_tailnet.md` (el despliegue vigente, desde DEPLOY11, está en `docs/manuales/DESPLIEGUE_REMOTO.md`).

**Verificación.** Resultados completos en la sección 6 de `historico/DESPLIEGUE_REMOTO_DEPLOY09_tailnet.md`; prueba de viabilidad previa en `PRUEBA_TAILSCALE_RAILWAY_2026-11-13.md`. Puntos que importan para el incidente:
- Ninguna credencial anterior al 06/11 es aceptada (JWT, token del proxy, contraseñas y certificados de Redis).
- Cada etiqueta llega a un único puerto del Mac, medido desde los contenedores.
- Revocar la clave y borrar el nodo cortó a Cloud en menos de 1 min 39 s y no volvió a unirse (5 min de observación).
- Consumo del proyecto anterior: ver 7.1. No hay indicadores de uso ajeno de los contenedores.

**Defectos encontrados y corregidos durante el cierre.** Cloud y Fog usaban `redis://localhost:6379/0` sin TLS cuando faltaba `REDIS_URL` y se reiniciaban en bucle; ahora, con `ENTORNO=remoto`, se niegan a arrancar nombrando la variable (`require_redis_remoto`); lo mismo el frontend sin `PROXY_SHARED_TOKEN`. El frontend desplegado antes del segundo intento corría la imagen genérica sin Tailscale porque los proyectos nuevos de Railway ignoran `railway.json`. Un MTU de 1280 en el túnel impedía que respuestas de 1300 bytes o más llegaran a Railway (se fijó 1100).

**Riesgos aceptados.** Los de la sección 8 de `historico/DESPLIEGUE_REMOTO_DEPLOY09_tailnet.md`: Fog depende del Mac encendido; `TS_DEBUG_MTU=1100` es una variable de depuración ligada a Tailscale 1.104.4 y hay que volver a probarla si cambia la versión; el plan Free no tiene tope ni alerta configurados; Cloud se colgaba sin error si perdía la tailnet (corregido en FIX04); el escenario de peor caso de la sección 3 sigue sin poder descartarse para lo que estuvo en Railway antes del 21/10/2026 (la cuenta se trata como afectada porque Railway lo notificó al autor, aunque este no halló pruebas propias).

**Pendiente.** Confirmar con el panel si el plan Free admite alertas de uso; DEF-32 (RF-01 sin implementar), registrado en `contexto_sabre.md`.
