# Captura del clip del tocado (EDGE01)

Flujo: `LectorFavero` (flancos) → `CapturaTocados` (espera la ventana posterior y recorta el `BufferCircular`) → `datos/edge/tocados/tocado_*.mp4` + `.json`.

El JSON trae lo que hoy carga el operador a mano en `POST /matches/{id}/clip` (CONTRATO_API §4): `t_luz_a_ms` y `t_luz_b_ms` (enteros, relativos al primer frame del clip, `null` si la luz no se encendió), `luz_a`, `luz_b`; más `fuente`, `fps`, `n_frames`, `latencia_camara_ms`, `latencia_calibrada`, `camara`, `id`, `creado_utc`.

## Probar sin el aparato

```bash
cd backend && source .venv/bin/activate
python -m edge.favero.simulador --toques roja,verde,doble --cada 4      # imprime la ruta del pty
python -m edge.captura.servicio --puerto <ruta> --camara clip.mp4 --pacear --fuente simulado
```

## Con el aparato

```bash
python -m edge.calibrar_latencia --camara 0 --roi-roja x,y,w,h --roi-verde x,y,w,h   # una vez por cámara
python -m edge.captura.servicio --camara 0
```

## Parámetros (entorno)

`EDGE_VENTANA_PRE_MS` (2000), `EDGE_VENTANA_POST_MS` (500), `EDGE_FPS` (30), `EDGE_K_TOCADOS` (10), `EDGE_DIR_TOCADOS`, `EDGE_ARCHIVO_LATENCIA`. La ventana viene de EDGE02 y se moverá a `shared/config.py`. El buffer guarda `max(5 s, pre) + post` (RF-04): ~456 MB a 720p y 30 fps, porque los frames van sin comprimir hasta el recorte.

## Pendiente

Endpoint local de Edge y "Solicitar VAR" (flujo de EDGE02), RNF-09 visible en el frontend (el lector ya expone `estado()["senal"]` y avisa en el log), y el mapeo roja = A / verde = B por confirmar en la pista.

El permiso de cámara en macOS: Ajustes → Privacidad y seguridad → Cámara, para la terminal o Python.
