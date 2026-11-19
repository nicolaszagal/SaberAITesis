# Guía de instalación de SABRE.AI

Destinatario: la persona que instala y pone en marcha el sistema. Versión cubierta: Validación 1 (carga de clip y tocado simulado). El uso de la interfaz está en `MANUAL_USUARIO.md`.

Método: Docker Compose. No requiere Python, Node, entorno virtual, Alembic ni variables exportadas a mano. Los comandos son para una terminal de macOS o Linux.

Validación de esta guía: se siguió en un clon limpio de ambos repositorios desde GitHub, con `docker compose build --no-cache` y sin volúmenes, sobre macOS 27.0 (arm64) con Colima (2 CPU y 4 GiB).

## 1. Requisitos

### Software

| Elemento | Versión verificada |
|---|---|
| Docker Engine (servidor) | 29.5.2 |
| Docker CLI | 28.2.2 |
| Docker Compose | 5.5.1 |
| Colima (solo macOS sin Docker Desktop) | 0.10.3 |
| Git | Cualquier versión reciente |
| Navegador | Google Chrome |

Las versiones de Python, PostgreSQL, Redis, Node y nginx van dentro de las imágenes y no se instalan en el equipo.

### Recursos

| Recurso | Mínimo verificado | Medición |
|---|---|---|
| CPU | 2 | La prueba de humo y el flujo completo de revisión pasaron con 2 CPU. |
| Memoria para Docker | 4 GiB | Con 4 GiB el flujo completo, la exportación y la prueba de humo pasaron. Con 2 GiB la prueba de humo pasó, pero una exportación de evidencia terminó con código 137 (falta de memoria). |
| Disco libre | No medido como mínimo | Imágenes: Fog 3 GB, Cloud 1.43 GB, frontend 94 MB, PostgreSQL 411 MB, Redis 59 MB (unos 5 GB), más la caché de construcción. Con 7 GB libres en el equipo el build se completó. Con menos de 1 GB libres falló (sección 7). |

Memoria de cada contenedor (`docker stats`, equipo con 4 CPU y 8 GiB en Colima):

| Servicio | En reposo | Durante el análisis de clips (pico) |
|---|---|---|
| Fog | 647 MiB | 669 MiB, 125 % de CPU |
| Cloud | 274 MiB | 162 MiB, 52 % de CPU |
| PostgreSQL | 35 MiB | 32 MiB |
| Redis | 3.5 MiB | 4 MiB |
| Frontend | 7 MiB | 7 MiB |

Fog crece hasta unos 850 MiB tras varios análisis. `exportar_evidencia.py` y los demás scripts de `docker compose exec fog` inician otro proceso de Python que importa torch y llega a 447 MiB: por eso 2 GiB no bastan.

Con Colima, cree la máquina virtual con los recursos mínimos antes de instalar:

```bash
colima start --cpu 2 --memory 4
```

Si la memoria es insuficiente, Fog se queda sin memoria al cargar la pose YOLOv8x (sección 7).

Tiempos medidos:

| Paso | Tiempo |
|---|---|
| `docker compose build --no-cache` (las tres imágenes, con descargas) | 82 s y 85 s en dos corridas |
| `docker compose up -d --build` con las imágenes construidas, hasta Fog `healthy` | 17 s |
| Análisis de un clip en CPU (`ms_clip` de `prueba_humo.py`) | 23 a 47 s, con 2 y con 4 CPU |

Cloud responde en unos 5 ms por clip. El tiempo de análisis lo domina la pose en Fog.

### Carpetas

`backend` y `SaberAISoftware` deben ser carpetas hermanas. El compose construye el frontend desde `../SaberAISoftware`.

Con Colima, coloque las carpetas dentro de su carpeta de usuario (`/Users/<usuario>`): Colima solo comparte esa ruta con Docker. En otra ubicación, la evidencia queda dentro de la máquina virtual y no aparece en `backend/datos`.

## 2. Instalación

1. Cree una carpeta y clone los dos repositorios. El frontend debe llamarse `SaberAISoftware`.

```bash
mkdir sabre && cd sabre
git clone https://github.com/nicolaszagal/SaberAITesis.git backend
git clone https://github.com/nicolaszagal/SaberAI-Frontend.git SaberAISoftware
```

Resultado esperado: dos carpetas, `backend` y `SaberAISoftware`, ambas en la rama `main`.

2. Cree el archivo de configuración.

```bash
cd backend
cp .env.example .env
```

Resultado esperado: existe `backend/.env` con `POSTGRES_PASSWORD`, `FRONTEND_HOST_PORT` y `FOG_HOST_PORT`. Cambie `POSTGRES_PASSWORD` si el equipo es compartido (solo letras y números). Cambie los puertos si 8081 o 8001 están ocupados.

3. Construya y levante el sistema.

```bash
docker compose up -d --build
```

Resultado esperado: el comando termina sin errores y crea los contenedores `sabre-postgres-1`, `sabre-redis-1`, `sabre-cloud-1`, `sabre-fog-1` y `sabre-frontend-1`. La primera construcción descarga las imágenes base, torch y los pesos de YOLOv8x, y verifica su SHA-256 (`yolov8x-pose.pt verificado ...`).

4. Espere a que los servicios estén sanos.

```bash
docker compose ps
```

Resultado esperado: `postgres`, `redis`, `fog` y `frontend` en `healthy`, y `cloud` en `Up`. Fog puede figurar como `health: starting` durante los primeros 20 segundos. Al arrancar, Fog aplica las migraciones y registra el modelo desplegado solo si no hay uno activo. No hay pasos manuales.

Cada servicio se puede levantar por separado con `docker compose up -d <servicio>` (`postgres`, `redis`, `cloud`, `fog`, `frontend`). Sus dependencias se levantan con él.

## 3. Verificación

1. Estado del sistema.

```bash
curl -s -w " %{http_code}\n" http://localhost:8001/health
```

Resultado esperado: `{"fog":"ok","redis":"ok","postgres":"ok"} 200`.

2. Modelo activo.

```bash
curl -s http://localhost:8001/modelo/activo
```

Resultado esperado: `{"nombre":"lstm6class-20260928_141021","num_clases":6,"f1_macro_test":0.5249,"kappa_piloto":null}`.

3. Interfaz. Abra `http://localhost:8081` en el navegador.

Resultado esperado: aparece el encabezado SABRE.AI con la pantalla "Revisión VAR" (la interfaz abre directo en ella, sin pantalla de inicio), el texto "Modelo activo:" con el nombre del modelo y el indicador "Conectado". Si cambió los puertos en `.env`, use `http://localhost:<FRONTEND_HOST_PORT>`.

4. Cloud listo.

```bash
docker compose logs cloud
```

Resultado esperado: las líneas `modelo precalentado en N ms` y `Cloud escuchando 'fog:features' como 'cloud-worker-1'...`.

Solo se publican el frontend (8081) y Fog (8001). PostgreSQL y Redis no se publican en el equipo. Los puertos se cambian en `.env`. Si cambia `FOG_HOST_PORT`, reconstruya el frontend (`docker compose up -d --build frontend`), porque la dirección de Fog se incrusta en el build.

## 4. Preparar sesión y exportar evidencia

### Datos precargados: eventos, árbitro y operador

No hay que registrar nada a mano: la migración `0005` de la base (`alembic upgrade head`, que el arranque de Fog ejecuta solo) precarga dos eventos y dos usuarios. Inserta solo los que no existen por nombre y no modifica los existentes, de modo que también completa una base creada con una versión anterior.

| Dato | Nombre | Tipo o rol | Uso |
|---|---|---|---|
| Evento | "Evento de prueba" | `formativo` | Ensayos. |
| Evento | "Validación 1" | `piloto` | Sesión real. |
| Usuario | "Árbitro de prueba" | `arbitro` | Árbitro del combate. |
| Usuario | "Operador de prueba" | `operador` | Operador técnico. |

La fecha de ambos eventos es la del día en que corrió la migración: no hay una fecha documentada para la sesión. Los ensayos y la sesión real usan eventos distintos para que no se mezclen en la evidencia y en el resumen de la sesión.

En la interfaz, "Combate" abre "Configurar combate" con el evento "Validación 1", el árbitro único y la pista "P1" ya seleccionados. Los alias de los tiradores son opcionales ("Tirador A" y "Tirador B" por defecto) y el brazo armado de ambos es obligatorio. Para ensayar, seleccione "Evento de prueba". Si la lista aparece vacía, pulse "Recargar".

El formulario no pide datos de consentimiento. El sistema guarda a los tiradores con `es_menor = true` y sin consentimiento registrado, un valor conservador: el consentimiento informado se gestiona en papel, fuera del sistema (RNF-16).

Uso técnico (opcional): `scripts/crear_sesion_validacion.py` crea otro evento `piloto` u otros usuarios. Es idempotente por nombre.

```bash
docker compose exec fog python scripts/crear_sesion_validacion.py --evento "<nombre>" \
    --fecha AAAA-MM-DD --arbitro "<nombre>" --operador "<nombre>"
```

### Dónde queda la evidencia

| Carpeta del equipo | Contenido |
|---|---|
| `backend/datos/storage/clips/` y `keypoints/` | Clips y keypoints por SHA-256. |
| `backend/datos/evidencia/<evento_id>.jsonl` | Una línea por revisión cerrada. Solo adición. |
| `backend/datos/evidencia/<evento_id>/` | Exportación: `resumen.json`, `revisiones.csv`, `resumen.md`. |

Las carpetas se abren desde el Finder. La evidencia no incluye nombres de atletas: usa alias.

### Exportar la evidencia

```bash
docker compose exec fog python scripts/exportar_evidencia.py --evento <evento_id>
```

Resultado esperado: `Evidencia exportada en /data/evidencia/<evento_id>` y código 0. Los tres archivos aparecen en `backend/datos/evidencia/<evento_id>/`. El comando se puede repetir: sobrescribe los archivos. La tabla de M01 del resumen indica "no disponible" porque el log de experimentos no va dentro de la imagen.

## 5. Detener, actualizar, respaldar y restaurar

### Ver logs

```bash
docker compose logs -f fog
```

Use `cloud`, `postgres`, `redis` o `frontend` en lugar de `fog` para otro servicio. Salga con Ctrl+C.

### Detener e iniciar

```bash
docker compose down
docker compose up -d
```

Resultado esperado: `down` elimina los contenedores y conserva los datos (volumen de PostgreSQL y carpeta `datos/`). Nunca use `down -v`: borra la base (ver "Qué borra la base" más abajo).

### Actualizar

```bash
git pull
git -C ../SaberAISoftware pull
docker compose up -d --build
```

Resultado esperado: se reconstruyen solo las imágenes que cambiaron y Fog aplica las migraciones pendientes al arrancar.

### Qué borra la base

La base vive en un volumen de Docker (`sabre_pgdata`). Estos comandos la **borran** sin pedir confirmación y, sin respaldo, la evidencia de la sesión se pierde (así se perdió la base de la Validación 1, DEF-31):

- `docker compose down -v` (la opción `-v` elimina los volúmenes).
- `colima delete` o recrear la máquina de Colima.
- Cambiar de motor de Docker (Colima, Docker Desktop, OrbStack): cada uno tiene sus propios volúmenes.
- `docker volume rm sabre_pgdata` o `docker system prune --volumes`.

`docker compose down` sin `-v` conserva la base. La carpeta `datos/` (clips, `.npz`, JSONL) vive en el disco del equipo, pero sin las filas de la base no se puede reconstruir qué revisión es cuál.

### Respaldar una sesión

Defina `RESPALDO_DIR`, una carpeta **fuera del repo y fuera de Docker** (por ejemplo un disco externo). No tiene valor por defecto: sin ella el script se niega a correr. Se define en el entorno o con una línea `RESPALDO_DIR=...` en `.env`.

```bash
export RESPALDO_DIR="$HOME/Documents/Respaldo_Validación/Tesis"
sh scripts/respaldar_sesion.sh --evento <id del evento>
```

Con la base del despliegue remoto agregue `POSTGRES_DB_NAME=sabre_expo`. El script crea `RESPALDO_DIR/R<NNN>-<fecha UTC>/` (por ejemplo `R001-20261102T194746Z`; NNN es el número correlativo del respaldo, que no se reutiliza ni siquiera si un respaldo queda `*.FALLIDO`) con el `.dump` (`sabre_<evento>_<fecha>.dump`, formato custom de `pg_dump`), el `.tgz` de `datos/storage` y `datos/evidencia`, y `MANIFEST.sha256`. Después **verifica** el respaldo: comprueba los hashes, lee el `.tgz`, restaura el dump en una base temporal (que elimina), compara los conteos de revisiones, clasificaciones, veredictos y auditoría con los de la base, y exige que `fn_verificar_auditoria()` devuelva 0 filas. Resultado esperado: termina con `Respaldo verificado: <carpeta>`. Si algo no cuadra sale con error y renombra la carpeta a `*.FALLIDO`: ese respaldo no sirve; repita el comando (con Fog en reposo, porque falla si la base cambia durante el respaldo).

Cuándo respaldar:

- Al cerrar cada sesión: `python scripts/exportar_evidencia.py --evento <id>` exporta la evidencia y llama al respaldo. Sin `RESPALDO_DIR` avisa en grande y sale con código 2.
- `scripts/fog_nativo.sh` (al arrancar) y `scripts/fog_remoto.sh stop` avisan si hay revisiones nuevas desde el último respaldo verificado. Es solo un aviso: no respaldan por usted.

Copie además la carpeta de `RESPALDO_DIR` a un segundo disco o a la nube antes de apagar el equipo.

### Restaurar

Restaure en una base vacía, sin ejecutar antes migraciones: el dump ya trae el esquema y la tabla `alembic_version`. Primero compruebe el respaldo:

```bash
sh scripts/respaldar_sesion.sh --verificar "$RESPALDO_DIR/R<NNN>-<fecha>"
```

Luego, la base y los archivos:

```bash
docker compose exec -T postgres createdb -U sabre sabre_restaurada
docker compose exec -T postgres pg_restore --exit-on-error -U sabre -d sabre_restaurada \
    < "$RESPALDO_DIR/R<NNN>-<fecha>/sabre_<evento>_<fecha>.dump"
docker compose exec -T postgres psql -U sabre -d sabre_restaurada \
    -c "select count(*) from sabre.veredicto" -c "select * from sabre.fn_verificar_auditoria()"
tar -xzf "$RESPALDO_DIR/R<NNN>-<fecha>/sabre_<evento>_<fecha>.tgz" -C datos
```

Resultado esperado: la cuenta de veredictos coincide con la de la base original y `fn_verificar_auditoria()` devuelve 0 filas. Para usar la base restaurada, apunte Fog a ella con `POSTGRES_DB_NAME=sabre_restaurada` (modo piloto) o renómbrela a `sabre` con Fog detenido.

## 6. Prueba de humo

Recorre un clip por clase hasta el veredicto. Usa el proyecto `sabre-humo`, con base, Redis y carpeta de datos propios (`datos-humo`) y los puertos 8003 y 8083, sin tocar la validación. Monta `../dataset` en solo lectura: requiere la carpeta `dataset` hermana de `backend`, con `dataset trimmed/test_trimmed/` y `labels/`.

```bash
sh scripts/prueba_humo_docker.sh
```

Resultado esperado: seis líneas JSON, una por clase, cada una con `"disponible": true` y `"veredicto_http": 200`, y código de salida 0 (`echo $?`). El script sale con código 1 si algún veredicto no se registra. Dura unos cuatro minutos. Los resultados quedan en `backend/datos-humo/evidencia/humo.json`.

Para retirar la prueba, incluidos sus datos:

```bash
docker compose -p sabre-humo --env-file humo.env -f docker-compose.yml -f docker-compose.humo.yml down -v
rm -rf datos-humo
```

## 7. Solución de problemas

| Síntoma | Causa | Acción |
|---|---|---|
| `required variable POSTGRES_PASSWORD is missing a value: copiar .env.example a .env` | Falta `backend/.env`. | Ejecute `cp .env.example .env` (sección 2, paso 2). |
| `unable to prepare context: path "<ruta>/SaberAISoftware" not found` | El frontend no es carpeta hermana de `backend`, o tiene otro nombre. | Clone el frontend como `SaberAISoftware` junto a `backend` (sección 2, paso 1). |
| `Bind for 0.0.0.0:8081 failed: port is already allocated` (o 8001) | Otro proceso usa el puerto. | Cambie `FRONTEND_HOST_PORT` o `FOG_HOST_PORT` en `.env` y repita `docker compose up -d --build`. |
| Fog se reinicia sin llegar a `healthy`; `docker compose logs fog` termina en `Cargando modelo YOLO y extractor de features` | Falta de memoria (`OOMKilled`). | Confirme con `docker inspect -f '{{.RestartCount}}' sabre-fog-1`: un número mayor que 0 indica reinicios (`OOMKilled` solo es `true` justo después del corte). Con Colima: `colima stop` y `colima start --cpu 2 --memory 4`. |
| Un comando de `docker compose exec fog python scripts/...` termina con código 137 | Falta de memoria: el script carga torch (447 MiB) sobre Fog. | Suba la memoria a 4 GiB (`colima stop` y `colima start --cpu 2 --memory 4`) y repita. |
| `backend/datos` queda vacía aunque hay revisiones | Con Colima, las carpetas están fuera de `/Users/<usuario>` y Docker escribe dentro de la máquina virtual. | Mueva `backend` y `SaberAISoftware` a su carpeta de usuario y repita. |
| El build de Fog falla con `SHA-256 de yolov8x-pose.pt no coincide` | El archivo descargado no es el usado en el entrenamiento. | No continúe. Avise al equipo de desarrollo. |
| El build falla con `input/output error` o `no space left on device` | Disco del equipo lleno. | Libere espacio en el equipo y repita. Con Colima, reinicie con `colima stop` y `colima start`. |
| `Cannot connect to the Docker daemon` | Docker o Colima no están en marcha. | Ejecute `colima start` (o abra Docker Desktop). |
| La interfaz muestra "Sin conexión" | Fog no está sano, o `FOG_HOST_PORT` cambió sin reconstruir el frontend. | Revise `docker compose ps`. Si cambió el puerto, ejecute `docker compose up -d --build frontend`. |
| La interfaz muestra "No hay eventos registrados" o "No hay árbitros registrados" | La migración `0005` no se aplicó (Fog no reinició tras una actualización). | Ejecute `docker compose restart fog`: el arranque aplica las migraciones y precarga los datos (sección 4). Pulse "Recargar". |
| La carga de un clip responde 503 | No hay una versión de modelo activa. | Ejecute `docker compose restart fog`: el arranque registra el modelo si falta. |
| `/health` responde 503 | Un componente está en `"error"`. | Lea el cuerpo: `redis` o `postgres` indican cuál. Revise `docker compose ps` y los logs de ese servicio. |
| Aviso `objc: Class AVFFrameReceiver is implemented in both` en los logs de Fog | Bibliotecas duplicadas en la imagen. | Es un aviso. No impide el funcionamiento. |

## 8. Modo piloto: Fog nativo

Para un equipo con Apple Silicon donde el análisis en Docker es lento. Fog corre fuera de Docker, con el entorno virtual de `GUIA_EJECUCION.md` (sección 2); PostgreSQL, Redis, Cloud y el frontend siguen en Docker. Usa las mismas carpetas `backend/datos` que el modo Docker, pero no se ejecuta a la vez que el Fog de Docker (ambos usan el puerto 8001). El flujo de las secciones 2 a 7 no cambia.

1. Levante todo menos Fog. PostgreSQL y Redis quedan publicados solo en `127.0.0.1` (puertos 5436 y 6380; cámbielos con `POSTGRES_HOST_PORT` y `REDIS_HOST_PORT` en `.env`).

```bash
docker compose -f docker-compose.yml -f docker-compose.nativo.yml up -d
```

2. Arranque Fog nativo. El script fija las variables, aplica `alembic upgrade head`, registra el modelo si no hay uno activo y arranca `uvicorn` en el puerto 8001. Se detiene con Ctrl+C.

```bash
sh scripts/fog_nativo.sh
```

Resultado esperado: `Application startup complete` y `curl -s http://localhost:8001/health` responde `{"fog":"ok","redis":"ok","postgres":"ok"}`.

Medición (`prueba_humo.py`, 6 clips, tiempo `ms_clip` de la carga del clip, cliente en el equipo; mediana y p95 por rango superior de 6 valores):

| Modo | Mediana | p95 |
|---|---|---|
| Docker, Colima con 2 CPU y 4 GiB | 43.9 s | 48.9 s |
| Docker, Colima con 4 CPU y 4 GiB | 42.2 s | 45.7 s |
| Fog nativo (Python 3.14) | 5.4 s | 5.9 s |

Las seis sugerencias coincidieron entre Docker y nativo. En modo nativo la pose usa la CPU: el código no fija `device`, el log de Fog no muestra el dispositivo (`ultralytics` queda en WARNING) y una carga del mismo modelo con la llamada por defecto reporta `cpu`, aunque MPS está disponible en el equipo. Usar MPS no se ha probado. Para volver al flujo principal, detenga `fog_nativo.sh` y ejecute `docker compose up -d`.

## 9. Instalar o migrar Fog a otro equipo

Fog corre local (DEPLOY09). Esta sección lo instala en otro equipo y migra sus datos sin perder funcionalidad ni evidencia. Todo pasa por `scripts/instalar_fog.sh`, que **no borra datos** (sin `down -v`, `volume rm` ni `DROP DATABASE` sobre bases con datos) y **no instala nada del sistema**.

**Plataformas**: macOS arm64 (el Mac de la Validación 1) y Linux x86_64. Windows queda fuera. PostgreSQL y Redis siguen en Docker (Colima en macOS, Docker Engine en Linux); Fog corre nativo.

**Por qué hay una prueba de equivalencia.** Una versión distinta de `ultralytics` o del tracker cambia las features (`contexto_sabre.md` §8), y un equipo que "arranca" no prueba que clasifique igual. Por eso `probar` corre 10 clips fijos y exige la misma clase que el Mac de referencia. Y el volumen de PostgreSQL vive dentro de la máquina virtual del motor de Docker: la base se mueve con `exportar` e `importar`, no copiando volúmenes (DEF-31).

### Equipo de origen: exportar

1. Detenga Fog (el respaldo debe hacerse con la base en reposo) y deje PostgreSQL arriba.
2. Elija el evento a respaldar (el comando lista los eventos si falta `--evento`):

```bash
sh scripts/instalar_fog.sh exportar --destino /Volumes/Respaldo/fog_migracion --evento <uuid>
```

El destino debe estar vacío y fuera del repo. Genera `respaldo/` (el respaldo verificado de FIX03), `modelo/`, `lock/`, `referencia/clips/`, `CONTEOS.txt`, `MANIFEST.sha256` y `LEEME_MIGRACION.md` (con el commit de `main` que hay que clonar en el destino).

3. **Mueva a mano las claves.** No entran al paquete: `.env`, `.secrets/` y el certificado y la clave de cliente de Redis del nodo Fog (`REDIS_TLS_CERT`, `REDIS_TLS_KEY`, SEC01). Cópielos por un canal propio (llave USB cifrada o `scp` entre equipos suyos), con permisos 600. El `.env` del destino lo genera `instalar`: no copie el del origen.

### Equipo de destino: instalar, importar, probar

1. Clone `SaberAITesis` y `SaberAI-Frontend` como carpetas hermanas y haga `git checkout <commit de main del LEEME>`.
2. Compruebe los requisitos (no cambia nada; con `--remoto` también revisa `cloudflared` o `tailscale`):

```bash
sh scripts/instalar_fog.sh verificar
```

Lista lo que falta y cómo instalarlo. Si no hay ni `docker compose` ni `docker-compose`: en macOS con Colima, `brew install docker-compose` (queda el binario `docker-compose`; para usarlo como plugin hay que registrar `/opt/homebrew/lib/docker/cli-plugins` en `cliPluginsExtraDirs` de `~/.docker/config.json`); en Linux, el plugin oficial (<https://docs.docker.com/compose/install/linux/>). Todos los scripts usan la misma función (`scripts/lib_compose.sh`) y funcionan con cualquiera de los dos.

3. Instale:

```bash
sh scripts/instalar_fog.sh instalar --paquete /Volumes/Respaldo/fog_migracion
```

Crea `.venv` con `requirements-fog.lock` (macOS) o `requirements-fog.linux-x86_64.lock` (Linux), copia el modelo y lo verifica contra `scripts/datos/MODELO.sha256` (si un hash no coincide, aborta), genera `.env` (los valores aleatorios se generan; pide por `getpass` la contraseña maestra), levanta PostgreSQL y Redis, aplica las migraciones y registra el modelo activo. Si el volumen `sabre_pgdata` ya existe con datos no lo toca, y pide la contraseña de esa base en vez de generar otra. Termina avisando que **el equipo no está listo hasta que `probar` pase**.

4. Importe (restaura en una base sin revisiones; se niega si la base de destino ya tiene alguna):

```bash
sh scripts/instalar_fog.sh importar --desde /Volumes/Respaldo/fog_migracion
```

Verifica el manifiesto antes de tocar nada, restaura en una base temporal, compara los conteos con `CONTEOS.txt` y exige que `fn_verificar_auditoria()` dé 0 filas; solo entonces la renombra a la base definitiva (la anterior, vacía, queda como `<base>_previa_<n>`; bórrela usted si quiere). Después restaura `datos/storage` y `datos/evidencia` sin pisar archivos.

5. Pruebe la equivalencia (unos minutos con CPU):

```bash
sh scripts/instalar_fog.sh probar
```

Aprobado: misma clase en 10/10 y diferencia máxima de probabilidad dentro de la cota de `scripts/datos/referencia_salidas.json` (0.01, provisional). Escribe `datos/evidencia/equivalencia_<equipo>_<fecha>.json` con las versiones instaladas; si falla, compare las versiones con las del Mac (`referencia`) en ese reporte.

6. `sh scripts/instalar_fog.sh estado` muestra versión, commit, modelo activo, dispositivo, último respaldo, túnel y el resultado de la última `probar`.

### Reglas que impone el sistema

- `fog_nativo.sh` se niega a arrancar en modo remoto (`ENTORNO=remoto`) si la última `probar` de ese equipo no pasó o es de otro commit: tras cada `git pull` o commit nuevo hay que repetir `probar`.
- `FOG_DEVICE` (por defecto `cpu`, lo que corrió en la Validación 1; `mps` o `cuda` opcionales) llega a YOLO. Un dispositivo distinto de `cpu` solo arranca si la última `probar` se corrió con ese mismo dispositivo y pasó.
- Con `FOG_DEVICE=cuda` en Linux hay que correr `probar` con `FOG_DEVICE=cuda sh scripts/instalar_fog.sh probar`.

### Limitaciones conocidas

- `requirements-fog.linux-x86_64.lock` se generó por metadatos de PyPI con `scripts/generar_lock_linux.py` (mismas versiones que el lock del Mac más las dependencias solo de Linux: CUDA y triton); no es un `pip freeze` de un Linux real. La instalación en Linux está **pendiente de probar** en el PC de casa.
- La cota de probabilidad de `probar` es **0.01, provisional: a recalibrar con la primera medición entre plataformas**. Se confirmó tras medir dos corridas seguidas en un solo equipo (el Mac, diferencia 0.0), así que no incluye el ruido entre plataformas.

## Anexo. Fuera de la Validación 1

| Tema | Dónde |
|---|---|
| V2 (Edge y MediaMTX): perfil `v2` del compose. No verificado en esta versión. | `docker compose --profile v2 up -d`; detalle en `GUIA_EJECUCION.md`, sección 6.4 |
| Despliegue de Cloud en Render | `GUIA_EJECUCION.md`, secciones 6.2 y 6.3 |
| Modo de desarrollo (venv, pruebas, frontend con Expo) | `GUIA_EJECUCION.md` |
