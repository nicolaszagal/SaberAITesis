#!/bin/sh
# Respaldo verificado de una sesión de validación (FIX03, DEF-31; RF-22 y F-034).
#
# Uso, desde backend/ y con PostgreSQL de Docker arriba:
#   RESPALDO_DIR=/Volumes/Respaldo/sabre sh scripts/respaldar_sesion.sh --evento <uuid>
#   sh scripts/respaldar_sesion.sh --verificar <carpeta de un respaldo>
#
# RESPALDO_DIR (en el entorno o en .env) es obligatoria y debe estar fuera del repo y de
# Docker (volúmenes, ~/.colima, ~/.docker): un respaldo dentro de lo que se respalda no sirve.
# No tiene valor por defecto.
#
# Escribe RESPALDO_DIR/R<NNN>-<fecha UTC>/ (NNN: número correlativo de respaldo, 3 dígitos) con:
#   sabre_<evento>_<fecha>.dump   pg_dump en formato custom de la base completa
#   sabre_<evento>_<fecha>.tgz    datos/storage (sin clips: EDGE02) y datos/evidencia (DATOS_DIR, por defecto ./datos)
#   MANIFEST.sha256               hash de cada archivo
# y después lo VERIFICA: hashes, lectura del .tgz, restauración del dump en una base temporal,
# mismos conteos (revisiones, clasificaciones, veredictos, auditoría) y fn_verificar_auditoria()
# sin filas. Si algo no cuadra la carpeta se renombra a *.FALLIDO y el script sale con error.
# Variables opcionales: ENV_FILE, PG_CONTAINER, POSTGRES_USER, POSTGRES_DB_NAME, DATOS_DIR.
set -eu

cd "$(dirname "$0")/.."
. scripts/lib_respaldo.sh

fallo() {
    echo "ERROR: $*" >&2
    exit 1
}

EVENTO=""
VERIFICAR=""
while [ $# -gt 0 ]; do
    case "$1" in
        --evento) EVENTO=${2:-}; shift 2 || fallo "--evento necesita un valor" ;;
        --verificar) VERIFICAR=${2:-}; shift 2 || fallo "--verificar necesita un valor" ;;
        *) fallo "argumento desconocido: $1 (uso: --evento <uuid> | --verificar <carpeta>)" ;;
    esac
done
[ -n "$EVENTO" ] || [ -n "$VERIFICAR" ] || fallo "falta --evento <uuid> (o --verificar <carpeta>)"

hash_cmd() {
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$@"; else sha256sum "$@"; fi
}

TMPDB=""
limpiar() {
    if [ -n "$TMPDB" ]; then
        psql_base postgres "DROP DATABASE IF EXISTS \"$TMPDB\" WITH (FORCE)" >/dev/null 2>&1 || true
    fi
}
trap limpiar EXIT

command -v docker >/dev/null 2>&1 || fallo "docker no está disponible"
buscar_contenedor || fallo "no encuentro el contenedor de PostgreSQL (levante el compose o defina PG_CONTAINER)"

# verificar_carpeta <carpeta> [conteos esperados] [evento]
verificar_carpeta() {
    carpeta=$1
    esperado=${2:-}
    evento=${3:-}
    # `set -e` no rige dentro de una función llamada con `||`: cada paso comprueba su resultado.
    dump=$(ls "$carpeta"/*.dump 2>/dev/null | head -n 1 || true)
    tgz=$(ls "$carpeta"/*.tgz 2>/dev/null | head -n 1 || true)
    [ -n "$dump" ] && [ -n "$tgz" ] || { echo "falta el .dump o el .tgz en $carpeta" >&2; return 1; }

    (cd "$carpeta" && hash_cmd -c MANIFEST.sha256 >/dev/null) \
        || { echo "los hashes de MANIFEST.sha256 no coinciden con los archivos" >&2; return 1; }
    echo "  hashes del MANIFEST: OK"
    tar -tzf "$tgz" >/dev/null 2>&1 || { echo "no se puede leer $tgz" >&2; return 1; }
    echo "  lectura del .tgz: OK"

    TMPDB="sabre_verif_$$_$(date +%s)"
    psql_base postgres "CREATE DATABASE \"$TMPDB\"" >/dev/null || return 1
    docker exec -i "$PG_CONT" pg_restore --exit-on-error -U "$PGUSR" -d "$TMPDB" < "$dump" \
        || { echo "pg_restore falló: el dump no es restaurable" >&2; return 1; }
    echo "  restauración en base temporal: OK"

    restaurado=$(psql_base "$TMPDB" "$SQL_CONTEOS") || return 1
    echo "  conteos restaurados (revisiones,clasificaciones,veredictos,auditoría): $restaurado"
    if [ -n "$esperado" ] && [ "$restaurado" != "$esperado" ]; then
        echo "los conteos no coinciden: base=$esperado restaurado=$restaurado" >&2
        return 1
    fi
    if [ -n "$evento" ]; then
        [ "$(psql_base "$TMPDB" "SELECT count(*) FROM sabre.evento WHERE id = '$evento'")" = "1" ] \
            || { echo "el evento $evento no está en la base restaurada" >&2; return 1; }
    fi
    filas=$(psql_base "$TMPDB" "SELECT count(*) FROM sabre.fn_verificar_auditoria()") || return 1
    echo "  fn_verificar_auditoria(): $filas filas alteradas"
    [ "$filas" = "0" ] || { echo "la cadena de auditoría restaurada tiene registros alterados" >&2; return 1; }
    limpiar
    TMPDB=""
}

if [ -n "$VERIFICAR" ]; then
    [ -d "$VERIFICAR" ] || fallo "no existe la carpeta $VERIFICAR"
    echo "Verificando $VERIFICAR"
    verificar_carpeta "$VERIFICAR" || fallo "el respaldo NO es válido"
    echo "Respaldo válido."
    exit 0
fi

# --- Respaldar ---------------------------------------------------------------
leer_respaldo_dir
[ -n "$RESPALDO_DIR" ] || fallo "RESPALDO_DIR no está definida. Apunte a una carpeta fuera de Docker y del repo (en el entorno o en $ENV_FILE)."
printf '%s' "$EVENTO" | grep -Eq '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' \
    || fallo "--evento debe ser un UUID"

mkdir -p "$RESPALDO_DIR" || fallo "no puedo crear RESPALDO_DIR=$RESPALDO_DIR"
DESTINO_BASE=$(cd "$RESPALDO_DIR" && pwd -P)
REPO=$(git rev-parse --show-toplevel 2>/dev/null || pwd -P)
for prohibido in "$REPO" "$(pwd -P)" "$HOME/.colima" "$HOME/.docker" "$HOME/Library/Containers/com.docker.docker" /var/lib/docker; do
    case "$DESTINO_BASE/" in
        "$prohibido"/*) fallo "RESPALDO_DIR ($DESTINO_BASE) está dentro de $prohibido; use una carpeta fuera del repo y de Docker." ;;
    esac
done

[ "$(psql_base "$PGBASE" "SELECT count(*) FROM sabre.evento WHERE id = '$EVENTO'")" = "1" ] \
    || fallo "el evento $EVENTO no existe en la base $PGBASE"

DATOS_DIR=${DATOS_DIR:-./datos}
[ -d "$DATOS_DIR/storage" ] && [ -d "$DATOS_DIR/evidencia" ] \
    || fallo "faltan $DATOS_DIR/storage o $DATOS_DIR/evidencia"
DATOS_DIR=$(cd "$DATOS_DIR" && pwd -P)

FECHA=$(date -u +%Y%m%dT%H%M%SZ)
NOMBRE="sabre_${EVENTO}_${FECHA}"
# Número correlativo: el mayor R<NNN>- existente (también los *.FALLIDO, para no reutilizarlo) + 1.
ULTIMO_N=0
for existente in "$DESTINO_BASE"/R[0-9][0-9][0-9]-*; do
    [ -e "$existente" ] || continue
    n=$(basename "$existente" | cut -c2-4 | sed 's/^0*//')
    n=${n:-0}
    if [ "$n" -gt "$ULTIMO_N" ]; then ULTIMO_N=$n; fi
done
CARPETA="$DESTINO_BASE/$(printf 'R%03d-%s' "$((ULTIMO_N + 1))" "$FECHA")"
mkdir "$CARPETA" || fallo "no puedo crear $CARPETA"
echo "Respaldando evento $EVENTO (base $PGBASE) en $CARPETA"

fallido() {
    mv "$CARPETA" "$CARPETA.FALLIDO" 2>/dev/null || true
    fallo "$1 (carpeta marcada como $CARPETA.FALLIDO; no es un respaldo válido)"
}

antes=$(psql_base "$PGBASE" "$SQL_CONTEOS")
REVISIONES=$(psql_base "$PGBASE" "$SQL_CONTEO_REVISIONES")
docker exec -i "$PG_CONT" pg_dump -Fc -U "$PGUSR" -d "$PGBASE" > "$CARPETA/$NOMBRE.dump" \
    || fallido "pg_dump falló"
despues=$(psql_base "$PGBASE" "$SQL_CONTEOS")
[ "$antes" = "$despues" ] || fallido "la base cambió durante el respaldo ($antes -> $despues); repita con Fog en reposo"
# EDGE02: los clips (datos personales) no se respaldan; la base conserva su sha256.
tar -czf "$CARPETA/$NOMBRE.tgz" --exclude="storage/clips" -C "$DATOS_DIR" storage evidencia || fallido "tar falló"
(cd "$CARPETA" && hash_cmd "$NOMBRE.dump" "$NOMBRE.tgz" > MANIFEST.sha256) || fallido "no pude escribir MANIFEST.sha256"

echo "Verificando el respaldo (restauración en base temporal)"
verificar_carpeta "$CARPETA" "$antes" "$EVENTO" || fallido "la verificación falló"

printf '%s revisiones=%s respaldo=%s\n' "$FECHA" "$REVISIONES" "$NOMBRE" > "$(archivo_ultimo)"
echo "Respaldo verificado: $CARPETA"
