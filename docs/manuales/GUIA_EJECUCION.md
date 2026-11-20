# Guía de ejecución de SABRE.AI

Cómo arrancar, usar y detener el sistema ya instalado ([`GUIA_INSTALACION.md`](GUIA_INSTALACION.md)). Hay dos modos: el A es local y el B usa el frontend y Cloud desplegados con **su propio Fog**.

| Modo | Qué es | Para quién |
|---|---|---|
| **A · Local, sin hardware** | Fog, Cloud, Redis, PostgreSQL y frontend en su equipo. Carga manual de un clip con las luces marcadas a mano | Revisores |
| **B · Fog propio con frontend y Cloud desplegados** | El frontend y Cloud están en Railway; usted corre solo **su Fog** (y su PostgreSQL) en su equipo. El Fog sale por HTTPS a Cloud con un token de su nodo; no necesita Redis ni Tailscale | Revisores que reciben una URL y un archivo de token |

Todos los comandos se corren desde `<carpeta-del-proyecto>/backend`. Si instaló con otra base o puertos (`POSTGRES_DB_NAME`, `POSTGRES_HOST_PORT`, `REDIS_HOST_PORT`, `FOG_HOST_PORT`), tenga las mismas variables exportadas en cada terminal: los scripts las leen del entorno.

---

## Modo A · Local, sin hardware

### A.1 Encender Docker (macOS con Colima)

```bash
colima start --cpu 2 --memory 4
```

Debe verse `colima is running using macOS Virtualization.Framework`. Si ya está encendido, el comando lo dice y no hace nada. En Linux, `sudo systemctl start docker`.

### A.2 Levantar PostgreSQL, Redis, Cloud y el frontend

```bash
sh scripts/compose.sh -f docker-compose.yml -f docker-compose.nativo.yml up -d --build
```

`compose.sh` pasa a Docker Compose la contraseña de PostgreSQL de `.secrets/postgres_password.txt`. `docker-compose.nativo.yml` publica PostgreSQL y Redis solo en `127.0.0.1` y deja a Fog fuera de Docker. La primera vez construye las imágenes de Cloud (torch) y del frontend: **unos 5 minutos**. Debe terminar con líneas `Container ... Started` / `Healthy` para `postgres`, `redis`, `cloud` y `frontend`. Compruebe:

```bash
docker ps --format '{{.Names}} {{.Status}}'
```

Debe verse `sabre-postgres-1`, `sabre-redis-1` y `sabre-frontend-1` en `healthy` (el frontend puede figurar `health: starting` unos segundos) y `sabre-cloud-1` en `Up` (el prefijo `sabre-` es el nombre del proyecto de Compose).

### A.3 Arrancar Fog

En **otra terminal** (queda abierta mientras use el sistema):

```bash
cd <carpeta-del-proyecto>/backend
sh scripts/fog_nativo.sh
```

Debe verse (los números varían):

```text
modo local con cpu: no exige equivalencia
Respaldo al día (0 revisiones en 'sabre').
Ya hay un modelo activo (lstm6class-20260928_141021); no se registra 20260928_141021.
INFO:     Started server process [N]
... INFO:fog:Cargando modelo YOLO y extractor de features (192-dim)...
... INFO:fog:Fog listo.
INFO:     Uvicorn running on http://0.0.0.0:8001 (Press CTRL+C to quit)
```

Fog quedó listo en **5 s** y **7 s** en las dos mediciones. Si la base tiene revisiones sin respaldar, `fog_nativo.sh` lo avisa con un recuadro `FALTA RESPALDAR: N revisiones nuevas ...` (y "Respaldo al día (N revisiones ...)" si no): ver la sección de respaldos. No detiene el arranque. Compruebe:

```bash
curl -s -w " %{http_code}\n" http://localhost:8001/health
```

Debe verse `{"fog":"ok","redis":"ok","postgres":"ok"} 200`.

### A.4 Iniciar sesión, configurar el combate y cargar un clip

El manual de usuario describe cada pantalla con capturas ([`MANUAL_USUARIO.md`](MANUAL_USUARIO.md)). Aquí, el recorrido mínimo:

1. Abra `http://localhost:8081` en Chrome. Debe verse la pantalla **"Iniciar sesión"**. Escriba el usuario y la contraseña maestra que eligió al instalar y pulse **Ingresar**. Debe verse el encabezado SABRE.AI, `Modelo activo: lstm6class-20260928_141021` y el indicador **Conectado**.
2. Pulse **Combate**. El evento **"Validación 1"** y el árbitro **"Árbitro de prueba"** vienen cargados desde la instalación (y también el evento "Evento de prueba"). Elija el **brazo armado** de cada tirador (Diestro o Zurdo; es obligatorio, no tiene valor por defecto) y pulse **Crear combate**. Debe aparecer la tarjeta **Combate activo**.
3. Pulse **Revisión VAR**. En **Paso 1 · Clip**, pulse **Elegir archivo** (tecla S) y elija un clip MP4 o MOV de sable de ≥ 720p.

   > **[ORIGEN DE LOS CLIPS DE PRUEBA A DEFINIR POR EL AUTOR]** El repositorio no incluye clips: cualquier clip MP4/MOV de sable de ≥ 720p sirve para probar el flujo (ver [`LIMITACIONES.md`](LIMITACIONES.md), sección 7).

4. Lleve el reproductor al instante en que se encendió la luz de A y pulse **Marcar luz ROJ aquí** (tecla R). Debe verse `Luz A: <N> ms`. Si también se encendió la de B, haga lo mismo con **Marcar luz VER aquí** (tecla V). Hace falta al menos una luz.
5. Pulse **ANALIZAR** (tecla Intro). Debe verse "Analizando…" y, al terminar, **✓ Listo** y el **Paso 2 · Sugerencia** con la clase (por ejemplo "Riposte · ROJ"), el porcentaje de **Confianza** y una insignia de razonamiento ("Respaldada por la pose", "No concluyente", "Evidencia discordante" o "Evidencia insuficiente").
6. Pulse **Ver interpretación** (tecla I): se abre el modal con los **trazos de pose** sobre fondo negro y el **razonamiento** (eventos medidos sobre la pose y criterio FIE). Cierre con Esc.
7. En **Paso 3 · Decisión del árbitro** responda **¿Modifica la clase sugerida?**, elija la clase final si corresponde (o **Anular la acción**) y pulse **Confirmar y registrar**. Debe verse **✓ Veredicto registrado**. El sistema solo sugiere: el veredicto lo pone usted, y una vez registrado no se puede editar.
8. Pulse **Historial** para ver las revisiones, el resumen de la sesión (κ, latencia p95) y, con **Exportar evidencia**, descargar `resumen-<evento_id>.json`.

La sugerencia puede ser equivocada ([`LIMITACIONES.md`](LIMITACIONES.md), sección 1): no es un error del sistema.

### A.5 Qué hacer si el clip no da sugerencia

La pantalla muestra **"Clasificación no disponible"** con el motivo (por ejemplo, "No se pudo detectar a ambos tiradores en el clip.") y "Continúe con el procedimiento VAR habitual." Aun así puede registrar su veredicto. Los motivos están en [`MANUAL_USUARIO.md`](MANUAL_USUARIO.md), sección 5.

### A.6 Cerrar la sesión (D-22, D-26)

Ningún clip se conserva después de la sesión. En **Combate**, con un combate activo, pulse **Cerrar sesión de validación** y confirme con **Sí, respaldar y borrar los clips**. Hace el respaldo verificado (sin clips) y, **solo si pasa**, borra los clips de la sesión. Debe verse `✓ Sesión cerrada. Respaldo verificado; clips borrados: N.` La sesión queda cerrada y el combate activo se limpia (la pantalla vuelve a pedir configurarlo).

`N` cuenta los archivos que se borraron. Un clip que otra sesión también usó (mismo hash) **no se borra**: por eso, si carga el mismo archivo en dos sesiones, la primera en cerrarse puede informar menos clips borrados de los que cargó. Si el respaldo falla, **no se borra nada** y la pantalla muestra `✕ La sesión NO se cerró y no se borró ningún clip.` con el motivo.

### A.7 Tiempos medidos

Medidos en un MacBook Air Apple M4 (16 GB), macOS 27.0.1, Colima de 2 CPU y 2 GiB, con la red del autor. Los pasos de descarga dependen de la red y de las cachés:

| Paso | Tiempo |
|---|---|
| Fog listo tras `sh scripts/fog_nativo.sh` | 5 s |
| Sugerencia sobre un clip de 300 fotogramas (Fog recorta a la ventana de D-19), de pulsar ANALIZAR a ✓ Listo | 14,9 s |
| Sugerencia de cada clip de la prueba de humo (clips ya recortados, 15 a 28 fotogramas) | 3,1 a 5,6 s |
| `instalar_fog.sh instalar`, paso 1 (entorno Python con torch, caché fría de pip) | 467 s |
| `instalar_fog.sh instalar`, pasos 2 a 4 (modelo con descarga de YOLO de 133 MB, configuración, base) | 122 s |
| `compose ... up -d --build` (imágenes de Cloud y del frontend) | 4 min 53 s |
| Segunda corrida completa en un clon nuevo, con las cachés de pip y de Docker ya calientes: clon, `instalar` (venv, modelo, base) y `compose up --build` | 1 min 35 s (70 s + 24 s) |

**Del clon a la primera sugerencia: unos 15 minutos** (467 + 122 + 293 + 5 s de arranque + 15 s de análisis ≈ 902 s), sin contar la instalación de Homebrew, Colima y Docker, ni el tiempo que usted tarde en escribir las respuestas del instalador. Es el número del [`README.md`](../../README.md); con las cachés calientes (por ejemplo, al reinstalar) baja a unos 2 minutos.

---

## Modo B · Fog propio con frontend y Cloud desplegados

Qué recibe del autor: **(1)** la URL del frontend, **(2)** la URL de Cloud y **(3)** un archivo de token (`<su-nombre>.token`, por un canal seguro). Qué necesita en su equipo: lo mismo que el modo A **menos** Redis, Cloud y frontend: Fog nativo y PostgreSQL en Docker. Fog escucha **solo en `127.0.0.1`**: nada entra a su equipo; su navegador habla con su Fog local y su Fog sale por HTTPS hacia Cloud. Sus clips y su base **no salen de su equipo**: Cloud solo recibe las features de cada revisión y no guarda nada.

Esta receta es para macOS y Linux (Fog nativo). La de Windows está en preparación.

Requisito: haber instalado el sistema ([`GUIA_INSTALACION.md`](GUIA_INSTALACION.md)); eso deja `.env` con su usuario y contraseña.

**B.1 Configurar el modo remoto** (una vez):

```bash
cd <carpeta-del-proyecto>/backend
sh scripts/instalar_fog.sh modo --remoto --cloud-url https://<URL de Cloud> --frontend-url https://<URL del frontend>
```

Escribe `CLOUD_TRANSPORTE=http`, `CLOUD_URL` y `CORS_ORIGINS` en `.secrets/fog_remoto.env` (permisos 600). Solo acepta `https://` (sin usuario ni clave).

**B.2 Instalar su token** (sin mostrarlo):

```bash
sh scripts/instalar_fog.sh importar-token <ruta del archivo .token>
```

Lo copia a `.secrets/cloud_token.txt` con permisos 600. Puede borrar el archivo original.

**B.3 Levantar solo PostgreSQL** (sin Redis):

```bash
colima start --cpu 2 --memory 4        # solo macOS con Colima
sh scripts/compose.sh -f docker-compose.yml -f docker-compose.nativo.yml -f docker-compose.http.yml up -d
docker ps --format '{{.Names}} {{.Status}}'      # solo debe verse sabre-postgres-1 (healthy)
```

**B.4 Probar el equipo a través de Cloud** (10 clips de referencia clasificados por Cloud, con la misma cota de equivalencia que el modo A; tarda unos minutos):

```bash
sh scripts/instalar_fog.sh probar --remoto
```

Debe terminar con `Clase igual en 10/10 ...` y `APROBADA`. Sin esa prueba aprobada para esta versión, `fog_nativo.sh --remoto` no arranca.

**B.5 Arrancar Fog** (terminal aparte, queda abierta):

```bash
sh scripts/fog_nativo.sh --remoto
curl -s -w " %{http_code}\n" http://localhost:8001/health
```

Debe verse `{"fog":"ok","cloud":"ok","postgres":"ok"} 200`. `cloud` consulta `GET /health` de Cloud: si dice `error`, revise su conexión a internet o la URL de Cloud.

**B.6 Abrir la aplicación.** En **Chrome o Edge** abra la URL del frontend. En el login, el campo **Nodo Fog** ya dice `http://localhost:8001`:

1. Pulse **Probar conexión**. La primera vez Chrome o Edge preguntan si esa página puede acceder a aplicaciones y servicios de su equipo (red local): elija **Permitir**. Debe verse "Conectado: el Fog responde." Si elige Bloquear, el mensaje lo explica; se cambia en el candado de la barra de direcciones → Configuración del sitio.
2. Ingrese con el usuario y la contraseña de su `.env` (los mismos del modo A) y siga desde A.4: configurar el combate, cargar el clip con la luz marcada, ver la sugerencia, los trazos, el razonamiento y registrar el veredicto.

Solo se aceptan nodos `http://localhost[:puerto]`, `http://127.0.0.1[:puerto]` o `https://...`. Otra dirección `http://` se rechaza a propósito: el navegador bloquea las llamadas `http://` a otro equipo desde una página `https://` (contenido mixto).

**Navegadores** (medidos el 20/11/2026; detalle en [`DESPLIEGUE_REMOTO.md`](DESPLIEGUE_REMOTO.md), sección 5):

| Navegador | Estado |
|---|---|
| Chrome, Edge | Soportado. Pide permiso de red local la primera vez (**Permitir**) |
| Firefox | Debe funcionar con un aviso parecido, pero **no se pudo verificar** en las pruebas automáticas; si lo usa, cuéntele al autor qué vio |
| Safari | **No soportado**: bloquea `http://localhost` desde una página `https://`. Use Chrome, Edge o Firefox |

**Detener:** `Ctrl+C` en la terminal de Fog y `sh scripts/compose.sh -f docker-compose.yml -f docker-compose.nativo.yml -f docker-compose.http.yml stop`. Los respaldos y la purga de clips al cerrar la sesión son los mismos del modo A (secciones más abajo). **Su token deja de valer si el autor lo revoca**: en ese caso las revisiones quedan en "Clasificación no disponible" (`timeout`) y el log de Fog dice `Cloud rechazó el token de este nodo (401)`.

---

## Arrancar y detener

**Arrancar** (instalación ya hecha): A.1, A.2 sin `--build` y A.3.

```bash
colima start --cpu 2 --memory 4
sh scripts/compose.sh -f docker-compose.yml -f docker-compose.nativo.yml up -d
sh scripts/fog_nativo.sh        # terminal aparte
```

**Detener:**

1. En la terminal de Fog: `Ctrl+C`.
2. Los contenedores (conservan la base):

   ```bash
   sh scripts/compose.sh -f docker-compose.yml -f docker-compose.nativo.yml stop
   ```

3. Opcional: `colima stop`.

**No ejecute `down -v` ni `docker volume rm`**: borran el volumen `sabre_pgdata` con **toda la base**, incluida la auditoría de las revisiones (es de solo adición y no se puede reconstruir: ver [`LIMITACIONES.md`](LIMITACIONES.md), sección 8, DEF-31). Antes de cualquier cosa que toque Docker, respalde la sesión (más abajo).

## Logs

| Qué | Comando |
|---|---|
| Fog | La terminal donde corre `fog_nativo.sh` (nivel con `LOG_LEVEL`, `INFO` por defecto) |
| Cloud | `sh scripts/compose.sh -f docker-compose.yml -f docker-compose.nativo.yml logs cloud` (agregue `-f` para seguirlo) |
| Frontend, PostgreSQL, Redis | ídem con `logs frontend`, `logs postgres` o `logs redis` |
| Evidencia por revisión (L01) | `datos/evidencia/<evento_id>.jsonl`: una línea JSON por revisión cerrada |
| Estado del equipo | `sh scripts/instalar_fog.sh estado` (versión, modelo activo, último respaldo) |

## Respaldo de una sesión (FIX03)

Cada sesión se respalda y se **verifica**. El respaldo **no incluye clips** (D-22): guarda la base completa y los `keypoints` y la evidencia. `RESPALDO_DIR` (la carpeta que eligió al instalar, en `.env`) es obligatoria y debe estar fuera del repositorio y de Docker.

```bash
sh scripts/respaldar_sesion.sh --evento <evento_id>
```

(`<evento_id>` es el UUID del evento; la lista de eventos sale de `curl` a `/eventos` con el token, o de la base.) Debe verse, entre otras:

```text
Verificando el respaldo (restauración en base temporal)
  hashes del MANIFEST: OK
  lectura del .tgz: OK
  restauración en base temporal: OK
  conteos restaurados (revisiones,clasificaciones,veredictos,auditoría): <a>,<b>,<c>,<d>
  fn_verificar_auditoria(): 0 filas alteradas
Respaldo verificado: <RESPALDO_DIR>/R001-<fecha UTC>
```

Se crea `RESPALDO_DIR/R<NNN>-<fecha>/` con un `.dump` (formato custom de `pg_dump`), un `.tgz` y `MANIFEST.sha256`. Si algo no cuadra, la carpeta se renombra a `*.FALLIDO` y el script sale con error. **El botón "Cerrar sesión de validación" y `exportar_evidencia.py` ya ejecutan este respaldo**; el manual solo hace falta si cierra a mano. `fog_nativo.sh` avisa al arrancar si hay revisiones sin respaldar (`FALTA RESPALDAR`).

Verificar un respaldo existente (sin tocar la base):

```bash
sh scripts/respaldar_sesion.sh --verificar <carpeta del respaldo>
```

Debe terminar con `Respaldo válido.`

## Restaurar un respaldo

Restaure siempre en una base **nueva**, nunca sobre la que está usando. Con el contenedor de PostgreSQL en marcha (nombre `sabre-postgres-1` con el proyecto por defecto):

```bash
PG=sabre-postgres-1
docker exec $PG psql -U sabre -d postgres -c 'CREATE DATABASE sabre_restaurada'
docker exec -i $PG pg_restore --exit-on-error -U sabre -d sabre_restaurada < <carpeta del respaldo>/sabre_<evento>_<fecha>.dump
docker exec $PG psql -U sabre -d sabre_restaurada -tA -c "SELECT count(*) FROM sabre.revision_var"
docker exec $PG psql -U sabre -d sabre_restaurada -tA -c "SELECT count(*) FROM sabre.fn_verificar_auditoria()"
```

Debe verse `CREATE DATABASE`, el número de revisiones respaldadas y `0` filas alteradas. Para usarla, arranque Fog con `POSTGRES_DB_NAME=sabre_restaurada sh scripts/fog_nativo.sh`. Para mover la base a **otro equipo**, use `sh scripts/instalar_fog.sh exportar` y `importar` (paquete con el respaldo, el modelo y su manifiesto; ver la cabecera del script): nunca copie el volumen de Docker.

## Purgar clips al cerrar la sesión

El cierre normal es el botón (A.6). La herramienta manual, con las variables de la base y del almacenamiento:

```bash
export DATABASE_URL="postgresql+asyncpg://sabre:$(cat .secrets/postgres_password.txt)@127.0.0.1:${POSTGRES_HOST_PORT:-5436}/${POSTGRES_DB_NAME:-sabre}"
export STORAGE_DIR="$PWD/datos/storage"
.venv/bin/python scripts/purgar_clips.py --evento <evento_id>               # solo cuenta
.venv/bin/python scripts/purgar_clips.py --evento <evento_id> --confirmar   # borra
```

Debe verse `clips por borrar (use --confirmar): N` y, con `--confirmar`, `clips borrados: N` (y `clips borrados: 0` al repetirlo). Hágalo **después** del respaldo. Conserva `clip.sha256` y los metadatos.

## Exportar la evidencia (L02)

Desde la interfaz: **Historial → Exportar evidencia** descarga `resumen-<evento_id>.json`. Desde la línea de comandos se obtienen además `revisiones.csv` (18 campos por revisión) y `resumen.md`:

```bash
export DATABASE_URL="postgresql+asyncpg://sabre:$(cat .secrets/postgres_password.txt)@127.0.0.1:${POSTGRES_HOST_PORT:-5436}/${POSTGRES_DB_NAME:-sabre}"
export EVIDENCE_DIR="$PWD/datos/evidencia" STORAGE_DIR="$PWD/datos/storage"
.venv/bin/python scripts/exportar_evidencia.py --evento <evento_id>
```

Primero ejecuta el respaldo verificado (salida de arriba) y termina con `Evidencia exportada en <EVIDENCE_DIR>/<evento_id>`. Deja en esa carpeta `resumen.json`, `revisiones.csv` y `resumen.md` (métricas de la validación contra sus umbrales, conciliación con el JSONL e integridad de la auditoría). Es idempotente. Sale con código 1 si falta configuración o el evento no existe.

Para crear un evento propio (por ejemplo, para una sesión de ensayo separada), con las mismas variables:

```bash
.venv/bin/python scripts/crear_sesion_validacion.py --evento "Mi sesión" --fecha 2026-11-20 --arbitro "<nombre>" --operador "<nombre>"
```

Imprime `evento_id`, `arbitro_id` y `operador_id` (con `(creado)` o `(ya existía)`); el evento aparece en la pantalla Combate.

---

## Solución de problemas (hallados al ejecutar)

| Síntoma | Causa y solución |
|---|---|
| `fog_nativo.sh` dice `Falta .env` o `postgres no responde en 127.0.0.1:5436` | Falta instalar (`instalar_fog.sh instalar`) o los contenedores están detenidos: A.2. |
| `curl /health` da 503 con `"redis":"error"` o `"postgres":"error"` | El contenedor correspondiente está detenido: `docker ps` y A.2. `fog` en `ok` y otro en `error` es "Degradado" en el indicador de la interfaz. |
| `GET /modelo/activo` responde `{"detail":"No autenticado"}` 401 | Es lo esperado sin token: toda ruta exige `Authorization: Bearer` salvo `/health` y `/auth/login` ([`CONTRATO_API.md`](../../CONTRATO_API.md), sección 0). Use el token del paso 3 de la verificación. |
| La interfaz muestra "Sin conexión" | Fog no está en marcha, o la dirección del **Nodo Fog** (campo del login, se recuerda en el navegador) no es la de su Fog. Cámbiela y pulse *Probar conexión*. En el modo A, el valor inicial del campo sale de `EXPO_PUBLIC_FOG_URL=http://localhost:${FOG_HOST_PORT}` al construir: si cambió `FOG_HOST_PORT`, reconstruya con `... up -d --build frontend` o escriba el puerto en el campo. |
| Modo B: "No se pudo conectar con el servidor" con Fog en marcha | Chrome o Edge sin permiso de red local para esa página (candado → Configuración del sitio → permitir), `CORS_ORIGINS` sin el origen del frontend (repita B.1) o Safari (no soportado) |
| Login: "Credenciales inválidas" o código 429 | 5 fallos en 15 min bloquean la IP durante 15 min, incluso con la contraseña correcta. Espere. La contraseña no se puede recuperar: genere otro hash (`GUIA_INSTALACION.md`, sección 6). |
| "Error: no se pudo analizar el clip" con `413` | El clip supera `CLIP_MAX_MB` (200 MB por defecto). |
| "Clasificación no disponible" por `timeout` | El análisis pasó de 60 s (equipo lento, clip largo o de 60 fps). Ver [`LIMITACIONES.md`](LIMITACIONES.md), sección 2. |
| "Avance por cuadro no disponible: no se pudo medir los fps del clip." | El navegador no pudo medir los fps; los botones de cuadro quedan desactivados y se puede seguir usando el resto. |
| `Cerrar sesión de validación` informa `clips borrados: 0` | Los clips los usa otra sesión (mismo hash). No es un error: A.6. |
| `exportar_evidencia.py` imprime `ERROR: el evento ... no existe en la base sabre` | Instaló con otra base: exporte `POSTGRES_DB_NAME` (y `POSTGRES_HOST_PORT`) antes del script. |
| `instalar_fog.sh` se detiene con `Puerto ... ocupado` | Cambie `FOG_HOST_PORT`, `POSTGRES_HOST_PORT` o `REDIS_HOST_PORT` o libere el puerto (`lsof -i :<puerto>`). |
| Mensajes `Cache entry deserialization failed, entry ignored` al instalar | Avisos de la caché de pip: inofensivos. |
| `docker compose` no existe | Con Colima se instala el binario `docker-compose`; los scripts usan el que haya. Use siempre `sh scripts/compose.sh ...`. |
