#!/bin/sh
# Sonda de la Parte 0: imprime solo resultados (puertos, tiempos, memoria), nunca la clave.
# Se repite cada SONDA_INTERVALO s para poder leer los logs de Railway con calma.
SOCK=/tmp/tailscaled.sock
MAC=${MAC_HOST:-sabre-mac}

mem_mib() {
    # cgroup v2 si existe; si no, solo el RSS de tailscaled
    if [ -r /sys/fs/cgroup/memory.current ]; then
        echo "cgroup=$(( $(cat /sys/fs/cgroup/memory.current) / 1048576 ))MiB"
    fi
    echo "tailscaled_rss=$(awk '/VmRSS/ {print int($2/1024)}' /proc/$(pidof tailscaled | cut -d' ' -f1)/status)MiB"
}

puerto() {
    # $1 = puerto; alcanzable si `tailscale nc` conecta en 5 s
    if timeout 5 tailscale --socket="$SOCK" nc "$MAC" "$1" </dev/null >/dev/null 2>&1; then
        echo "mac:$1 ALCANZABLE"
    else
        echo "mac:$1 BLOQUEADO"
    fi
}

while true; do
    echo "== sonda $(date -u +%FT%TZ)"
    mem_mib
    echo "health: $(curl -s -m 10 -o /dev/null -w 'http=%{http_code}' http://127.0.0.1:18001/health)"
    tiempos=""
    for _ in $(seq 1 20); do
        t=$(curl -s -m 10 -o /dev/null -w '%{time_total}' http://127.0.0.1:18001/health)
        tiempos="$tiempos $t"
    done
    echo "latencia_s:$tiempos"
    for p in 6379 5432 22; do puerto "$p"; done
    sleep "${SONDA_INTERVALO:-300}"
done
