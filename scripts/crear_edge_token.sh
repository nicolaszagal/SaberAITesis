#!/bin/sh
# Crea el token de servicio de Edge (EDGE02): `.secrets/edge_token.txt`, al azar, solo lectura del dueño.
# Fog (`fog_nativo.sh`) y Edge lo leen de ahí; Fog lo acepta solo desde 127.0.0.1 y solo en las rutas de
# tocados. No imprime el token. Con --rotar crea uno nuevo (hay que reiniciar Fog y Edge).
# También borra las credenciales del usuario maestro que Edge usaba antes (edge_fog_*.txt).
set -eu
cd "$(dirname "$0")/.."
S=${SECRETS_DIR:-.secrets}
mkdir -p "$S"
rm -f "$S/edge_fog_user.txt" "$S/edge_fog_password.txt"
if [ -s "$S/edge_token.txt" ] && [ "${1:-}" != "--rotar" ]; then
    echo "Ya existe $S/edge_token.txt (use --rotar para cambiarlo)."
    exit 0
fi
umask 077
openssl rand -hex 32 > "$S/edge_token.txt"
chmod 600 "$S/edge_token.txt"
echo "Token de servicio de Edge creado en $S/edge_token.txt"
