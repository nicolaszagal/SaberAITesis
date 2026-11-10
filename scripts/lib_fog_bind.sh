# Dirección en la que escucha Fog (SEC02). Se carga con `. scripts/lib_fog_bind.sh`.
#
# En modo remoto (ENTORNO=remoto) Fog escucha solo en 127.0.0.1: a él se llega por `tailscale serve`
# (que reenvía a loopback), nunca por la red local. En el modo piloto local sigue en 0.0.0.0 porque
# el frontend en Docker lo alcanza por host.docker.internal. FOG_BIND_HOST cambia el valor en local;
# en remoto solo se admite una dirección de loopback.

fog_bind_host() {
    if [ "${ENTORNO:-}" = "remoto" ]; then
        case "${FOG_BIND_HOST:-127.0.0.1}" in
            127.*|localhost|::1) printf '%s\n' "${FOG_BIND_HOST:-127.0.0.1}" ;;
            *)
                echo "En modo remoto Fog solo puede escuchar en loopback (FOG_BIND_HOST=${FOG_BIND_HOST})." >&2
                return 1 ;;
        esac
    else
        printf '%s\n' "${FOG_BIND_HOST:-0.0.0.0}"
    fi
}
