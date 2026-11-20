#!/bin/sh
# Emite el token de un nodo Fog para Cloud (DEPLOY11). POSIX sh.
#
# Uso: sh scripts/emitir_token_nodo.sh <nombre> [--forzar]
#
# - Genera 32 bytes al azar (base64 URL) y los escribe en un archivo con permisos 600 FUERA del repo
#   (por defecto ~/.sabre/tokens/<nombre>.token; carpeta TOKENS_DIR para otra). NO imprime el token.
# - Imprime solo la línea `nombre:hash` (SHA-256 del token) para pegarla en CLOUD_NODOS_SHA256 de Railway.
# - El autor entrega el ARCHIVO por un canal seguro; el revisor lo instala con
#   `sh scripts/instalar_fog.sh importar-token <archivo>`.
# - Revocar: quitar la entrada `nombre:hash` de CLOUD_NODOS_SHA256 y redesplegar Cloud.
# - No sobrescribe un token existente sin --forzar (reemplazarlo invalida el anterior al actualizar Railway).
set -eu
umask 077

NOMBRE=${1:-}
FORZAR=0
[ "${2:-}" != "--forzar" ] || FORZAR=1
[ -n "$NOMBRE" ] || { echo "Uso: sh scripts/emitir_token_nodo.sh <nombre> [--forzar]" >&2; exit 2; }
# LC_ALL=C: con otro idioma [a-z] admite mayúsculas y el nombre ya no coincidiría con el formato de Cloud.
printf '%s' "$NOMBRE" | LC_ALL=C grep -Eq '^[a-z0-9][a-z0-9_-]{0,31}$' \
    || { echo "Nombre inválido: minúsculas, dígitos, guion y guion bajo; 1 a 32 caracteres, sin empezar por guion." >&2; exit 2; }

DIR=${TOKENS_DIR:-$HOME/.sabre/tokens}
RAIZ_REPO=$(cd "$(dirname "$0")/.." && git rev-parse --show-toplevel 2>/dev/null || true)
mkdir -p "$DIR"
chmod 700 "$DIR"
DIR=$(cd "$DIR" && pwd -P)
if [ -n "$RAIZ_REPO" ]; then
    case "$DIR/" in
        "$RAIZ_REPO"/*) echo "TOKENS_DIR ($DIR) está dentro del repo; use una carpeta externa." >&2; exit 1 ;;
    esac
fi
ARCHIVO="$DIR/$NOMBRE.token"
if [ -e "$ARCHIVO" ] && [ "$FORZAR" = 0 ]; then
    echo "Ya existe un token para '$NOMBRE' ($ARCHIVO). Use --forzar para reemplazarlo (el anterior deja de valer al actualizar Railway)." >&2
    exit 1
fi

sha256_stdin() {
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 | cut -d' ' -f1
    elif command -v sha256sum >/dev/null 2>&1; then sha256sum | cut -d' ' -f1
    else openssl dgst -sha256 | sed 's/^.* //'; fi
}

command -v openssl >/dev/null 2>&1 || { echo "Falta openssl para generar el token." >&2; exit 1; }
TOKEN=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n')
[ "${#TOKEN}" -ge 40 ] || { echo "No se pudo generar el token." >&2; exit 1; }
TMP=$(mktemp "$DIR/.$NOMBRE.XXXXXX")
printf '%s\n' "$TOKEN" > "$TMP"
chmod 600 "$TMP"
mv "$TMP" "$ARCHIVO"
HASH=$(printf '%s' "$TOKEN" | sha256_stdin)
unset TOKEN

echo "Token de '$NOMBRE' escrito en $ARCHIVO (permisos 600). No se muestra." >&2
echo "Agregue esta línea a CLOUD_NODOS_SHA256 en Railway (entradas separadas por coma o salto de línea):" >&2
printf '%s:%s\n' "$NOMBRE" "$HASH"
