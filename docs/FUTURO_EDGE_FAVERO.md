# Trabajo futuro: Edge, Favero y captura automática (rama `future/edge-favero`)

**Estado:** fuera de alcance de la tesis por solicitud de cambio del 20/11/2026 (decisión del autor con los asesores). `main` llega hasta los trazos de pose y la justificación del veredicto (EXP01-04), más despliegue, seguridad e instalador. Esta rama conserva, tal cual estaba en `main` antes de SCOPE01 (`2723b3f`, FIX05), lo construido en HW01, EDGE01, EDGE02 y fix/EDGE02-decisiones.

## Qué contiene
- `edge/favero/` (puente Arduino, lector, simulador, diagnóstico), `edge/captura/` (buffer circular, recorte, cámara, envío a Fog, núcleo), `edge/api_local.py`, `edge/calibrar_latencia.py`, `edge/medir_buffer.py` y `docs/hardware/limite_resolucion_favero.md` (el límite de ~42 ms de la señal).
- Fog: `POST/GET /matches/{id}/tocados`, `POST /tocados/{id}/revision`, `POST /tocados/{id}/decision-pista`, `GET /tocados/{id}/clip`, la cola con prioridad (`servicio_tocados.py`), el proxy `/edge/*`, `EDGE_TOKEN` (`exigir_edge_o_jwt`), el combate activo explícito (`GET /matches/activo`) y la migración 0007 (`decision_pista`).
- Frontend (rama `future/edge-favero` del repo `SaberAISoftware`): "Últimos tocados", visor en bucle, botones de señal de prueba, sección Cámara y aviso "sin señal Favero".
- Decisiones D-20 a D-25, D-27 y D-28 en `docs_claude/contexto_sabre.md` (rama `future/edge-favero` del repo raíz).

## Cómo reintegrarla en el futuro
1. **Migraciones:** en `main` existe la `0008` (elimina `decision_pista`, solo si está vacía). Aquí la 0008 no existe. Al reintegrar, **renumerar la migración de la tabla después de la 0008 de `main`** (p. ej. `0009_decision_pista.py` con `down_revision = "0008"`, usando `CREATE TABLE IF NOT EXISTS`), y volver a agregar el bloque `decision_pista` a `sabre_ai_schema.sql` y a la copia `migrations/sql/0001_esquema_sabre.sql` (deben ser idénticas).
2. **Cierre de sesión:** en `main` es `POST /sesion/cerrar {match_id}` (el frontend envía el combate). Aquí usa el combate activo explícito y también purga `datos/edge/tocados/`. Al reintegrar, decidir si se vuelve al combate activo o se deja `match_id` y se agrega la purga de Edge.
3. **Purga por evento:** `main` mueve la consulta de URIs a `ClipRepositoryPort.uris_de_sesion`; aquí vive en `TocadosRepositoryPort.uris_clips`. Unificar en uno.
4. Volver a incluir `pyserial==3.5` en `edge/requirements.txt`, el token (`scripts/crear_edge_token.sh`) y las variables `EDGE_*`/`MODO_PRUEBA_SENAL`.
5. Pendiente que quedó abierto aquí: probar con el aparato real (20 toques por lado y 10 dobles), calibrar la latencia y decidir la redacción de RF-06 (≤ 1 trama Favero ≈ 42 ms, o refinar con el repetidor en cuadro).
