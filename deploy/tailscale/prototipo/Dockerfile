# Prototipo SEC02: simula un contenedor de Railway (sin /dev/net/tun ni NET_ADMIN).
# tailscaled en modo userspace + reenviadores locales que atraviesan la tailnet con `tailscale nc`.
FROM tailscale/tailscale:stable
RUN apk add --no-cache socat redis curl coreutils
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["sh", "/entrypoint.sh"]
