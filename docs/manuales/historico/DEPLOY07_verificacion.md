> **DOCUMENTO HISTÓRICO. Vigente hasta el 13/11/2026 (DEPLOY09 reemplazó el Redis público con TLS de DEPLOY07 por Tailscale).** Se conserva como registro de la verificación de DEPLOY07. Lo vigente está en [`../DESPLIEGUE_REMOTO.md`](../DESPLIEGUE_REMOTO.md).

# Verificación de DEPLOY07 (arquitectura anterior, solo histórico)
| # | Prueba | Resultado |
|---|---|---|
| 1 | `curl -I` al frontend | 200; `strict-transport-security`, `content-security-policy`, `x-content-type-options: nosniff`, `referrer-policy`, `permissions-policy`; `server: railway-hikari` (sin versión de nginx) |
| 2 | App sin login | **Pendiente de confirmación visual** (el build exige token; no se probó con navegador) |
| 3 | `/api/eventos` y `/api/revisiones` sin token | 401 (`/api/health` es público por diseño) |
| 4 | 6 logins fallidos con `X-Forwarded-For` falsificado distinto en cada intento | 401 ×5 y 429 al sexto; el bloqueo es por la IP real |
| 5 | Túnel `/health` sin `X-Proxy-Token` | 403 |
| 6 | Preflight CORS desde `https://ejemplo.com` | 400 sin `Access-Control-Allow-Origin` |
| 7 | `redis-cli` al TCP proxy (`<host-del-proxy-TCP-de-Railway>`) | sin TLS: conexión cerrada; TLS sin certificado de cliente: error de E/S; certificado sin contraseña: `NOAUTH`; `sabre` con `FLUSHALL`: `NOPERM`. TLS 1.3 de extremo a extremo con verificación del certificado propio: el proxy no termina TLS |
| 8 | Cloud sin dominio público | `railway domain list --service cloud`: sin dominios |
| 9 | Flujo completo con 2 clips | Por el frontend público: login, configuración y clip → sugerencia (AttackA_0007: AttackB 0.53; RiposteB_0004: RiposteB 0.44). Desde datos móviles: **pendiente** (lo hace el autor) |
| 10 | `fn_verificar_auditoria()` en `sabre_expo` | 0 filas (2 revisiones) |
| 11 | Logs de Fog | `auth.login_ok` / `auth.login_fallo` con IP real y usuario; 0 apariciones de contraseñas, tokens o hashes |
| 12 | `fog_remoto.sh stop` | la URL del túnel responde 530 |
| 13 | Latencia de 2 clips (cliente → frontend → túnel → Fog → Redis → Cloud → respuesta) | 6.0 s y 7.9 s (límite D-08: 60 s) |

Imagen del frontend: 93.6 MB; `/usr/share/nginx/html` solo contiene el build (`_expo`, `index.html`…), sin `node_modules`.

