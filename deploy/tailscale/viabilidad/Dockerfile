# Parte 0 de DEPLOY09: prueba de viabilidad de Tailscale en Railway (un solo servicio, se borra al terminar).
# Reutiliza el entrypoint del prototipo de SEC02 y añade la sonda `sonda.sh`.
FROM tailscale/tailscale:stable
RUN apk add --no-cache socat curl
COPY prototipo/entrypoint.sh /entrypoint.sh
COPY viabilidad/sonda.sh /sonda.sh
ENV TS_HOSTNAME=sabre-viabilidad TS_FORWARDS="18001:sabre-mac:8001"
ENTRYPOINT ["sh", "/entrypoint.sh"]
CMD ["sh", "/sonda.sh"]
