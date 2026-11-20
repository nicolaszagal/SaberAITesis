# SABRE.AI · repositorio del backend (SaberAITesis)

## Cómo reproducir SABRE.AI en 30 minutos

**Qué es.** Un sistema de video arbitraje asistido para esgrima (sable). Dado un clip de un tocado y el instante de cada luz, **sugiere** una de 6 clases tácticas (Ataque, Contraataque o Riposte, atribuida al tirador A·ROJ o B·VER) con un porcentaje de confianza, y muestra los trazos de pose y el razonamiento que la sostienen. **El árbitro conserva la decisión**: el sistema nunca asigna puntos ni cierra una revisión sin su veredicto. Tiene tres nodos: *Fog* (API, pose YOLOv8-pose, 192 features), *Cloud* (clasificador BiLSTM con atención) y el frontend web (repositorio `SaberAI-Frontend`).

**Qué hace falta.**

- Un Mac con Apple Silicon (verificado en macOS 27.0.1, arm64; Linux x86_64 **no** está verificado) con Homebrew, unos 4 GB libres y conexión a internet (descarga ≈ 1,5 GB).
- `brew install python@3.14 git colima docker docker-compose` y `colima start --cpu 2 --memory 4`. Python debe ser **3.14**.
- Un clip MP4/MOV de sable de ≥ 720p. **El repositorio no incluye clips** (derechos de imagen y política de datos): `[ORIGEN DE LOS CLIPS DE PRUEBA A DEFINIR POR EL AUTOR]`.
- Los hashes del modelo con el que se obtuvieron los resultados están en [`docs/manuales/GUIA_INSTALACION.md`](docs/manuales/GUIA_INSTALACION.md), sección 5. El enlace de un paquete de modelo para instalar sin internet es un hueco que completa el autor: `[ENLACE A COMPLETAR POR EL AUTOR]`.

**Tres comandos** (después de clonar los dos repositorios como carpetas hermanas `backend` y `SaberAISoftware`):

```bash
git clone https://github.com/nicolaszagal/SaberAITesis.git backend
git clone https://github.com/nicolaszagal/SaberAI-Frontend.git SaberAISoftware
cd backend

sh scripts/instalar_fog.sh instalar      # 1) entorno, modelo verificado, secretos propios y base (pide usuario y contraseña)
sh scripts/compose.sh -f docker-compose.yml -f docker-compose.nativo.yml up -d --build   # 2) Cloud, Redis, PostgreSQL y frontend en Docker
sh scripts/fog_nativo.sh                 # 3) Fog; en otra terminal, déjelo abierto
```

Luego abra `http://localhost:8081`, inicie sesión con el usuario y la contraseña que eligió, pulse **Combate → Crear combate**, y en **Revisión VAR** elija su clip, marque la luz (tecla R o V) y pulse **ANALIZAR**: en unos 15 s aparece la **sugerencia**. Es el modo A de [`docs/manuales/GUIA_EJECUCION.md`](docs/manuales/GUIA_EJECUCION.md).

**Tiempo medido, del clon a la primera sugerencia: unos 15 minutos** (≈ 902 s en un MacBook Air M4, red del autor: entorno Python 467 s, modelo y base 122 s, imágenes de Docker 293 s, arranque de Fog 5 s, análisis del primer clip 15 s). No incluye instalar Homebrew, Colima y Docker, ni escribir las respuestas del instalador. Detalle en `GUIA_EJECUCION.md`, A.7.

**Qué esperar.** La sugerencia puede ser equivocada: el F1 macro del modelo (0,4856 ± 0,0322, N = 10) **no alcanza** el umbral de aceptación de 0,65 (RNF-03). No es un error del software. Lea [`docs/manuales/LIMITACIONES.md`](docs/manuales/LIMITACIONES.md) para no confundir un límite con un defecto.

## Adónde ir después

| Documento | Para qué |
|---|---|
| [`docs/manuales/GUIA_INSTALACION.md`](docs/manuales/GUIA_INSTALACION.md) | Requisitos verificados, instalación, paquete de modelo con hashes SHA-256, secretos propios y verificación |
| [`docs/manuales/GUIA_EJECUCION.md`](docs/manuales/GUIA_EJECUCION.md) | Los tres modos (A local sin hardware, B con aparato Favero, C remoto), arrancar y detener, logs, respaldo, restauración, purga de clips, exportar evidencia, problemas |
| [`docs/manuales/MANUAL_USUARIO.md`](docs/manuales/MANUAL_USUARIO.md) | Uso de la interfaz, con capturas reales |
| [`docs/manuales/LIMITACIONES.md`](docs/manuales/LIMITACIONES.md) | Límites conocidos, con sus cifras y fuentes |
| [`docs/manuales/GUIA_DESARROLLO.md`](docs/manuales/GUIA_DESARROLLO.md) | Pruebas (`TEST_DATABASE_URL`, pytest-timeout, ruff, Playwright), arquitectura hexagonal, ramas y commits |
| [`CONTRATO_API.md`](CONTRATO_API.md) | Contrato de la API entre frontend, Fog y Cloud |
| [`docs/manuales/DESPLIEGUE_REMOTO.md`](docs/manuales/DESPLIEGUE_REMOTO.md) | Despliegue remoto (solo el autor) |
| [`docs/manuales/historico/`](docs/manuales/historico/) | Guías que ya no están vigentes (WebRTC, Render, Edge RTSP, Redis público), con la fecha hasta la que lo estuvieron |

## Estructura

- `fog/`, `cloud/`: los dos nodos (arquitectura hexagonal: `domain/`, `application/`, `ports/`, `infrastructure/` y `composition.py`).
- `shared/`: configuración y código común. `scripts/`: instalación, respaldo, evidencia y pruebas de humo. `tests/`: suite de pruebas.
- `dataset/lstm_6class/`: el checkpoint vigente, sus estadísticas y sus métricas (lo mínimo para ejecutar). El conjunto de datos y el entrenamiento no están en este repositorio.
- El nodo Edge y el lector del aparato Favero están en la rama `future/edge-favero`, fuera de `main`.
