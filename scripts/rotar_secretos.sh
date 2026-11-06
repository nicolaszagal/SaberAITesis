#!/bin/sh
# Rotación completa de secretos (SEC01). Idempotente y sin imprimir valores.
#
# Uso, desde backend/:
#   sh scripts/rotar_secretos.sh            # rota lo que falte; si ya se rotó, no hace nada
#   sh scripts/rotar_secretos.sh --forzar   # vuelve a rotar todo menos el hash de la contraseña
#                                           # maestra (lo vigente pasa a _retirado)
#
# Qué hace:
#   1. Mueve lo vigente a .secrets/_retirado_2026-10-27/ (no borra evidencia).
#   2. Genera, solo si falta: AUTH_PASSWORD_HASH (pide la contraseña por getpass),
#      AUTH_JWT_SECRET, PROXY_SHARED_TOKEN, POSTGRES_PASSWORD y la PKI de Redis
#      completa (CA, servidor, fog, cloud y contraseña del usuario `sabre`).
#   3. Actualiza POSTGRES_PASSWORD en .env y regenera .secrets/fog_remoto.env.
#   4. Imprime solo nombre, longitud y huella (sha256 truncado a 8 caracteres).
#
# Variables opcionales: SECRETS_DIR (.secrets), ENV_FILE (.env), PYTHON (.venv/bin/python),
# REDIS_SAN_HOSTS (nombres del certificado de servidor; por defecto
# "redis.railway.internal localhost") y REDIS_HOST_REMOTO (host:puerto del Redis para
# Fog; por defecto PENDIENTE:6379 hasta que exista el despliegue nuevo).
set -eu

cd "$(dirname "$0")/.."
BACKEND=$(pwd)
SECRETS_DIR=${SECRETS_DIR:-.secrets}
ENV_FILE=${ENV_FILE:-.env}
PY=${PYTHON:-.venv/bin/python}
SAN_HOSTS=${REDIS_SAN_HOSTS:-"redis.railway.internal localhost"}
REDIS_HOST_REMOTO=${REDIS_HOST_REMOTO:-PENDIENTE:6379}
export SECRETS_DIR

FORZAR=0
[ "${1:-}" != "--forzar" ] || FORZAR=1

umask 077
mkdir -p "$SECRETS_DIR"
SECRETS_DIR=$(cd "$SECRETS_DIR" && pwd)
export SECRETS_DIR
RETIRADO="$SECRETS_DIR/_retirado_2026-10-27"
MARCA_FIN="$SECRETS_DIR/.rotacion_SEC01"
MARCA_RETIRO="$SECRETS_DIR/.retiro_SEC01"

if [ "$FORZAR" -eq 0 ] && [ -f "$MARCA_FIN" ]; then
    echo "Ya rotado (marca $MARCA_FIN). Use --forzar para rotar de nuevo."
    exit 0
fi
if [ "$FORZAR" -eq 1 ]; then
    RETIRADO="$RETIRADO/forzado_$(date +%s)"
    rm -f "$MARCA_FIN" "$MARCA_RETIRO"
fi

huella() { # archivo -> sha256 truncado a 8 caracteres del contenido
    shasum -a 256 "$1" | cut -c1-8
}
informar() { # nombre archivo
    printf '%-24s longitud=%-6s huella=%s\n' "$1" "$(tr -d '\n' < "$2" | wc -c | tr -d ' ')" "$(huella "$2")"
}
mover() { # origen destino
    [ -e "$1" ] || return 0
    mkdir -p "$(dirname "$2")"
    mv "$1" "$2"
}
generar_token() { # archivo
    [ -s "$1" ] && return 0
    "$PY" -c 'import secrets; print(secrets.token_urlsafe(48), end="")' > "$1"
    chmod 600 "$1"
}
valor_previo() { # NOMBRE -> valor no secreto copiado del fog_remoto.env retirado
    sed -n "s/^$1=//p" "$RETIRADO/fog_remoto.env" | head -n 1
}

# 1. Retiro de lo vigente (una sola vez; la marca evita retirar lo nuevo si se repite)
if [ ! -f "$MARCA_RETIRO" ]; then
    mkdir -p "$RETIRADO"
    chmod 700 "$RETIRADO"
    mover "$SECRETS_DIR/redis" "$RETIRADO/redis"
    for f in auth_maestro.txt clave_prueba.txt proxy_token.txt fog_remoto.env; do
        mover "$SECRETS_DIR/$f" "$RETIRADO/$f"
    done
    if [ "$FORZAR" -eq 1 ]; then
        # El hash de la contraseña maestra se conserva: cambiarla exige terminal.
        # Para cambiarla, borre auth_password_hash.env antes de --forzar.
        mover "$SECRETS_DIR/auth_jwt_secret.txt" "$RETIRADO/auth_jwt_secret.txt"
        mover "$SECRETS_DIR/postgres_password.txt" "$RETIRADO/postgres_password.txt"
    fi
    [ ! -f "$ENV_FILE" ] || cp "$ENV_FILE" "$RETIRADO/env.previo"
    touch "$MARCA_RETIRO"
fi

# 2. Generación (solo lo que falta)
HASH_FILE="$SECRETS_DIR/auth_password_hash.env"
if [ ! -s "$HASH_FILE" ]; then
    [ -t 0 ] || { echo "Falta $HASH_FILE y no hay terminal para pedir la contraseña." >&2; exit 1; }
    "$PY" scripts/crear_hash_password.py --env > "$HASH_FILE" || { rm -f "$HASH_FILE"; exit 1; }
    chmod 600 "$HASH_FILE"
fi
generar_token "$SECRETS_DIR/auth_jwt_secret.txt"
generar_token "$SECRETS_DIR/proxy_token.txt"
if [ ! -s "$SECRETS_DIR/postgres_password.txt" ]; then
    # Solo letras y números: se inserta en una URL (ver .env.example).
    "$PY" -c 'import secrets, string; a = string.ascii_letters + string.digits; print("".join(secrets.choice(a) for _ in range(32)), end="")' \
        > "$SECRETS_DIR/postgres_password.txt"
    chmod 600 "$SECRETS_DIR/postgres_password.txt"
fi
if [ ! -e "$SECRETS_DIR/redis/ca.crt" ]; then
    # shellcheck disable=SC2086
    sh scripts/generar_pki_redis.sh $SAN_HOSTS
fi

# 3. .env (POSTGRES_PASSWORD) y fog_remoto.env
PG=$(cat "$SECRETS_DIR/postgres_password.txt")
if [ -f "$ENV_FILE" ] && grep -q '^POSTGRES_PASSWORD=' "$ENV_FILE"; then
    sed -i.bak "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$PG/" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
else
    printf 'POSTGRES_PASSWORD=%s\n' "$PG" >> "$ENV_FILE"
fi

if [ ! -s "$SECRETS_DIR/fog_remoto.env" ]; then
    [ -f "$RETIRADO/fog_remoto.env" ] || { echo "Falta $RETIRADO/fog_remoto.env para copiar los valores no secretos." >&2; exit 1; }
    for v in ENTORNO AUTH_USER CORS_ORIGINS FOG_HOST_PORT PROXY_SALTOS_CONFIANZA POSTGRES_DB_NAME; do
        grep -q "^$v=" "$RETIRADO/fog_remoto.env" || { echo "Falta $v en el fog_remoto.env anterior." >&2; exit 1; }
    done
    {
        echo "ENTORNO=$(valor_previo ENTORNO)"
        echo "AUTH_USER=$(valor_previo AUTH_USER)"
        cat "$HASH_FILE"
        echo "AUTH_JWT_SECRET=$(cat "$SECRETS_DIR/auth_jwt_secret.txt")"
        echo "PROXY_SHARED_TOKEN=$(cat "$SECRETS_DIR/proxy_token.txt")"
        echo "CORS_ORIGINS=$(valor_previo CORS_ORIGINS)"
        echo "REDIS_URL_REMOTO=rediss://sabre:$(cat "$SECRETS_DIR/redis/redis_password.txt")@$REDIS_HOST_REMOTO/0"
        echo "REDIS_TLS_CA=$SECRETS_DIR/redis/ca.crt"
        echo "REDIS_TLS_CERT=$SECRETS_DIR/redis/fog.crt"
        echo "REDIS_TLS_KEY=$SECRETS_DIR/redis/fog.key"
        echo "POSTGRES_PASSWORD=$PG"
        echo "FOG_HOST_PORT=$(valor_previo FOG_HOST_PORT)"
        echo "PROXY_SALTOS_CONFIANZA=$(valor_previo PROXY_SALTOS_CONFIANZA)"
        echo "POSTGRES_DB_NAME=$(valor_previo POSTGRES_DB_NAME)"
    } > "$SECRETS_DIR/fog_remoto.env"
    chmod 600 "$SECRETS_DIR/fog_remoto.env"
fi
chmod 600 "$SECRETS_DIR"/*.txt "$SECRETS_DIR"/*.env "$SECRETS_DIR"/redis/* 2>/dev/null || true

# 4. Informe: nombres, longitudes y huellas
echo "Secretos vigentes (huella = sha256 truncado a 8 caracteres):"
informar AUTH_PASSWORD_HASH "$HASH_FILE"
informar AUTH_JWT_SECRET "$SECRETS_DIR/auth_jwt_secret.txt"
informar PROXY_SHARED_TOKEN "$SECRETS_DIR/proxy_token.txt"
informar POSTGRES_PASSWORD "$SECRETS_DIR/postgres_password.txt"
informar REDIS_PASSWORD "$SECRETS_DIR/redis/redis_password.txt"
for f in ca server fog cloud; do
    informar "PKI_$f.crt" "$SECRETS_DIR/redis/$f.crt"
done
echo "Retirado en: $RETIRADO"
touch "$MARCA_FIN"
