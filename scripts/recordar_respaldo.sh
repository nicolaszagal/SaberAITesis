#!/bin/sh
# Avisa si la base tiene revisiones nuevas desde el último respaldo verificado (FIX03).
# La llaman fog_nativo.sh (al arrancar) y fog_remoto.sh stop. No falla nunca: solo avisa.
#
# Variables: las de lib_respaldo.sh (RESPALDO_DIR, PG_CONTAINER, POSTGRES_DB_NAME...).
# Con la base del despliegue remoto, defina POSTGRES_DB_NAME=sabre_expo.
cd "$(dirname "$0")/.." || exit 0
. scripts/lib_respaldo.sh

aviso() {
    echo "" >&2
    echo "################################################################" >&2
    for linea in "$@"; do echo "#  $linea" >&2; done
    echo "################################################################" >&2
    echo "" >&2
}

leer_respaldo_dir
if [ -z "$RESPALDO_DIR" ]; then
    aviso "SIN RESPALDO: RESPALDO_DIR no está definida." \
          "La base '$PGBASE' vive en un volumen de Docker y puede perderse (DEF-31)." \
          "Defina RESPALDO_DIR (fuera de Docker y del repo) y corra:" \
          "  sh scripts/respaldar_sesion.sh --evento <uuid>"
    exit 0
fi

command -v docker >/dev/null 2>&1 && buscar_contenedor || {
    echo "Respaldo: no pude consultar PostgreSQL; no sé si hay revisiones sin respaldar." >&2
    exit 0
}
actuales=$(psql_base "$PGBASE" "$SQL_CONTEO_REVISIONES" 2>/dev/null) || {
    echo "Respaldo: no pude contar las revisiones de '$PGBASE'." >&2
    exit 0
}
respaldadas=0
[ -f "$(archivo_ultimo)" ] && respaldadas=$(sed -n 's/.*revisiones=\([0-9]*\).*/\1/p' "$(archivo_ultimo)" | head -n 1)
respaldadas=${respaldadas:-0}

if [ "$actuales" -gt "$respaldadas" ]; then
    aviso "FALTA RESPALDAR: $((actuales - respaldadas)) revisiones nuevas en '$PGBASE' desde el último respaldo ($respaldadas -> $actuales)." \
          "Corra: sh scripts/respaldar_sesion.sh --evento <uuid del evento>"
else
    echo "Respaldo al día ($actuales revisiones en '$PGBASE')."
fi
exit 0
