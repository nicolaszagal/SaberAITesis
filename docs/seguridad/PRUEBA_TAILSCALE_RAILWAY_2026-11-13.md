# Parte 0 de DEPLOY09: viabilidad de Tailscale en Railway (13/11/2026)

Evidencia para el registro del incidente (ISO/IEC 27001:2022 Anexo A 5.26 y 5.28, sin declarar cumplimiento).
Sonda: `deploy/tailscale/viabilidad/`. Un solo servicio en un proyecto de prueba del plan Free, con clave de Tailscale efímera, etiquetada `tag:frontend`, preaprobada y de 7 días, cargada como variable *sealed*. La clave nunca se imprimió.

## Resultados (contenedor en Railway, Fog en el Mac por la tailnet)
| Prueba | Resultado |
|---|---|
| Unirse a la tailnet en modo userspace (sin `/dev/net/tun`) | Correcto: nodo `sabre-viabilidad` |
| `/health` de Fog en `mac:8001` | Alcanzable: `http=403` (sin `X-Proxy-Token`; la sonda no lo lleva a propósito) |
| `mac:6379` desde `tag:frontend` | Bloqueado |
| `mac:5432` desde `tag:frontend` | Bloqueado |
| `mac:22` desde `tag:frontend` | Bloqueado |
| Memoria del contenedor (cgroup) | 22 MiB |
| RSS de `tailscaled` | 39 MiB (RAM extra que agrega Tailscale) |
| Latencia de `/health`, 20 peticiones, cada una con conexión nueva | mín 0,293 s, mediana 0,365 s, máx 0,381 s |

## Límites
- No hay medición del quick tunnel en las mismas condiciones, así que la comparación pedida no se hizo. No se inventa una cifra.
- Cada petición abre una conexión nueva por `tailscale nc`; la latencia incluye ese establecimiento y probablemente un relevo (DERP). No se verificó la ruta.
- `mac:5432` y `mac:22` bloqueados no distinguen la política de que `tailscale serve` no los publica. El bloqueo de `mac:6379` sí es por política: ahí `serve` publica Redis para `tag:cloud`.
- Una sola corrida y un solo contenedor.
