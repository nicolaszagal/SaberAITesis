# Funciones comunes del respaldo (FIX03). Se incluye con `. scripts/lib_respaldo.sh`
# desde respaldar_sesion.sh y recordar_respaldo.sh; no se ejecuta solo.
#
# Variables: RESPALDO_DIR (obligatoria para respaldar), ENV_FILE (por defecto .env, de donde
# se lee RESPALDO_DIR si no está en el entorno), PG_CONTAINER (por defecto el servicio
# `postgres` de docker compose), POSTGRES_USER (sabre) y POSTGRES_DB_NAME (sabre).

. scripts/lib_compose.sh

ENV_FILE=${ENV_FILE:-.env}
PGUSR=${POSTGRES_USER:-sabre}
PGBASE=${POSTGRES_DB_NAME:-sabre}

# RESPALDO_DIR del entorno o, si falta, de la línea RESPALDO_DIR= de ENV_FILE.
leer_respaldo_dir() {
    if [ -z "${RESPALDO_DIR:-}" ] && [ -f "$ENV_FILE" ]; then
        RESPALDO_DIR=$(sed -n 's/^RESPALDO_DIR=//p' "$ENV_FILE" | tail -n 1 | sed "s/^[\"']//; s/[\"']\$//")
    fi
    RESPALDO_DIR=${RESPALDO_DIR:-}
}

# Contenedor de PostgreSQL, por orden: PG_CONTAINER; el que publica POSTGRES_HOST_PORT (5436 por
# defecto, el puerto al que se conecta Fog nativo; sirve sin el plugin `docker compose`, que
# colima no trae); y, al final, el servicio `postgres` del compose.
buscar_contenedor() {
    PG_CONT=${PG_CONTAINER:-}
    [ -n "$PG_CONT" ] || PG_CONT=$(docker ps -q --filter "publish=${POSTGRES_HOST_PORT:-5436}" 2>/dev/null | head -n 1 || true)
    [ -n "$PG_CONT" ] || PG_CONT=$(compose ps -q postgres 2>/dev/null | head -n 1 || true)
    [ -n "$PG_CONT" ]
}

# psql_base <base> <sentencia>: imprime el resultado sin formato.
psql_base() {
    docker exec -i "$PG_CONT" psql -X -q -t -A -v ON_ERROR_STOP=1 -U "$PGUSR" -d "$1" -c "$2"
}

SQL_CONTEO_REVISIONES="SELECT count(*) FROM sabre.revision_var"
# revisiones,clasificaciones,veredictos,auditoria
SQL_CONTEOS="SELECT (SELECT count(*) FROM sabre.revision_var) || ',' ||
    (SELECT count(*) FROM sabre.clasificacion) || ',' ||
    (SELECT count(*) FROM sabre.veredicto) || ',' ||
    (SELECT count(*) FROM sabre.registro_auditoria)"

# Dónde se anota cuántas revisiones tenía la base en el último respaldo verificado.
archivo_ultimo() {
    printf '%s/ULTIMO_%s.txt' "$RESPALDO_DIR" "$PGBASE"
}
