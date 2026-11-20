# Guía de instalación de SABRE.AI

Para una persona con conocimientos técnicos que instala el sistema por primera vez, sin ayuda del autor y sin acceso a sus secretos. Después de instalar, siga [`GUIA_EJECUCION.md`](GUIA_EJECUCION.md) (modo A). El uso de la interfaz está en [`MANUAL_USUARIO.md`](MANUAL_USUARIO.md) y lo que el sistema **no** hace, en [`LIMITACIONES.md`](LIMITACIONES.md).

**Cómo se validó esta guía.** Se siguió en un clon limpio de `main` en una carpeta nueva (un `.venv` nuevo y una base nueva, `sabre_revision`), copiando cada comando del documento. Las salidas "Debe verse" se copiaron de esa ejecución. La tabla de defectos hallados está en la sección 8. Si un paso no se comporta como aquí, es un defecto de la guía: repórtelo.

## 1. Qué se instala

| Pieza | Dónde corre | Cómo se instala |
|---|---|---|
| Fog (API, pose YOLOv8-pose, 192 features) | **Nativo** en su equipo (Python 3.14 + `.venv`) | `scripts/instalar_fog.sh instalar` |
| Cloud (clasificador BiLSTM) | Docker | `docker compose` construye la imagen |
| PostgreSQL 16 y Redis 7 | Docker | `docker compose` |
| Frontend (interfaz web) | Docker (nginx, build estático) | `docker compose` construye la imagen |

Fog corre fuera de Docker porque en CPU es más rápido y es lo que se usó en las pruebas de rendimiento (ver [`LIMITACIONES.md`](LIMITACIONES.md), sección 2). Esta guía cubre la instalación local para revisar el sistema. El despliegue remoto es solo del autor ([`DESPLIEGUE_REMOTO.md`](DESPLIEGUE_REMOTO.md)).

## 2. Requisitos verificados

| Elemento | Verificado en esta sesión | No verificado |
|---|---|---|
| Sistema operativo | **macOS 27.0.1 (arm64)**, Apple M4 | **Linux x86_64**: existe `requirements-fog.linux-x86_64.lock`, pero se generó a partir de metadatos de PyPI y **no es un `pip freeze` de un Linux real** (lo dice su cabecera). No se instaló en Linux. Windows queda fuera. |
| Memoria | 16 GB en el equipo; Colima con **2 CPU y 2 GiB**. Con esos 2 GiB corrieron Cloud, PostgreSQL, Redis y el frontend, la suite de pruebas y el flujo completo | Mínimo del equipo: no medido. Fog nativo llegó a 883 MiB con una pista y 1577 MiB con cuatro (`docs/evidencia/estres/ESTRES01_2026-11-19.md`, otro equipo: M4 de 16 GB). Se recomienda Colima con 4 GiB. |
| Disco | 28 GB libres al empezar. Ocupó: `.venv` 1,2 GB, imagen de Cloud 1,54 GB, imagen de PostgreSQL 411 MB, imagen del frontend 94 MB, Redis 59 MB, `yolov8x-pose.pt` 133 MB (unos 3,5 GB en total, sin la caché de construcción) | Mínimo del instalador: 7 GB libres (`ESPACIO_MIN_GB`). No hay otro mínimo medido. |
| Python | **3.14.5** (Homebrew). El lock se generó con 3.14.5 y el instalador exige la misma versión menor (3.14) | Otras versiones menores: rechazadas por `verificar`. |
| Docker | Docker Engine 29.5.2 (servidor), CLI 28.2.2, Colima 0.10.3, `docker-compose` 5.5.1 (binario suelto, sin el plugin `docker compose`). Los scripts usan `docker compose` o `docker-compose`, el que exista | Docker Desktop: no probado. |
| Git | 2.54.0 | |
| Navegador | Google Chrome (el que se usó para las capturas y el que reproduce H.264) | Otros: no probados. |
| Node.js | **No hace falta** para el modo A: el frontend se construye dentro de Docker. Solo se necesita para desarrollo (v22.22.0, npm 11.17.0; ver [`GUIA_DESARROLLO.md`](GUIA_DESARROLLO.md)) | |

Conexión a internet: la instalación descarga unos 1,5 GB (torch y demás dependencias, imágenes de Docker y los pesos de YOLO).

### Instalar los requisitos en macOS (Homebrew)

```bash
brew install python@3.14 git colima docker docker-compose
colima start --cpu 2 --memory 4
```

Debe verse: `colima is running using macOS Virtualization.Framework`. Compruebe que Docker responde con `docker info` (sin error). En Linux instale Python 3.14, Docker Engine con el plugin Compose y Git con el gestor de paquetes (sin verificar, ver arriba).

Con Colima, ponga la carpeta del proyecto dentro de su carpeta de usuario: Colima solo comparte esa ruta con Docker.

## 3. Obtener el código

Las tres carpetas `backend`, `SaberAISoftware` y `dataset` deben quedar **juntas** (hermanas). `dataset` la crea el instalador en el paso 4. Elija una carpeta de trabajo (aquí `sabre`):

```bash
mkdir sabre && cd sabre
git clone https://github.com/nicolaszagal/SaberAITesis.git backend
git clone https://github.com/nicolaszagal/SaberAI-Frontend.git SaberAISoftware
cd backend
git branch --show-current
```

Debe verse: `main` (la rama vigente de ambos repositorios). Si los repositorios son privados, necesita acceso que le dé el autor.

## 4. Instalación

### 4.1 Comprobar los requisitos (no cambia nada)

```bash
sh scripts/instalar_fog.sh verificar
```

Debe verse una línea `✓` por requisito y, al final, `Requisitos cumplidos.` (la línea `! Modo remoto no verificado` es normal). Cada `✗` trae el comando para arreglarlo. Si un puerto está ocupado, cambie `FOG_HOST_PORT`, `POSTGRES_HOST_PORT` o `REDIS_HOST_PORT` (por defecto 8001, 5436 y 6380) en el entorno antes de seguir.

### 4.2 Instalar

```bash
sh scripts/instalar_fog.sh instalar
```

Hace cuatro cosas y **no instala nada del sistema**:

1. `[1/4] Entorno Python`: crea `.venv` e instala **exactamente** las versiones de `requirements-fog.lock` (macOS arm64) con `-c constraints.txt` (fija `torch`, `torchvision` y `ultralytics`), y compara el resultado con el lock. Es el paso más largo (unos 8 minutos en la medición, por la descarga de torch). Verá avisos `Cache entry deserialization failed, entry ignored` de pip: son inofensivos.
2. `[2/4] Paquete de modelo`: deja en `../dataset` los archivos del modelo y **verifica su SHA-256** (sección 5).
3. `[3/4] Configuración`: crea `.env` y `.secrets/postgres_password.txt` con **sus propios secretos** (sección 6). Le pregunta usuario, carpeta de respaldos y contraseña.
4. `[4/4] Base de datos`: levanta PostgreSQL y Redis en Docker, crea la base, aplica las migraciones y registra el modelo.

Debe verse, al final, algo como:

```text
[2/4] Paquete de modelo
  ✓ yolov8x-pose.pt (descargado y verificado)
  ✓ lstm_6class/feature_stats.npz (copiado del repositorio y verificado)
  ✓ lstm_6class/checkpoints/20260928_141021/best_model.pt (copiado del repositorio y verificado)
  ✓ lstm_6class/checkpoints/20260928_141021/run_config.json (copiado del repositorio y verificado)
[3/4] Configuración
...
.env creado (permisos 600). Los secretos no se muestran.
[4/4] Base de datos
  ✓ base sabre creada
Registrado modelo_version <uuid> (lstm6class-20260928_141021): f1_macro_test=0.5249 activo=True
  ✓ migraciones aplicadas y modelo 20260928_141021 registrado como activo (si no había otro)

################################################################
#  Instalación terminada. En modo local con cpu no se exige la prueba de equivalencia.
#  Siguiente paso: arrancar Fog con  sh scripts/fog_nativo.sh
################################################################
```

(`base sabre creada` dice `sabre_revision` si usó `POSTGRES_DB_NAME=sabre_revision`.) Si el comando se interrumpe, se puede repetir: no borra nada y no toca lo que ya existe. Si ya tenía un volumen `sabre_pgdata` de otra instalación de SABRE.AI, el instalador lo dice (`Ya existe el volumen de PostgreSQL`) y le pide la contraseña de **esa** base en lugar de generar una; un equipo nuevo no ve esa pregunta. La carpeta de respaldos se crea sola si no existe.

No use `sh scripts/instalar_fog.sh probar`: esa prueba de equivalencia exige los 10 clips de referencia del autor y solo hace falta en modo remoto o con una GPU (`FOG_DEVICE` distinto de `cpu`).

## 5. Paquete de modelo (con hashes)

El sistema usa cuatro archivos, que **no se versionan todos del mismo modo**. Sus hashes SHA-256 están en `scripts/datos/MODELO.sha256` y son los de los resultados de la tesis:

| Archivo (en `dataset/`) | SHA-256 | Cómo se obtiene |
|---|---|---|
| `yolov8x-pose.pt` (133 MB, pesos de pose) | `7a9bf952c2fc1c07d4a1da00dbb4cfab5ed71f89cbe8824d51a8f7a61cee5825` | **No está en git.** El instalador lo descarga de la release oficial de Ultralytics (`https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8x-pose.pt`) y rechaza el archivo si el hash no coincide. |
| `lstm_6class/feature_stats.npz` (media y desviación de las 192 features) | `8d7464ae987a66c5355806d77d4b07dc58165394fda4bff89ec3506de0669b62` | Sí está en git (`backend/dataset/lstm_6class/`); el instalador lo copia a `../dataset`. |
| `lstm_6class/checkpoints/20260928_141021/best_model.pt` (checkpoint activo) | `382a03e368ed21368ba179632f2e7c0881c8f00876d82a54d900358e854b4505` | Sí está en git; ídem. |
| `lstm_6class/checkpoints/20260928_141021/run_config.json` (configuración de la corrida) | `93aeaeebce0ab78d5f31587dc5b8d5bd3ac6995dca80f5e52414093fe270978b` | Sí está en git; ídem. |

Además el instalador copia `lstm_6class/results/20260928_141021_metrics.json` (métricas de la corrida, de las que sale `f1_macro_test=0.5249`). Ese archivo no lleva hash propio.

**Verificar que usa el mismo modelo que los resultados** (desde `backend/`, tras instalar):

```bash
(cd ../dataset && shasum -a 256 -c ../backend/scripts/datos/MODELO.sha256)
```

Debe verse `OK` en las cuatro líneas. En Linux use `sha256sum -c` en lugar de `shasum -a 256 -c`. Cualquier otra salida significa que el archivo es distinto del de los resultados: no use ese equipo para comparar cifras.

**Instalación sin internet o con el paquete del autor.** `instalar_fog.sh instalar --paquete <carpeta>` usa los archivos de una carpeta con la estructura `modelo/<ruta>` (la que crea `instalar_fog.sh exportar`) y verifica los mismos hashes. El autor decide el medio de entrega:

> **[ENLACE A COMPLETAR POR EL AUTOR]** (paquete de modelo para instalar sin internet: `yolov8x-pose.pt`, `feature_stats.npz` y `checkpoints/20260928_141021/`).

Con el hueco sin completar, la instalación igualmente funciona con internet, por las dos vías de la tabla.

## 6. Secretos propios

**Nunca use valores del autor.** El instalador genera los suyos y no los muestra:

- `.secrets/postgres_password.txt`: contraseña de PostgreSQL, al azar (32 letras y números), permisos 600. Es la única fuente: no se copia a ningún `.env`.
- `.env` (permisos 600), creado desde `.env.example`, con:
  - `AUTH_USER`: el usuario maestro que usted elige. **Pregunta:** `Usuario maestro de Fog (AUTH_USER):`.
  - `AUTH_PASSWORD_HASH`: el hash Argon2id de la contraseña maestra que usted escribe (mínimo 16 caracteres, por `getpass`, sin eco). **Pregunta:** `Contraseña del usuario maestro (mínimo 16 caracteres):` y `Repetir contraseña:`. La contraseña en sí no se guarda en ningún archivo: **no hay forma de recuperarla**; anótela.
  - `AUTH_JWT_SECRET`: al azar (48 bytes).
  - `RESPALDO_DIR`: la carpeta donde se guardarán los respaldos de sesión. **Pregunta:** `Carpeta de respaldos (RESPALDO_DIR, fuera de Docker y del repo):`. Debe estar **fuera del repositorio y de Docker** (no use `~/.colima` ni `~/.docker`). Ejemplo: `~/sabre-respaldos`. Escriba la ruta completa.
- Con `ENTORNO=local` (por defecto), Fog **escucha en todas las interfaces** (`0.0.0.0:8001`) para que el frontend en Docker lo alcance. En una red compartida, cualquiera con la dirección llega a la pantalla de login (toda ruta exige token salvo `/health` y `/auth/login`, con bloqueo tras 5 fallos). Si no quiere eso, trabaje en una red de confianza o exporte `FOG_BIND_HOST=127.0.0.1` antes de `sh scripts/fog_nativo.sh`: Fog escucha solo en su equipo. Se verificó: `curl` a `http://localhost:8001/health` responde 200 y a la dirección de la red local (`http://<ip-de-su-equipo>:8001/health`) no conecta, y el inicio de sesión desde `http://localhost:8081` sigue funcionando (el navegador habla con `localhost:8001`).

Si ya tiene un `.env`, el instalador **no lo toca** y solo comprueba que defina `POSTGRES_PASSWORD` (o `.secrets/postgres_password.txt`), `AUTH_USER`, `AUTH_PASSWORD_HASH` y `AUTH_JWT_SECRET`.

Para cambiar la contraseña maestra más adelante: `.venv/bin/python scripts/crear_hash_password.py --env` imprime la línea `AUTH_PASSWORD_HASH='...'` lista para pegar en `.env` (reinicie Fog). El script `scripts/rotar_secretos.sh` rota además la PKI de Redis del despliegue remoto y no hace falta en el modo local.

## 7. Verificación

Con la instalación hecha, siga **A.1 a A.3** de [`GUIA_EJECUCION.md`](GUIA_EJECUCION.md) (levantar Docker y arrancar Fog) y compruebe:

1. **Estado del sistema.**

   ```bash
   curl -s -w " %{http_code}\n" http://localhost:8001/health
   ```

   Debe verse: `{"fog":"ok","redis":"ok","postgres":"ok"} 200`. Si algún componente dice `"error"`, el código es 503 (ver la solución de problemas de `GUIA_EJECUCION.md`).

2. **Interfaz.** Abra `http://localhost:8081`. Debe verse la pantalla "Iniciar sesión" y, tras entrar con el usuario y la contraseña de la sección 6, el encabezado SABRE.AI, `Modelo activo: lstm6class-20260928_141021` y el indicador "Conectado".

3. **Modelo activo** (necesita el token del login; `/modelo/activo` responde 401 sin él):

   ```bash
   TOKEN=$(curl -s -X POST http://localhost:8001/auth/login -H 'content-type: application/json' \
     -d '{"usuario":"<su usuario>","password":"<su contraseña>"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
   curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8001/modelo/activo
   ```

   Debe verse: `{"nombre":"lstm6class-20260928_141021","num_clases":6,"f1_macro_test":0.5249,"kappa_piloto":null}`.

4. **Cloud listo.**

   ```bash
   sh scripts/compose.sh -f docker-compose.yml -f docker-compose.nativo.yml logs cloud
   ```

   Debe verse: `modelo precalentado en N ms` y `Cloud escuchando 'fog:features' como 'cloud-worker-1'...`.

5. **Sugerencia de punta a punta.** Cargue un clip propio (MP4 o MOV de sable de ≥ 720p) siguiendo A.4 de `GUIA_EJECUCION.md`.

   > **[ORIGEN DE LOS CLIPS DE PRUEBA A DEFINIR POR EL AUTOR]** Este repositorio no incluye clips de competencia: sus derechos de imagen no son del autor y la política de datos (D-22) impide conservarlos. Cualquier clip MP4/MOV de sable de ≥ 720p sirve para probar el flujo.

**Prueba de humo (solo con el conjunto de datos del autor).** `scripts/prueba_humo.py` recorre un clip por clase de `dataset/dataset trimmed/test_trimmed` con las luces de `dataset/labels/`. Ese conjunto **no está en git** y no se distribuye, así que un revisor no puede correrla con lo que instala esta guía. En la ejecución de verificación de DOC01 se corrió, con acceso de solo lectura al conjunto del autor, sobre una base nueva y un evento propio, y dio:

```text
{"clip": "AttackA_0007", "frames": 15, "fps": 30.0, ..., "sugerida": "AttackB", "confianza": 0.534145, "clase_final": "AttackA", "decision": "cambiar", "veredicto_http": 200, "auditoria_seq": 12, ..., "ms_clip": 3076, ..., "inferencia_ms": 7}
... (una línea JSON por cada una de las 6 clases)
```

con código de salida 0 (6 de 6 veredictos registrados) y 29 s en total. Con ese evento, `exportar_evidencia.py` dio: 6 revisiones, latencia p95 5619 ms (umbral 60 000 ms: cumple), inferencia p95 7 ms (umbral 50 ms: cumple), κ = 0,4 (umbral 0,61: no cumple) y concordancia 50 % (n = 6). Son cifras de una prueba de humo de 6 clips, no de la validación.

## 8. Defectos encontrados al instalar en limpio

Hallados siguiendo la guía en un clon nuevo (DOC01). Los tres primeros se corrigieron en el código (con prueba que falla antes y pasa después); el resto son límites que la guía ya advierte.

| # | Qué falló | Causa | Corrección |
|---|---|---|---|
| 1 | `instalar_fog.sh instalar` se detenía en `[2/4]` con `falta yolov8x-pose.pt en .../dataset` en cualquier equipo sin la carpeta `dataset` del autor | El instalador exigía `../dataset` ya poblado o el paquete del autor | `instalador.py obtener-modelo`: copia lo versionado en `backend/dataset/`, descarga YOLO de la release oficial y verifica todo contra `MODELO.sha256` (`tests/shared/test_instalador.py`) |
| 2 | Tras instalar, el aviso decía "el equipo no está listo, falta `probar`" aunque en local no se exige y `probar` necesita clips del autor | Mensaje fijo | `mensaje_final_instalacion`: solo pide `probar` donde el bloqueo la exige (modo remoto o `FOG_DEVICE` distinto de `cpu`) |
| 3 | `registrar_modelo.py` buscaba las métricas siempre en `../dataset`, sin respetar `DATASET_DIR` | Ruta fija en el script | `instalar_fog.sh` y `fog_nativo.sh` pasan `--dataset-dir "$DS/lstm_6class"` |
| 4 | La suite de pruebas daba 1 fallo (`ModuleNotFoundError: sklearn`) con el entorno del lock | El lock de Fog no incluye `scikit-learn` (solo `requirements.txt`) | Documentado en [`GUIA_DESARROLLO.md`](GUIA_DESARROLLO.md): `pip install scikit-learn==1.9.1`. No se edita el lock a mano |
| 5 | `exportar_evidencia.py` imprimió `ERROR: el evento ... no existe en la base sabre` y siguió | Con una base distinta de `sabre`, el respaldo que invoca usa `POSTGRES_DB_NAME` (por defecto `sabre`) | Documentado: exporte `POSTGRES_DB_NAME` (y `POSTGRES_HOST_PORT` si cambió el puerto) antes de los scripts |
| 6 | El primer intento de `instalar` terminó sin mensaje durante el paso 1 y quedó un `pip` huérfano instalando en el mismo `.venv` | No determinada: ocurrió al lanzar el instalador desde un proceso en segundo plano de la sesión de automatización con la que se hizo la verificación; no se repitió en el segundo intento | Se borró el `.venv` y se repitió. Si `instalar` se interrumpe, compruebe con `pgrep -fl "pip install"` que no queda un `pip` vivo antes de repetir |
