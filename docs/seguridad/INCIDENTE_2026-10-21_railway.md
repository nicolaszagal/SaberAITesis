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

## 7. Indicadores revisados y resultado
Sin indicadores de compromiso en lo revisable: sin clips nuevos en disco, sin secretos en git, túnel cerrado. Lo no revisable (4.1 a 4.3, 4.5) impide descartar compromiso: no se puede demostrar que nadie inyectó revisiones o veredictos en la base anterior.

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
