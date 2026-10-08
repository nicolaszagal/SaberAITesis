# Prueba remota del árbitro (DEPLOY03)

Permite que el árbitro use la Validación 1 desde su navegador mientras Fog, Cloud, PostgreSQL y Redis corren en el Mac del autor (modo piloto). No se despliega nada en la nube. Instrucciones para el árbitro: `INSTRUCCIONES_ARBITRO_REMOTO.md`.

## 1. Requisitos

- Stack del modo piloto arriba (`GUIA_INSTALACION.md`): `docker compose -f docker-compose.yml -f docker-compose.nativo.yml up -d` y `sh scripts/fog_nativo.sh`. Compruebe `curl localhost:8001/health` (fog, redis y postgres "ok").
- `brew install cloudflared` (sin cuenta; túnel rápido).
- Build del frontend con la API bajo `/api`: `cd SaberAISoftware && npm run build:remoto` (genera `dist-remoto/`, fuera de git). El modo local no cambia: sin esa variable el frontend usa `http://localhost:8001`.

## 2. Evento propio

Los datos de la prueba quedan separados en un evento:

```bash
cd backend && set -a; source fog/.env; set +a
.venv/bin/python scripts/crear_sesion_validacion.py \
    --evento "Prueba remota árbitro" --fecha 2026-10-05 \
    --arbitro "<Nombre del árbitro>" --operador "<Nombre del operador>"
```

Anote el `evento_id`. El árbitro debe elegir ese evento en "Configurar combate".

## 3. Usuario y contraseña

El proxy exige autenticación básica en todas las rutas. El archivo vive en `.secrets/` (fuera de git):

```bash
cd backend && htpasswd -B -c .secrets/htpasswd arbitro   # pide la contraseña; use una larga y única
```

Entregue usuario y contraseña al árbitro por un canal distinto al del enlace.

## 4. Ventana de disponibilidad

```bash
cd backend
caffeinate -dimsu &                 # evita la suspensión mientras dura la ventana
sh scripts/prueba_remota.sh start   # imprime https://*.trycloudflare.com y la guarda en datos/prueba_remota_url.txt
```

Envíe al árbitro la URL y la hora de inicio y fin. La URL cambia en cada `start`. Al terminar la ventana:

```bash
sh scripts/prueba_remota.sh stop    # cierra túnel y proxy; la URL deja de responder
kill %1                             # o: pkill caffeinate
```

## 5. Evidencia al final

```bash
set -a; source fog/.env; set +a
.venv/bin/python scripts/exportar_evidencia.py --evento <evento_id>   # escribe en EVIDENCE_DIR/<evento_id>/
docker exec sabre-postgres-1 psql -U sabre -d sabre -c "SELECT * FROM fn_verificar_auditoria();"   # debe devolver 0 filas
```

Los clips quedan en `datos/storage`.

## 6. Riesgos

- La URL es pública mientras el túnel esté abierto; la única barrera es la contraseña básica. La aplicación no tiene autenticación y el CORS de Fog está abierto (DEF-23): no deje el túnel fuera de la ventana.
- Si el Mac se suspende o pierde red, el árbitro pierde el acceso. Use `caffeinate` y conexión estable.
- Los clips del árbitro se guardan en este Mac; trátelos según el consentimiento informado (RNF-16).
- La vista previa de cámaras (WebSocket, Validación 2) no está disponible por el túnel y no se usa en la Validación 1.
