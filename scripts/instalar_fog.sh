#!/bin/sh
# Instalar o migrar Fog entre equipos (DEPLOY10). POSIX sh, idempotente. Ningún subcomando borra datos:
# no hay `down -v`, `volume rm` ni `DROP DATABASE` sobre bases que contengan datos.
#
# Uso, desde backend/:
#   sh scripts/instalar_fog.sh verificar [--remoto]      comprueba requisitos sin cambiar nada
#   sh scripts/instalar_fog.sh modo [--remoto]           muestra el modo y los archivos de configuración que se cargarían
#   (todas las órdenes son LOCALES por defecto: .secrets/fog_remoto.env y ENTORNO=remoto solo con --remoto)
#   sh scripts/instalar_fog.sh instalar [--paquete DIR]  entorno, modelo, .env, base (DIR: paquete de `exportar`)
#   sh scripts/instalar_fog.sh exportar --destino DIR --evento UUID    (equipo de origen)
#   sh scripts/instalar_fog.sh importar --desde DIR      (equipo de destino, tras `instalar`)
#   sh scripts/instalar_fog.sh probar                    prueba de equivalencia (10 clips de referencia)
#   sh scripts/instalar_fog.sh estado
#
# Variables opcionales: ENV_FILE (por defecto .env; con --remoto, también .secrets/fog_remoto.env encima), VENV_DIR (.venv), DATOS_DIR (./datos), DATASET_DIR (../dataset),
# MODEL_RUN_ID, FOG_DEVICE (cpu), POSTGRES_DB_NAME (sabre), PYTHON_BIN (python3), ESPACIO_MIN_GB (7).
# Ver docs/manuales/GUIA_INSTALACION.md, sección "Instalar o migrar Fog a otro equipo".
set -eu

cd "$(dirname "$0")/.."
BACKEND_DIR=$(pwd)
. scripts/lib_compose.sh

[ -z "${ENV_FILE:-}" ] || ENV_FILE_EXPLICITO=1
ENV_FILE=${ENV_FILE:-.env}
. scripts/lib_fog_env.sh
VENV_DIR=${VENV_DIR:-.venv}
PY_SIS=${PYTHON_BIN:-python3}
COMPOSE_ARCHIVOS="-f docker-compose.yml -f docker-compose.nativo.yml"
FALTAS=0
# Pesos de pose de la release oficial de Ultralytics (la misma URL y el mismo SHA-256 que fog/Dockerfile).
YOLO_POSE_URL=${YOLO_POSE_URL:-https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8x-pose.pt}

fallo() { echo "ERROR: $*" >&2; exit 1; }
ok() { echo "  ✓ $*"; }
aviso() { echo "  ! $*"; }
falta() { # falta <qué> <cómo se arregla>
    FALTAS=$((FALTAS + 1))
    echo "  ✗ $1"
    shift
    for linea in "$@"; do echo "      → $linea"; done
}

sha256_de() {
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1; else sha256sum "$1" | cut -d' ' -f1; fi
}

plataforma() {
    case "$(uname -s)/$(uname -m)" in
        Darwin/arm64) echo macos-arm64 ;;
        Linux/x86_64) echo linux-x86_64 ;;
        *) echo desconocida ;;
    esac
}

archivo_lock() {
    case "$(plataforma)" in
        macos-arm64) echo requirements-fog.lock ;;
        linux-x86_64) echo requirements-fog.linux-x86_64.lock ;;
        *) echo "" ;;
    esac
}

cargar_env() {
    cargar_archivos_env
    aplicar_modo
}

puerto_ocupado() {
    "$PY_SIS" -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(('127.0.0.1',int(sys.argv[1])))==0 else 1)" "$1"
}

dataset_dir() {
    DS=${DATASET_DIR:-$BACKEND_DIR/../dataset}
    [ -d "$DS" ] && DS=$(cd "$DS" && pwd)
    printf '%s' "$DS"
}

venv_python() {
    [ -x "$VENV_DIR/bin/python" ] || fallo "falta $VENV_DIR (corra: sh scripts/instalar_fog.sh instalar)"
    printf '%s' "$VENV_DIR/bin/python"
}

# ---------------------------------------------------------------- verificar
cmd_verificar() {
    remoto=$MODO_REMOTO
    cargar_env
    FALTAS=0
    so=$(uname -s)
    echo "Verificación (no cambia nada):"

    plat=$(plataforma)
    if [ "$plat" = desconocida ]; then
        falta "Plataforma no soportada: $(uname -s) $(uname -m)" \
              "Soportado: macOS arm64 y Linux x86_64. Windows queda fuera."
    else
        ok "Plataforma: $plat"
    fi

    lock=$(archivo_lock)
    if command -v "$PY_SIS" >/dev/null 2>&1; then
        version=$("$PY_SIS" -c 'import platform; print(platform.python_version())')
        requerida=""
        [ -n "$lock" ] && [ -f "$lock" ] && requerida=$(sed -n 's/^# python: //p' "$lock" | head -n 1)
        if [ -n "$requerida" ] && [ "${version%.*}" != "${requerida%.*}" ]; then
            falta "Python $version; el lock se generó con $requerida (misma versión menor ${requerida%.*})" \
                  "macOS: brew install python@${requerida%.*}" \
                  "Linux: instale Python ${requerida%.*} (https://www.python.org/downloads/) y use PYTHON_BIN=python${requerida%.*}"
        else
            ok "Python $version"
        fi
    else
        falta "No hay $PY_SIS" "macOS: brew install python" "Linux: instale python3 con el gestor de paquetes"
    fi

    for herramienta in git tar; do
        command -v "$herramienta" >/dev/null 2>&1 || falta "No hay $herramienta" "Instálelo con el gestor de paquetes del sistema"
    done
    if ! command -v shasum >/dev/null 2>&1 && ! command -v sha256sum >/dev/null 2>&1; then
        falta "No hay shasum ni sha256sum" "Linux: paquete coreutils"
    fi

    if ! command -v docker >/dev/null 2>&1; then
        falta "No hay docker (CLI)" \
              "macOS: brew install colima docker" \
              "Linux: Docker Engine, https://docs.docker.com/engine/install/"
    elif ! docker info >/dev/null 2>&1; then
        if [ "$so" = Darwin ]; then
            falta "Docker no responde (Colima apagado)" "colima start --cpu 2 --memory 4"
        else
            falta "Docker no responde" "sudo systemctl start docker (y su usuario en el grupo docker)"
        fi
    else
        ok "Docker en marcha ($(docker context show 2>/dev/null || echo ?))"
    fi

    if detectar_compose; then
        ok "Compose: $COMPOSE_CMD"
    else
        falta "No hay Docker Compose ni 'docker compose' ni 'docker-compose'" \
              "macOS con Colima: brew install docker-compose (queda como 'docker-compose'; para usarlo como plugin," \
              "  registre /opt/homebrew/lib/docker/cli-plugins en \"cliPluginsExtraDirs\" de ~/.docker/config.json)" \
              "Linux: plugin oficial, https://docs.docker.com/compose/install/linux/ (paquete docker-compose-plugin)"
    fi

    minimo=${ESPACIO_MIN_GB:-7}
    libres_kb=$(df -Pk "$BACKEND_DIR" | awk 'NR==2 {print $4}')
    libres_gb=$((libres_kb / 1048576))
    if [ "$libres_gb" -lt "$minimo" ]; then
        falta "Espacio libre: ${libres_gb} GB (mínimo $minimo GB)" \
              "Libere espacio. El mínimo de 7 GB es el único valor medido (GUIA_INSTALACION §1, build de Docker); no hay mínimo medido para el modo nativo."
    else
        ok "Espacio libre: ${libres_gb} GB (mínimo $minimo GB)"
    fi

    for par in "FOG_HOST_PORT:${FOG_HOST_PORT:-8001}" "POSTGRES_HOST_PORT:${POSTGRES_HOST_PORT:-5436}" "REDIS_HOST_PORT:${REDIS_HOST_PORT:-6380}"; do
        nombre=${par%%:*}
        puerto=${par#*:}
        if puerto_ocupado "$puerto"; then
            propio=""
            command -v docker >/dev/null 2>&1 && propio=$(docker ps --filter "publish=$puerto" --format '{{.Names}}' 2>/dev/null | grep '^sabre-' | head -n 1 || true)
            fog_propio=""
            if [ "$nombre" = FOG_HOST_PORT ] && command -v lsof >/dev/null 2>&1; then
                for pid in $(lsof -nP -iTCP:"$puerto" -sTCP:LISTEN -t 2>/dev/null); do
                    ps -p "$pid" -o command= 2>/dev/null | grep -q 'fog\.main:app' && fog_propio=$pid
                done
            fi
            if [ -n "$propio" ]; then
                ok "Puerto $puerto ($nombre): lo publica $propio, el compose de SABRE.AI"
            elif [ -n "$fog_propio" ]; then
                ok "Puerto $puerto ($nombre): lo usa Fog ya en marcha (pid $fog_propio)"
            else
                falta "Puerto $puerto ($nombre) ocupado" "Cambie $nombre en $ENV_FILE o detenga lo que lo usa (lsof -i :$puerto)"
            fi
        else
            ok "Puerto $puerto ($nombre) libre"
        fi
    done

    if [ "$remoto" = 1 ]; then
        modo=${FOG_REMOTO_MODO:-tailscale}
        if [ "$modo" = cloudflared ]; then
            command -v cloudflared >/dev/null 2>&1 && ok "cloudflared instalado" \
                || falta "No hay cloudflared (modo remoto)" "macOS: brew install cloudflared" "Linux: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
        else
            command -v tailscale >/dev/null 2>&1 && ok "tailscale instalado" \
                || falta "No hay tailscale (modo remoto)" "https://tailscale.com/download"
        fi
    else
        aviso "Modo remoto no verificado (use: verificar --remoto)"
    fi

    echo
    if [ "$FALTAS" -gt 0 ]; then
        echo "Falta $FALTAS cosa(s). Este comando no instala nada del sistema."
        return 1
    fi
    echo "Requisitos cumplidos."
}

# ---------------------------------------------------------------- instalar
paso_entorno() {
    echo "[1/4] Entorno Python"
    lock=$(archivo_lock)
    [ -n "$lock" ] && [ -f "$lock" ] || fallo "no hay lock para esta plataforma ($(plataforma))"
    for pin in torch torchvision ultralytics; do
        esperado=$(sed -n "s/^$pin==//p" constraints.txt | head -n 1)
        obtenido=$(sed -n "s/^$pin==//p" "$lock" | head -n 1)
        [ -n "$esperado" ] && [ "$esperado" = "$obtenido" ] \
            || fallo "$lock fija $pin==${obtenido:-?} y constraints.txt pide ${esperado:-?}. Se detiene: no se cambia la versión por su cuenta."
    done
    if [ ! -x "$VENV_DIR/bin/python" ]; then
        "$PY_SIS" -m venv "$VENV_DIR" || fallo "no pude crear $VENV_DIR"
        ok "creado $VENV_DIR"
    else
        ok "$VENV_DIR ya existe"
    fi
    "$VENV_DIR/bin/python" -m pip install --quiet --disable-pip-version-check -r "$lock" -c constraints.txt \
        || fallo "pip no pudo instalar $lock (si en Linux falta una versión, repórtelo: no se sustituye)"
    t1=$(mktemp); t2=$(mktemp)
    sed -e '/^#/d' -e '/^$/d' "$lock" | tr 'A-Z_' 'a-z-' | sort > "$t1"
    "$VENV_DIR/bin/python" -m pip freeze --disable-pip-version-check | tr 'A-Z_' 'a-z-' | sort > "$t2"
    distintos=$(comm -23 "$t1" "$t2" || true)
    rm -f "$t1" "$t2"
    [ -z "$distintos" ] || fallo "el entorno no coincide con $lock: $(echo "$distintos" | tr '\n' ' ')"
    ok "dependencias = $lock"
}

paso_modelo() {
    echo "[2/4] Paquete de modelo"
    ds=$(dataset_dir)
    [ -d "$ds" ] || { mkdir -p "$ds" && ds=$(cd "$ds" && pwd); }
    while read -r hash ruta; do
        [ -n "$hash" ] || continue
        destino="$ds/$ruta"
        if [ -f "$destino" ]; then
            [ "$(sha256_de "$destino")" = "$hash" ] \
                || fallo "$destino existe pero su hash no coincide con scripts/datos/MODELO.sha256. No se sobrescribe."
            ok "$ruta"
        elif [ -n "${PAQUETE:-}" ] && [ -f "$PAQUETE/modelo/$ruta" ]; then
            [ "$(sha256_de "$PAQUETE/modelo/$ruta")" = "$hash" ] || fallo "$PAQUETE/modelo/$ruta no coincide con MODELO.sha256"
            mkdir -p "$(dirname "$destino")"
            cp "$PAQUETE/modelo/$ruta" "$destino"
            [ "$(sha256_de "$destino")" = "$hash" ] || fallo "la copia de $ruta no coincide con MODELO.sha256"
            ok "$ruta (copiado del paquete y verificado)"
        else
            # Sin paquete (DOC01): el checkpoint y las estadísticas están versionados en backend/dataset/; los pesos
            # de YOLO se descargan de la release oficial de Ultralytics. Todo se verifica contra MODELO.sha256.
            url=""
            [ "$ruta" != yolov8x-pose.pt ] || url=$YOLO_POSE_URL
            como=$("$PY_SIS" scripts/instalador.py obtener-modelo --dataset "$ds" --ruta "$ruta" --hash "$hash" \
                    --origen-repo "$BACKEND_DIR/dataset" ${url:+--url "$url"}) \
                || fallo "no pude obtener $ruta. Use el paquete de modelo del autor: instalar --paquete <carpeta de exportar>"
            ok "$ruta ($como y verificado)"
        fi
    done < scripts/datos/MODELO.sha256
    # registrar_modelo.py lee las métricas de la corrida (results/<run>_metrics.json); no llevan hash propio.
    "$PY_SIS" scripts/instalador.py fusionar "$BACKEND_DIR/dataset/lstm_6class/results" "$ds/lstm_6class/results" >/dev/null \
        || aviso "las métricas de $ds/lstm_6class/results difieren de las del repositorio (se conservan las existentes)"
    if [ -n "${PAQUETE:-}" ] && [ -d "$PAQUETE/referencia/clips" ]; then
        datos=${DATOS_DIR:-./datos}
        mkdir -p "$datos/referencia/clips"
        for clip in "$PAQUETE"/referencia/clips/*.mp4; do
            [ -e "$datos/referencia/clips/$(basename "$clip")" ] || cp "$clip" "$datos/referencia/clips/"
        done
        ok "clips de referencia en $datos/referencia/clips"
    fi
}

volumen_pg_existe() {
    docker volume ls -q 2>/dev/null | grep -Eq '(^|_)sabre_pgdata$'
}

paso_env() {
    echo "[3/4] Configuración"
    if [ -n "$(archivos_env)" ]; then
        faltan=""
        for clave in POSTGRES_PASSWORD AUTH_USER AUTH_PASSWORD_HASH AUTH_JWT_SECRET; do
            valor=$( (set +u; cargar_archivos_env >/dev/null 2>&1; eval "printf '%s' \"\${$clave:-}\"") )
            [ -n "$valor" ] || faltan="$faltan $clave"
        done
        [ -z "$faltan" ] || fallo "la configuración ($(archivos_env | tr '\n' ' ')) no define:$faltan. No se modifica; complétela a mano."
        ok "configuración existente (no se toca): $(archivos_env | tr '\n' ' ')"
        [ -n "${RESPALDO_DIR:-}" ] || aviso "RESPALDO_DIR no está definida (sin ella no hay respaldo; ver .env.example)"
    else
        opcion=""
        volumen_pg_existe && opcion="--volumen-existente"
        # shellcheck disable=SC2086
        "$(venv_python)" scripts/instalador.py generar-env --plantilla .env.example --destino "$ENV_FILE" $opcion \
            || fallo "no se creó $ENV_FILE"
        echo "      Certificado y clave de cliente de Redis del nodo Fog: se importan aparte (ver LEEME_MIGRACION.md / SEC01)."
    fi
}

esperar_postgres() {
    n=0
    until docker exec "$PG_CONT" pg_isready -h 127.0.0.1 -U "$PGUSR" >/dev/null 2>&1; do
        n=$((n + 1))
        [ "$n" -le 60 ] || fallo "PostgreSQL no arrancó en 60 s"
        sleep 1
    done
}

asegurar_base() { # crea la base si no existe (nunca borra)
    case "$PGBASE" in *[!A-Za-z0-9_]*|"") fallo "POSTGRES_DB_NAME inválido: $PGBASE (solo letras, números y _)" ;; esac
    existe=$(psql_base postgres "SELECT count(*) FROM pg_database WHERE datname = '$PGBASE'")
    if [ "$existe" = 0 ]; then
        psql_base postgres "CREATE DATABASE \"$PGBASE\"" >/dev/null
        ok "base $PGBASE creada"
    else
        ok "base $PGBASE ya existe"
    fi
}

paso_base() {
    echo "[4/4] Base de datos"
    cargar_env
    . scripts/lib_respaldo.sh
    if volumen_pg_existe; then
        ok "el volumen de PostgreSQL (sabre_pgdata) ya existe: se conserva sin tocarlo"
    fi
    # Si ya están en marcha no se vuelve a correr `up`: con otra configuración (p. ej. otra POSTGRES_PASSWORD
    # en .secrets) Compose recrearía el contenedor en vez de dejarlo como está.
    redis_activo=$(docker ps -q --filter "publish=${REDIS_HOST_PORT:-6380}" 2>/dev/null | head -n 1 || true)
    if buscar_contenedor && [ -n "$redis_activo" ]; then
        ok "PostgreSQL y Redis ya están en marcha: no se tocan"
    else
        # shellcheck disable=SC2086
        compose $COMPOSE_ARCHIVOS up -d postgres redis || fallo "compose no pudo levantar postgres y redis"
    fi
    buscar_contenedor || fallo "no encuentro el contenedor de PostgreSQL"
    esperar_postgres
    asegurar_base
    . scripts/lib_fog_env.sh
    exportar_entorno_fog
    py=$(venv_python)
    "$py" -m alembic upgrade head || fallo "alembic upgrade head falló"
    "$py" scripts/registrar_modelo.py "$MODEL_RUN_ID" --solo-si-no-hay-activo --dataset-dir "$DS/lstm_6class" || fallo "no se pudo registrar el modelo activo"
    ok "migraciones aplicadas y modelo $MODEL_RUN_ID registrado como activo (si no había otro)"
}

cmd_instalar() {
    PAQUETE=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --paquete) PAQUETE=${2:-}; shift 2 || fallo "--paquete necesita un valor" ;;
            *) fallo "argumento desconocido: $1" ;;
        esac
    done
    [ -z "$PAQUETE" ] || { PAQUETE=$(cd "$PAQUETE" && pwd) || fallo "no existe el paquete"; }
    cmd_verificar || fallo "corrija lo anterior y repita (instalar no instala nada del sistema)"
    echo
    paso_entorno
    paso_modelo
    paso_env
    paso_base
    echo
    remoto=""
    [ "$MODO_REMOTO" = 1 ] && remoto="--remoto"
    echo "################################################################"
    # shellcheck disable=SC2086
    "$PY_SIS" scripts/instalador.py mensaje-final --dispositivo "${FOG_DEVICE:-cpu}" $remoto | sed 's/^/#  /'
    echo "################################################################"
}

# ---------------------------------------------------------------- exportar
cmd_exportar() {
    DESTINO=""
    EVENTO=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --destino) DESTINO=${2:-}; shift 2 || fallo "--destino necesita un valor" ;;
            --evento) EVENTO=${2:-}; shift 2 || fallo "--evento necesita un valor" ;;
            *) fallo "argumento desconocido: $1" ;;
        esac
    done
    [ -n "$DESTINO" ] || fallo "falta --destino <dir>"
    cargar_env
    . scripts/lib_respaldo.sh
    command -v docker >/dev/null 2>&1 || fallo "docker no está disponible"
    buscar_contenedor || fallo "no encuentro el contenedor de PostgreSQL (levante el compose)"
    if [ -z "$EVENTO" ]; then
        echo "Falta --evento <uuid>. Eventos de la base '$PGBASE':" >&2
        psql_base "$PGBASE" "SELECT id || '  ' || nombre FROM sabre.evento ORDER BY nombre" >&2 || true
        exit 1
    fi
    if [ -e "$DESTINO" ] && [ -n "$(ls -A "$DESTINO" 2>/dev/null)" ]; then
        fallo "$DESTINO no está vacío: no se sobrescribe ni se mezcla con otro paquete"
    fi
    mkdir -p "$DESTINO"
    DESTINO=$(cd "$DESTINO" && pwd -P)
    case "$DESTINO/" in
        "$BACKEND_DIR"/*|"$(git rev-parse --show-toplevel 2>/dev/null || echo /nonexistente)"/*)
            fallo "el destino ($DESTINO) está dentro del repo; use una carpeta externa" ;;
    esac

    echo "Exportando la base '$PGBASE' (evento $EVENTO) a $DESTINO"
    antes=$(psql_base "$PGBASE" "$SQL_CONTEOS")
    mkdir -p "$DESTINO/respaldo"
    RESPALDO_DIR="$DESTINO/respaldo" ENV_FILE="$ENV_FILE" sh scripts/respaldar_sesion.sh --evento "$EVENTO" \
        || fallo "el respaldo verificado falló"
    despues=$(psql_base "$PGBASE" "$SQL_CONTEOS")
    [ "$antes" = "$despues" ] || fallo "la base cambió durante la exportación ($antes -> $despues); repita con Fog en reposo"
    printf '%s\n' "$antes" > "$DESTINO/CONTEOS.txt"

    ds=$(dataset_dir)
    while read -r hash ruta; do
        [ -n "$hash" ] || continue
        [ "$(sha256_de "$ds/$ruta")" = "$hash" ] || fallo "$ds/$ruta no coincide con MODELO.sha256; no se exporta un modelo distinto"
        mkdir -p "$DESTINO/modelo/$(dirname "$ruta")"
        cp "$ds/$ruta" "$DESTINO/modelo/$ruta"
    done < scripts/datos/MODELO.sha256
    mkdir -p "$DESTINO/lock" "$DESTINO/referencia/clips"
    cp requirements-fog.lock requirements-fog.linux-x86_64.lock constraints.txt scripts/datos/MODELO.sha256 "$DESTINO/lock/"
    "$PY_SIS" scripts/instalador.py lista-clips --dataset "$ds" --extra "${DATOS_DIR:-./datos}/referencia/clips" \
        | while read -r clip; do cp "$clip" "$DESTINO/referencia/clips/"; done
    [ "$(ls "$DESTINO/referencia/clips" | wc -l)" -gt 0 ] || fallo "no se pudieron copiar los clips de referencia"

    commit_main=$(git rev-parse main 2>/dev/null || echo desconocido)
    cat > "$DESTINO/LEEME_MIGRACION.md" <<LEEME
# Migración de Fog (DEPLOY10)

- Fecha (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)
- Equipo de origen: $(hostname -s) ($(plataforma))
- **Código: commit de \`main\` = \`$commit_main\`** (HEAD de origen: \`$(git rev-parse HEAD 2>/dev/null)\`, rama \`$(git branch --show-current 2>/dev/null)\`).
  En el destino: \`git clone\` del repo SaberAITesis y \`git checkout $commit_main\`.
- Base: \`$PGBASE\`; evento respaldado: \`$EVENTO\`.
- Conteos (revisiones,clasificaciones,veredictos,auditoría): \`$antes\`
- Modelo: \`${MODEL_RUN_ID:-$MODEL_RUN_ID_POR_DEFECTO}\`; FOG_DEVICE de origen: \`${FOG_DEVICE:-cpu}\`.

## Contenido
- \`respaldo/R<NNN>-<fecha>/\`: dump, .tgz (storage sin clips y evidencia) y MANIFEST.sha256, verificado al exportar.
- \`modelo/\`: yolov8x-pose.pt, feature_stats.npz y checkpoints/<run>/ (se verifican contra scripts/datos/MODELO.sha256).
- \`lock/\`: requirements-fog.lock (macOS arm64), requirements-fog.linux-x86_64.lock y constraints.txt.
- \`referencia/clips/\`: los 10 clips de la prueba de equivalencia.
- \`MANIFEST.sha256\`: hash de todo lo anterior; \`importar\` lo verifica antes de tocar nada.

## NO incluido (se mueve a mano)
Las claves privadas y secretos **no** entran al paquete: \`.env\`, \`.secrets/\`, y el certificado y la clave de
cliente de Redis del nodo Fog (\`REDIS_TLS_CERT\`, \`REDIS_TLS_KEY\`, SEC01). Cópielos por un canal propio
(llave USB cifrada o \`scp\` entre equipos suyos), con permisos 600, y no los deje en el paquete ni en el repo.
\`.env\` del destino lo genera \`instalar\`: no copie el del origen.

## En el equipo de destino
1. \`sh scripts/instalar_fog.sh verificar\`
2. \`sh scripts/instalar_fog.sh instalar --paquete <esta carpeta>\`
3. \`sh scripts/instalar_fog.sh importar --desde <esta carpeta>\`
4. \`sh scripts/instalar_fog.sh probar\` — hasta que pase, el equipo no está listo.
LEEME
    "$PY_SIS" scripts/instalador.py manifiesto-crear "$DESTINO"
    "$PY_SIS" scripts/instalador.py manifiesto-verificar "$DESTINO" || fallo "el manifiesto recién creado no verifica"
    echo "Paquete exportado y verificado: $DESTINO"
}

# ---------------------------------------------------------------- importar
cmd_importar() {
    DESDE=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --desde) DESDE=${2:-}; shift 2 || fallo "--desde necesita un valor" ;;
            *) fallo "argumento desconocido: $1" ;;
        esac
    done
    [ -n "$DESDE" ] && [ -d "$DESDE" ] || fallo "falta --desde <carpeta del paquete>"
    DESDE=$(cd "$DESDE" && pwd -P)
    echo "Verificando el manifiesto de $DESDE"
    "$PY_SIS" scripts/instalador.py manifiesto-verificar "$DESDE" || fallo "el paquete no coincide con su manifiesto; no se importa nada"

    cargar_env
    . scripts/lib_respaldo.sh
    command -v docker >/dev/null 2>&1 || fallo "docker no está disponible"
    buscar_contenedor || fallo "no encuentro el contenedor de PostgreSQL (¿corrió instalar?)"
    esperado=$(cat "$DESDE/CONTEOS.txt")
    carpeta=$(ls -d "$DESDE"/respaldo/R[0-9][0-9][0-9]-* 2>/dev/null | grep -v '\.FALLIDO$' | tail -n 1 || true)
    [ -n "$carpeta" ] || fallo "no hay carpeta de respaldo en $DESDE/respaldo"
    dump=$(ls "$carpeta"/*.dump | head -n 1)
    tgz=$(ls "$carpeta"/*.tgz | head -n 1)

    case "$PGBASE" in *[!A-Za-z0-9_]*|"") fallo "POSTGRES_DB_NAME inválido: $PGBASE" ;; esac
    existe=$(psql_base postgres "SELECT count(*) FROM pg_database WHERE datname = '$PGBASE'")
    if [ "$existe" != 0 ]; then
        actuales=$(psql_base "$PGBASE" "$SQL_CONTEOS" 2>/dev/null) || actuales="0,0,0,0"
        if ! "$PY_SIS" scripts/instalador.py base-vacia "$actuales"; then
            fallo "la base $PGBASE ya tiene revisiones ($actuales): se niega a importar sobre ella"
        fi
    fi

    TMP="${PGBASE}_import_$(date +%s)"
    echo "Restaurando el dump en una base nueva ($TMP); la base $PGBASE no se toca hasta verificar"
    psql_base postgres "CREATE DATABASE \"$TMP\"" >/dev/null
    docker exec -i "$PG_CONT" pg_restore --exit-on-error -U "$PGUSR" -d "$TMP" < "$dump" \
        || fallo "pg_restore falló (la base $TMP queda para diagnóstico; bórrela usted: DROP DATABASE \"$TMP\")"
    obtenidos=$(psql_base "$TMP" "$SQL_CONTEOS")
    echo "  conteos esperados: $esperado | restaurados: $obtenidos"
    [ "$obtenidos" = "$esperado" ] || fallo "los conteos no coinciden (la base $TMP queda para diagnóstico)"
    filas=$(psql_base "$TMP" "SELECT count(*) FROM sabre.fn_verificar_auditoria()")
    echo "  fn_verificar_auditoria(): $filas filas alteradas"
    [ "$filas" = 0 ] || fallo "la cadena de auditoría restaurada tiene registros alterados (la base $TMP queda para diagnóstico)"

    if [ "$existe" != 0 ]; then
        conexiones=$(psql_base postgres "SELECT count(*) FROM pg_stat_activity WHERE datname = '$PGBASE'")
        [ "$conexiones" = 0 ] || fallo "$conexiones conexiones abiertas a $PGBASE: detenga Fog y repita (la base $TMP queda lista)"
        previa="${PGBASE}_previa_$(date +%s)"
        psql_base postgres "ALTER DATABASE \"$PGBASE\" RENAME TO \"$previa\"" >/dev/null
        echo "  la base vacía anterior se conserva como $previa (bórrela usted cuando quiera: DROP DATABASE \"$previa\")"
    fi
    psql_base postgres "ALTER DATABASE \"$TMP\" RENAME TO \"$PGBASE\"" >/dev/null

    . scripts/lib_fog_env.sh
    exportar_entorno_fog
    py=$(venv_python)
    "$py" -m alembic upgrade head || fallo "alembic upgrade head falló tras importar"
    "$py" scripts/registrar_modelo.py "$MODEL_RUN_ID" --solo-si-no-hay-activo --dataset-dir "$DS/lstm_6class" || fallo "no se pudo verificar el modelo activo"
    final=$(psql_base "$PGBASE" "$SQL_CONTEOS")
    [ "$final" = "$esperado" ] || fallo "conteos finales distintos de los esperados: $final"
    filas=$(psql_base "$PGBASE" "SELECT count(*) FROM sabre.fn_verificar_auditoria()")
    [ "$filas" = 0 ] || fallo "fn_verificar_auditoria() devolvió $filas filas en la base final"
    echo "Base $PGBASE: conteos $final, auditoría 0 filas"

    tmpd=$(mktemp -d)
    tar -xzf "$tgz" -C "$tmpd" || fallo "no pude extraer $tgz"
    datos=${DATOS_DIR:-./datos}
    mkdir -p "$datos/storage" "$datos/evidencia"
    for parte in storage evidencia; do
        [ -d "$tmpd/$parte" ] || continue
        echo "Restaurando datos/$parte (sin pisar archivos existentes)"
        "$PY_SIS" scripts/instalador.py fusionar "$tmpd/$parte" "$datos/$parte" || aviso "hubo conflictos en $parte; revise arriba"
    done
    rm -rf "$tmpd"
    echo
    echo "Importación terminada. Siguiente paso: sh scripts/instalar_fog.sh probar"
}

# ---------------------------------------------------------------- probar
cmd_probar() {
    cargar_env
    . scripts/lib_fog_env.sh
    exportar_entorno_fog
    py=$(venv_python)
    echo "Verificando el paquete de modelo contra MODELO.sha256"
    "$PY_SIS" scripts/instalador.py manifiesto-verificar "$(dataset_dir)" --nombre "$BACKEND_DIR/scripts/datos/MODELO.sha256" --no-estricto \
        || fallo "el modelo de este equipo no es el verificado; no se prueba"
    if [ -d "$DATOS_DIR/referencia/clips" ]; then
        CLIPS_REFERENCIA_DIR="$DATOS_DIR/referencia/clips"
        export CLIPS_REFERENCIA_DIR
    fi
    export DATASET_DIR MODEL_RUN_ID DATOS_DIR
    DATASET_DIR=$(dataset_dir)
    echo "Prueba de equivalencia con FOG_DEVICE=$FOG_DEVICE (10 clips; tarda unos minutos)"
    "$py" scripts/equivalencia.py probar
}

# ---------------------------------------------------------------- estado
cmd_estado() {
    cargar_env
    . scripts/lib_respaldo.sh
    . scripts/lib_fog_env.sh
    datos=${DATOS_DIR:-./datos}
    echo "Versión:        $(git describe --tags --always 2>/dev/null || echo ?) (rama $(git branch --show-current 2>/dev/null))"
    echo "Commit:         $(git rev-parse HEAD 2>/dev/null || echo ?)"
    activo="no disponible (¿Docker o la base apagados?)"
    if command -v docker >/dev/null 2>&1 && buscar_contenedor; then
        activo=$(psql_base "$PGBASE" "SELECT nombre || ' (sha256 ' || left(checkpoint_sha256, 12) || ')' FROM sabre.modelo_version WHERE activo" 2>/dev/null) \
            || activo="no disponible (base $PGBASE inaccesible)"
        [ -n "$activo" ] || activo="ninguno"
    fi
    echo "Modelo activo:  $activo"
    echo "Dispositivo:    FOG_DEVICE=${FOG_DEVICE:-cpu}"
    leer_respaldo_dir
    if [ -z "$RESPALDO_DIR" ]; then
        echo "Último respaldo: RESPALDO_DIR no definida"
    elif [ -f "$(archivo_ultimo)" ]; then
        echo "Último respaldo: $(cat "$(archivo_ultimo)")"
    else
        echo "Último respaldo: ninguno registrado para '$PGBASE'"
    fi
    if [ -f "$datos/fog_remoto_modo.txt" ] || [ -f "$datos/fog_remoto_tunel.pid" ] || [ -f "$datos/fog_remoto_vence.txt" ]; then
        echo "Túnel:          ABIERTO o con restos ($(DATOS_DIR="$datos" sh scripts/fog_remoto.sh status 2>&1 | head -n 1))"
    else
        echo "Túnel:          cerrado"
    fi
    echo "Última probar:  $("$PY_SIS" scripts/instalador.py estado-probar --datos "$datos")"
}

# MODO LOCAL POR DEFECTO: el modo remoto (cargar .secrets/fog_remoto.env y ENTORNO=remoto) solo con `--remoto`.
MODO_REMOTO=0
n_args=$#
while [ "$n_args" -gt 0 ]; do
    argumento=$1
    shift
    n_args=$((n_args - 1))
    if [ "$argumento" = "--remoto" ]; then MODO_REMOTO=1; else set -- "$@" "$argumento"; fi
done
export MODO_REMOTO

cmd_modo() {
    echo "modo: $([ "$MODO_REMOTO" = 1 ] && echo remoto || echo local)"
    echo "archivos: $(archivos_env | tr '\n' ' ')"
    echo "clave de PostgreSQL: $([ -s "$(archivo_clave_postgres)" ] && echo "de $(archivo_clave_postgres)" || echo "de los .env (no hay $(archivo_clave_postgres))")"
}

case "${1:-}" in
    modo) shift; cmd_modo "$@" ;;
    verificar) shift; cmd_verificar "$@" ;;
    instalar) shift; cmd_instalar "$@" ;;
    exportar) shift; cmd_exportar "$@" ;;
    importar) shift; cmd_importar "$@" ;;
    probar) shift; cmd_probar "$@" ;;
    estado) shift; cmd_estado "$@" ;;
    *) echo "Uso: sh scripts/instalar_fog.sh {modo|verificar|instalar [--paquete DIR]|exportar --destino DIR --evento UUID|importar --desde DIR|probar|estado} [--remoto]  (local por defecto)" >&2; exit 2 ;;
esac
