# Prototipo de conectividad por Tailscale (SEC02, 06/11/2026)

Evidencia para el registro del incidente (ISO/IEC 27001:2022 Anexo A 5.26 y 5.28, sin declarar cumplimiento).
Scripts: `scripts/prueba_tailnet.sh` y `scripts/prueba_revocacion_tailnet.sh`; política: `deploy/tailscale/politica.hujson`.

## Montaje
- Mac etiquetado `tag:mac` (`sabre-mac`), con Tailscale 1.104.4 (plan Personal, gratuito, uso no comercial).
- Dos contenedores **sin `/dev/net/tun` ni `NET_ADMIN`** (como Railway, que no los expone): `tailscaled --tun=userspace-networking`, clave efímera y etiquetada (`tag:cloud` y `tag:frontend`), reenviadores locales con `tailscale nc`.
- En el Mac, `tailscale serve --tcp` publica a la tailnet un Redis de prueba (puerto 6390, TLS 1.3 + mTLS, ACL real de `redis/generar_acl.sh`, Redis v=8.8.0) y un servidor HTTP (8001). Ambos escuchan solo en `127.0.0.1`.

## Resultados
| Prueba | Resultado |
|---|---|
| Redis por la tailnet (TLS + mTLS + usuario `cloud`) | `PONG`; handshake TLS completo ≈ 53 ms por conexión (50 repeticiones) |
| ACL de Redis por la tailnet | `cloud` escribe `cloud:verdicts:*`; `XADD fog:features` → `NOPERM` |
| 50 peticiones HTTP pequeñas | 7 a 14 ms cada una (dos corridas) |
| POST de 200 MB (el límite de clip) | 4 s; sha256 idéntico |
| `cloud` → `mac:6379` / `mac:8001` | permitido / **bloqueado por la ACL** |
| `frontend` → `mac:8001` / `mac:6379` | permitido / **bloqueado por la ACL** |
| `cloud` y `frontend` → `mac:22`, `mac:5432` | bloqueado (no distingue ACL de servicio ausente: `serve` no publica esos puertos) |
| Revocación: borrar el nodo `ts-prueba-cloud` en Machines (≈ 21:17 Lima = 02:17 UTC, hora anotada al minuto) | último acceso 02:18:13, primer corte 02:18:22 UTC: **entre 22 y 82 s** (límite pedido: 5 min) |

## Límites de la prueba
- El contenedor corrió en colima en el mismo Mac, no en Railway. Los tiempos de red son un mejor caso: desde Railway por internet la ruta puede pasar por un relevo (DERP) y la subida depende de la velocidad de subida del Mac. Se mide en el despliegue real (SEC02 Parte E).
- No se probó un clip real de Fog ni el flujo completo; el servidor HTTP era un sumidero.
- Revocar solo la **clave** no desautoriza nodos ya registrados (documentación de Tailscale); lo que corta es borrar el nodo o cambiar la política. Eso es lo que se midió.
- Las claves de la prueba caducan en 1 día y son efímeras; se pueden borrar en Settings → Keys.
