# Despliegue remoto de SABRE.AI (DEPLOY11)

> **Solo para el autor.** Cómo desplegar el frontend y Cloud en Railway, y cómo emitir y revocar los tokens de los nodos Fog. Los revisores no leen este documento: reciben una URL y un archivo de token y siguen el modo B de [`GUIA_EJECUCION.md`](GUIA_EJECUCION.md).
>
> El diseño anterior (DEPLOY09: Redis nativo, Tailscale y un solo Fog) está en [`historico/DESPLIEGUE_REMOTO_DEPLOY09_tailnet.md`](historico/DESPLIEGUE_REMOTO_DEPLOY09_tailnet.md). Su retiro se explica en la sección 8.

## 1. Arquitectura

Principio: **en el equipo del usuario no entra nada**. Fog escucha solo en `127.0.0.1`; el navegador del usuario habla con su Fog local, y Fog sale por HTTPS hacia Cloud.

```
Navegador ──HTTPS──> [Railway] frontend (nginx, solo estático)
    │
    └──HTTP http://localhost:8001──> Fog del usuario (127.0.0.1) ── PostgreSQL propio
                                          │
                                          └──HTTPS POST /v1/clasificar + Bearer <token del nodo>──> [Railway] cloud-http
```

Diagrama: [`../uml/UML7_Despliegue.png`](../uml/UML7_Despliegue.png). Contrato de `POST /v1/clasificar`: [`../../CONTRATO_API.md`](../../CONTRATO_API.md), sección 5.1.

- **Frontend (Railway).** Imagen estática (`SaberAISoftware/deploy/railway/Dockerfile`): sin `/api`, sin reenviador y sin Tailscale. El nodo Fog no se fija al construir: el usuario lo escribe en el login ("Nodo Fog", `http://localhost:8001` por defecto) y el navegador lo recuerda.
- **Cloud (Railway).** `cloud/Dockerfile`. Sin `REDIS_URL`, corre solo con HTTP (`POST /v1/clasificar`, `GET /health`) y **no persiste nada**. Su `PORT` lo asigna Railway.
- **Fog (equipo de cada usuario).** `CLOUD_TRANSPORTE=http`: no usa Redis ni PKI. Autentica ante Cloud con un token propio de su nodo.
- **Autenticación.** Cada Fog tiene su propio JWT (`AUTH_JWT_SECRET`): un usuario existe solo en su nodo. Sin proxy no hay `PROXY_SHARED_TOKEN`: la protección es el JWT, CORS y la escucha en loopback.

## 2. Servicios de Railway

Proyecto `sabre-ai-tailscale` (el nombre es histórico). **El plan Free permite 3 servicios por proyecto.** Estado tras DEPLOY11:

| Servicio | Contenido | Dockerfile (`RAILWAY_DOCKERFILE_PATH`) | Dominio |
|---|---|---|---|
| `cloud-http` | Cloud con HTTP | `cloud/Dockerfile` | `cloud-http-production.up.railway.app` |
| `frontend` | frontend estático | `deploy/railway/Dockerfile` (antes la imagen con Tailscale y proxy; ahora la estática) | `frontend-production-23fc2e14.up.railway.app` |
| `cloud` | Cloud del diseño de Tailscale | `cloud/Dockerfile` | sin dominio, **sin usar** |

Los dominios los asigna Railway y cambian si el servicio se crea de nuevo. `cloud` conserva sus variables selladas del camino anterior (`REDIS_URL`, `REDIS_TLS_*_B64`, `TS_AUTHKEY`) sin tocar: no se borraron porque no se pueden recuperar y el retiro del camino de la tailnet espera la aprobación del autor (sección 8).

### Variables

| Servicio | Variable | Valor |
|---|---|---|
| `cloud-http` | `RAILWAY_DOCKERFILE_PATH` | `cloud/Dockerfile` |
| `cloud-http` | `CLOUD_NODOS_SHA256` | entradas `nombre:hash`, ver sección 3 |
| `cloud-http` | `ENTORNO` | `remoto` (apaga `/docs`, `/redoc` y `/openapi.json`) |
| `cloud-http` | opcionales | `CLOUD_HTTP_MAX_BODY_BYTES` (2 MiB), `CLOUD_HTTP_LIMITE_PETICIONES` (30) y `CLOUD_HTTP_LIMITE_VENTANA_S` (60), `CLOUD_HTTP_PETICION_TIMEOUT_S` (20) |
| `frontend` | `RAILWAY_DOCKERFILE_PATH` | `deploy/railway/Dockerfile` |
| `frontend` | `FOG_ORIGENES_EXTRA` | opcional: orígenes `https://` de Fog remotos que la CSP debe permitir, separados por espacios. Sin comodín: un valor inválido impide arrancar el contenedor |

La CSP del frontend es `connect-src 'self' http://localhost:* http://127.0.0.1:*` más `FOG_ORIGENES_EXTRA`. No hay comodín `https:`.

**Sellado.** `CLOUD_NODOS_SHA256` solo contiene hashes SHA-256 de tokens de 256 bits, no los tokens. La CLI de Railway no puede sellar una variable: se carga con `railway variables --set` y el autor la sella en el panel (Variables → ⋮ → Seal) si quiere que no se vuelva a mostrar.

Los proyectos nuevos de Railway ignoran `railway.json`: el Dockerfile se elige por `RAILWAY_DOCKERFILE_PATH` y la política de reinicio (On Failure, 3 reintentos) se fija en el panel de cada servicio.

## 3. Tokens de nodo: emitir y revocar

Cloud guarda **solo hashes SHA-256** de los tokens, con el nombre de cada nodo, en `CLOUD_NODOS_SHA256`. Formato: entradas `nombre:hash` separadas por comas o saltos de línea; `nombre` en minúsculas, dígitos, `-` y `_` (1 a 32); `hash` de 64 hexadecimales. Una variable mal formada impide arrancar Cloud (el mensaje nombra la variable y nunca muestra hashes).

**Emitir** (en el equipo del autor, desde `backend/`):

```bash
sh scripts/emitir_token_nodo.sh <nombre>
```

- Escribe el token en `~/.sabre/tokens/<nombre>.token` (permisos 600, carpeta 700, **fuera del repo**; `TOKENS_DIR` cambia la carpeta y el script se niega a usar una dentro del repo). **No imprime el token.**
- Muestra solo la línea `nombre:hash`. Agréguela a `CLOUD_NODOS_SHA256` y despliegue:

  ```bash
  railway variables -s cloud-http --set "CLOUD_NODOS_SHA256=nicolas:<hash>,revisor1:<hash>"   # redespliega Cloud
  ```
- No reemplaza un token existente sin `--forzar` (reemplazarlo invalida el anterior cuando se actualiza Railway).
- El autor entrega **el archivo** por un canal seguro. El revisor lo instala con `sh scripts/instalar_fog.sh importar-token <archivo>`.

**Revocar.** Quite la entrada del nodo de `CLOUD_NODOS_SHA256` y vuelva a cargar la variable (Railway redespliega Cloud). El token deja de valer en ~25 s (medido). El Fog de ese nodo sigue funcionando, pero sus revisiones quedan en "Clasificación no disponible" (`timeout`) y su log dice `Cloud rechazó el token de este nodo (401)`. Borre también el archivo del token.

**Límites por petición** (todos configurables, ver la tabla de variables): cuerpo máximo de 2 MiB (413), 30 peticiones por nodo y por minuto (429) y 20 s por petición (504, compatible con los 60 s de RNF-04). Los logs de Cloud llevan el nombre del nodo, el código y el tiempo (`[nicolas] POST /v1/clasificar -> 200 en 23 ms`), nunca el contenido ni el token.

## 4. Desplegar

Desde la carpeta de cada repo, con el proyecto enlazado (`railway status`):

```bash
cd backend          && railway up -s cloud-http --ci
cd SaberAISoftware  && railway up -s frontend   --ci
```

Comprobaciones (medidas el 20/11/2026):

```bash
curl -s https://<dominio de cloud-http>/health                                    # {"status":"ok"}
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://<dominio de cloud-http>/v1/clasificar -d '{}'   # 401
curl -s https://<dominio del frontend>/healthz                                     # ok
```

En los logs de Cloud debe aparecer `Cloud HTTP escuchando en 0.0.0.0:<PORT> (nodos: ...)` y **no** `Cloud escuchando 'fog:features'`.

**Apagar** al terminar la ventana de revisión: `railway down -s cloud-http -y` y `railway down -s frontend -y` (despliegues en `REMOVED`).

### El Fog del autor (modo remoto)

```bash
sh scripts/instalar_fog.sh modo --remoto --cloud-url https://<dominio de cloud-http> --frontend-url https://<dominio del frontend>
sh scripts/instalar_fog.sh importar-token ~/.sabre/tokens/nicolas.token
sh scripts/instalar_fog.sh probar --remoto      # 10 clips clasificados a través de Cloud por HTTP
sh scripts/fog_nativo.sh --remoto
```

`modo --remoto` escribe `CLOUD_TRANSPORTE=http`, `CLOUD_URL` y `CORS_ORIGINS` en `.secrets/fog_remoto.env`, conserva el resto de ese archivo y **quita `PROXY_SHARED_TOKEN`**. Con `http`, `verificar`, `instalar` y `fog_nativo.sh` no piden Redis y el compose usa el perfil `docker-compose.http.yml` (solo PostgreSQL).

## 5. Verificación de DEPLOY11 (20/11/2026)

Equipo: MacBook Air Apple M4, macOS 27.0.1; Cloud y frontend en Railway; Fog nativo (`FOG_DEVICE=cpu`) con una base de prueba aparte (`sabre_d11`); clip ContrattackA_0071 con la luz de A en el cuadro 29.

**Extremo a extremo local** (Cloud en contenedor solo con HTTP y sin `REDIS_URL`; Fog con `http`; frontend en `http://localhost:8099`): sugerencia ContrattackA con 0,847; veredicto registrado (200). Los logs de Cloud muestran el nodo y el tiempo (23 ms) y ningún contenido.

**Equivalencia (`instalar_fog.sh probar`, 10 clips de referencia, misma cota):**

| Modo | Clases iguales | Diferencia máxima | Keypoints idénticos |
|---|---|---|---|
| A, local (Redis, LSTM local) | 10/10 | 0,0 | 10/10 |
| Remoto, contra Cloud local en Docker por HTTP | 10/10 | 0,0 | 10/10 |
| Remoto, contra Cloud en Railway por HTTPS | 10/10 | 0,0 | 10/10 |

**Flujo completo en el navegador, con el despliegue real** (Chromium 153, frontend de Railway → Fog del Mac en `http://localhost:8001` → Cloud de Railway): login, combate, clip con la luz de A, sugerencia **Contraataque (85 %)**, trazos, razonamiento y veredicto (200), sin fallos de red. El razonamiento de este clip sale "Evidencia insuficiente" por un hueco de detección de VER en el tramo clave (es de la pose, igual por Redis o por HTTP).

**Latencia de una pista** (8 corridas del mismo clip, ya con el modelo caliente, Fog del Mac → Cloud de Railway, desde que el navegador envía el clip hasta tener la sugerencia):

| | min | mediana | máx |
|---|---|---|---|
| Tiempo total | 9,5 s | 9,8 s | 10,1 s |
| Solo la ida y vuelta a Cloud | 1,0 s | 1,1 s | 1,25 s |

Comparación con ESTRES01 (1 pista, local: p95 14,8 s): **no es la misma carga**. ESTRES01 usó clips distintos y su tiempo lo domina la pose (13,5 s); aquí el clip es corto y, descontada la ida y vuelta a Cloud, el resto (pose y features) ronda los 8,7 s. Lo comparable es el componente de Cloud: en ESTRES01 la espera de Cloud fue 0,00 s (Redis local) y por HTTPS hacia Railway es ~1,1 s, es decir, **el modo remoto agrega ~1,1 s por revisión** sobre un presupuesto de 60 s (RNF-04).

**Aislamiento y revocación** (un segundo Fog en el mismo Mac, con otra base y otro token: no hubo una segunda máquina):
- Cada Fog tiene su base: tras las pruebas, la base del nodo 1 tenía 10 revisiones y la del nodo 2, 1. Cloud no guarda nada: no hay dónde ver datos de otro nodo, y sus logs distinguen los nodos por nombre (`[nicolas]`, `[revisor-prueba]`).
- Revocación: se quitó `revisor-prueba` de `CLOUD_NODOS_SHA256`; Cloud redesplegó en ~24 s y la siguiente revisión de ese Fog quedó en "Clasificación no disponible" (`timeout`) con el 401 en ambos logs. El nodo del autor siguió funcionando.

**Navegadores** (frontend por HTTPS contra un Fog en `http://localhost:8001`; `e2e-navegadores/` en el repo del frontend). **Hay una regla que depende del origen:** una página en `https://localhost` es de loopback y no activa ninguna restricción, así que la prueba solo vale con el frontend en un origen público (el de Railway).

| Navegador | Sin permiso | Con permiso | Qué ve el usuario |
|---|---|---|---|
| Chrome / Edge (Chromium 153; Chrome 157 real) | **Bloquea** (`Permission was denied for this request to access the loopback address space`) | Conecta; flujo completo verificado | Al pulsar "Probar conexión" el navegador pide permiso de acceso a "aplicaciones y servicios del dispositivo" (red local); con **Permitir** funciona y no vuelve a preguntar. En la automatización no hay diálogo: se concede por API y no se observó el diálogo con una persona |
| Firefox (153 o posterior) | no se pudo ejecutar | no se pudo ejecutar | La documentación de Mozilla describe un aviso parecido, activado por defecto desde Firefox 153. **No verificado**: Playwright no abrió Firefox dentro del entorno de pruebas (macOS niega las extensiones de sandbox). Hay que probarlo a mano |
| Safari / WebKit | **Bloquea siempre** como contenido mixto (`requested insecure content from http://localhost:8001`) | no hay permiso que conceder | "No se pudo conectar con el servidor" con una explicación: Safari no permite que una página `https://` hable con `http://localhost`. **No soportado**: usar Chrome, Edge o Firefox |

Según la documentación de Chrome para desarrolladores, el control es el permiso del usuario más CORS normal (los encabezados `Access-Control-*Private-Network` están en desuso y no hacen falta). Las políticas de empresa (`LocalNetworkAccessAllowedForUrls`) pueden conceder el permiso por adelantado.

## 6. Costo

Tarifas de Railway (docs.railway.com/pricing, consultadas el 20/11/2026): memoria 10 USD/GB·mes, CPU 20 USD/vCPU·mes, salida de red 0,05 USD/GB, cobrado por minuto.

**Estimación** (no es una factura): se usaron las mediciones locales de las mismas imágenes en reposo (Cloud: 197 MiB y 0,2 % de CPU con el modelo cargado; nginx: 10 MiB y 0 % de CPU), siempre encendidos 7 días:

| | USD por semana |
|---|---|
| `cloud-http` (memoria 0,19 GB + CPU ≈ 0) | ≈ 0,45 |
| `frontend` estático (10 MiB) | ≈ 0,02 |
| Salida de red (respuestas de ~1 KB y un bundle de ~1 MB por visita) | < 0,01 |
| **Total, con la ventana de revisión continua** | **≈ 0,5** |

**Costo anterior (DEPLOY09, medido en el proyecto previo y registrado en el documento histórico):** con el sidecar de Tailscale y el reenviador en ambos servicios, el crédito de 1 USD se agotaba en unos 7 días, es decir ≈ 1 USD por semana. El diseño actual cuesta aproximadamente la mitad. La cifra de Railway por servicio no se midió en el panel (la CLI no la expone): confírmela en *Usage* tras la ventana real.

## 7. Operación el día de la revisión

1. **Antes:** `railway whoami`; Docker (Colima) y PostgreSQL arriba en el Mac del autor.
2. **Encender:** `railway up -s cloud-http --ci` y `railway up -s frontend --ci` (o reiniciar los despliegues). Comprobar la sección 4.
3. **Fog del autor:** `sh scripts/fog_nativo.sh --remoto` (requiere `probar --remoto` aprobada para este commit).
4. **Revisores:** reciben la URL del frontend y su archivo de token; siguen el modo B de [`GUIA_EJECUCION.md`](GUIA_EJECUCION.md).
5. **Al terminar:** `railway down -s cloud-http -y` y `railway down -s frontend -y`.

### Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| Todas las revisiones salen "no disponible" por `timeout` y el log de Fog dice `Cloud rechazó el token de este nodo (401)` | Token revocado, mal copiado o de otro nodo: reemitir con `emitir_token_nodo.sh --forzar`, actualizar `CLOUD_NODOS_SHA256` y reimportar |
| `Cloud ... 429` | Más de 30 peticiones por minuto del mismo nodo |
| El login dice "No se pudo conectar con el servidor" | Fog apagado, `CORS_ORIGINS` sin el origen del frontend, o el navegador no tiene permitido el acceso a la red local (ver la tabla de navegadores) |
| Cloud no arranca y dice `CLOUD_NODOS_SHA256: ...` | La variable está mal formada (formato `nombre:hash`, hash de 64 hexadecimales) |
| El contenedor del frontend no arranca y dice `FOG_ORIGENES_EXTRA` | Un origen no es `https://host[:puerto]` (sin comodines ni rutas) |

## 8. Camino de la tailnet (DEPLOY09): retirado

Retirado de `main` el 20/11/2026 con la aprobación del autor, en un commit propio, y conservado en la rama **`historico/tailnet`** de backend y de frontend (la rama sale del `main` anterior al retiro). Se quitó: el sidecar de Tailscale y el reenviador `socat` de las imágenes de Cloud y del frontend, `deploy/tailscale/` (incluida `politica.hujson`), `scripts/fog_remoto.sh`, `scripts/prueba_tailnet.sh`, `scripts/prueba_revocacion_tailnet.sh`, el proxy `/api` de DEPLOY03 (`docker-compose.remoto.yml`, `proxy/`, `scripts/prueba_remota.sh`) y la imagen vieja del frontend (`deploy/railway/Dockerfile` con proxy `/api`), cuyo lugar toma la imagen estática. El Redis del modo A se queda.

Para volver a ese diseño: `git switch historico/tailnet`. Siguen en `main`, sin uso en el modo remoto, el Redis nativo con PKI (`scripts/redis_nativo.sh`, `generar_pki_redis.sh`, `rotar_secretos.sh`) y el soporte `rediss://` de Cloud y Fog; son candidatos a retirarse si el autor lo decide. El servicio `cloud` de Railway conserva sus variables selladas del camino anterior sin usar: bórrelo cuando quiera (el plan Free permite 3 servicios).

## 9. Riesgos aceptados

- **El navegador necesita permiso de red local** (Chrome, Edge y Firefox) y Safari no está soportado con un Fog `http://localhost`. Quien necesite Safari tendría que servir su Fog por `https://` con un certificado de confianza: no está implementado ni probado.
- **Fog depende del equipo del usuario encendido** y de su PostgreSQL.
- **El token de nodo vive en un archivo** del equipo del usuario (permisos 600): quien lo copie puede clasificar como ese nodo hasta que se revoque. Cloud no limita por IP.
- **Cloud público en internet**, protegido por token de 256 bits, límite de cuerpo, de peticiones y de tiempo. No hay limitación por IP para peticiones sin token (rechazadas con 401 antes de leer el cuerpo completo).
- **Plan Free de Railway:** 3 servicios por proyecto y crédito limitado; sin tope ni alerta configurados. Se mitiga apagando los servicios al terminar.
- **Cuenta de Railway tratada como afectada** por el incidente del 21/10/2026 (`../seguridad/INCIDENTE_2026-10-21_railway.md`): nada de lo anterior a esa fecha se reutilizó.
- JWT sin revocación; el secreto y la clave de cada Fog viven solo en su equipo.
