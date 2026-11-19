# Invocación única de Docker Compose (DEPLOY10). Se incluye con `. scripts/lib_compose.sh`; no se ejecuta solo.
#
# Hay dos formas según el equipo: el plugin `docker compose` (Docker Engine, Docker Desktop) y el binario
# suelto `docker-compose` (el Colima del Mac no trae el plugin). Ningún script debe escribir
# `docker compose` a mano: todos llaman a `compose <argumentos>`.

# detectar_compose: fija COMPOSE_CMD ("docker compose" o "docker-compose"). Falla si no hay ninguno.
detectar_compose() {
    [ -z "${COMPOSE_CMD:-}" ] || return 0
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        COMPOSE_CMD="docker-compose"
    else
        return 1
    fi
}

# compose <argumentos>: ejecuta Compose con la forma disponible.
compose() {
    detectar_compose || {
        echo "No hay Docker Compose (ni 'docker compose' ni 'docker-compose'). Ver 'sh scripts/instalar_fog.sh verificar'." >&2
        return 127
    }
    # COMPOSE_CMD lleva a propósito dos palabras en el caso del plugin.
    # shellcheck disable=SC2086
    $COMPOSE_CMD "$@"
}
