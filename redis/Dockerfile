# Redis del despliegue remoto (DEPLOY07): solo puerto TLS 1.3 con autenticación
# mutua (mTLS) y ACL. Los secretos llegan como variables de entorno y el
# entrypoint los escribe en memoria (/dev/shm); no hay claves en la imagen.
FROM redis:7-alpine

COPY redis/redis.conf /etc/redis/redis.conf
COPY redis/docker-entrypoint.sh /usr/local/bin/sabre-redis-entrypoint.sh

# Usuario no root de la imagen base (redis); no hay volumen: los streams son
# transitorios (save "" y appendonly no).
USER redis
EXPOSE 6379
ENTRYPOINT ["sh", "/usr/local/bin/sabre-redis-entrypoint.sh"]
