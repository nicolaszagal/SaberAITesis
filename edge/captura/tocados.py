"""Del flanco Favero al clip del tocado (EDGE01, CU-04).

`CapturaTocados` recibe los flancos del lector, espera la ventana posterior, recorta el buffer
circular y escribe `tocado_*.mp4` + `tocado_*.json` con los instantes de luz relativos al primer
frame del clip. Es lo que hoy carga el operador a mano en `POST /matches/{id}/clip`
(CONTRATO_API §4): `t_luz_a_ms` y `t_luz_b_ms` enteros entre 0 y la duración del clip.

Corrección de latencia (RF-06): una luz vista por el serie en el instante S aparece en el video
en el frame de instante `S + desfase`. El desfase sale de `edge/calibrar_latencia.py`; sin
calibración vale 0 y el JSON lo dice (`latencia_calibrada: false`).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edge.captura.buffer import BufferCircular
from edge.captura.clip import ErrorClip, escribir_mp4, remuestrear
from edge.captura.config import ConfigCaptura
from edge.favero.lector import Flanco

logger = logging.getLogger(__name__)


def cargar_desfase_ms(archivo: Path, camara_id: str) -> float | None:
    """Lee el desfase calibrado de una cámara.

    Args:
        archivo: JSON escrito por `calibrar_latencia.py`.
        camara_id: identificador de la cámara.

    Returns:
        El desfase medio en ms, o `None` si no hay calibración para esa cámara.
    """
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        return float(datos[camara_id]["desfase_ms"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


@dataclass
class _Grupo:
    """Luces de un mismo tocado: la primera abre la ventana y las demás entran si caen dentro."""

    t_primero_ns: int
    luces: dict[str, int] = field(default_factory=dict)  # lado ("A"/"B") -> instante del flanco
    fuente: str | None = None  # 'simulado' gana si alguna luz del tocado no vino del aparato
    origen: str | None = None


@dataclass(frozen=True)
class TocadoCapturado:
    """Resultado de un recorte.

    Attributes:
        id: nombre base de los archivos (sin extensión).
        ruta_video: MP4 escrito.
        ruta_json: JSON con los instantes.
        metadatos: contenido del JSON.
    """

    id: str
    ruta_video: Path
    ruta_json: Path
    metadatos: dict[str, Any]


class CapturaTocados:
    """Agrupa flancos en tocados y recorta el clip de cada uno."""

    def __init__(
        self,
        buffer: BufferCircular,
        config: ConfigCaptura,
        *,
        camara_id: str = "frontal",
        fuente: str = "favero",
        desfase_ms: float | None = None,
        reloj_ns: Callable[[], int] = time.monotonic_ns,
        al_tocado: Callable[[TocadoCapturado], None] | None = None,
        enviar: bool = False,
    ) -> None:
        """Crea el coordinador (no corre hasta `iniciar`, o se maneja a mano con `procesar`).

        Args:
            buffer: buffer circular que alimenta la cámara.
            config: ventana, fps, K y carpetas.
            camara_id: nombre de la cámara (clave de la calibración).
            fuente: origen de la señal para el JSON (`favero` o `simulado`).
            desfase_ms: desfase cámara-serie; `None` = sin calibrar (0 y se avisa en el JSON).
            reloj_ns: reloj monótono, el mismo de los frames y los flancos.
            al_tocado: se llama al terminar de escribir cada tocado.
            enviar: si el tocado queda `"envio": "pendiente"` para subirlo a Fog (EDGE02).
        """
        self._enviar = enviar
        self._buffer = buffer
        self._config = config
        self._camara_id = camara_id
        self._fuente = fuente
        self._calibrado = desfase_ms is not None
        self._desfase_ns = int((desfase_ms or 0.0) * 1e6)
        self._reloj_ns = reloj_ns
        self._al_tocado = al_tocado
        self._lock = threading.Lock()
        self._grupo: _Grupo | None = None
        self._vencidos: list[_Grupo] = []  # cerrados por un flanco posterior, aún sin escribir
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._contador = 0
        self.tocados_escritos = 0
        self.errores = 0

    # ---- entrada de flancos

    def registrar_flanco(self, flanco: Flanco) -> None:
        """Agrega un flanco (se puede llamar desde el hilo del lector).

        Si cae dentro de la ventana posterior del tocado abierto, es su segunda luz; si no, y
        el anterior ya venció, el anterior se cierra y este abre uno nuevo.

        Args:
            flanco: flanco de subida del lector.
        """
        post_ns = self._config.post_ms * 1_000_000
        with self._lock:
            grupo = self._grupo
            if grupo is not None and flanco.t_ns > grupo.t_primero_ns + post_ns:
                # El procesamiento no alcanzó a cerrarlo: se cierra aparte, sin mezclar.
                pendiente, self._grupo = grupo, None
                self._vencidos.append(pendiente)
                grupo = None
            if grupo is None:
                grupo = self._grupo = _Grupo(flanco.t_ns)
            if flanco.fuente == "simulado" or grupo.fuente is None:
                grupo.fuente = flanco.fuente or grupo.fuente
            grupo.origen = grupo.origen or flanco.origen
            if flanco.lado in grupo.luces:
                logger.warning("[Captura] Luz %s repetida dentro del mismo tocado; se ignora", flanco.lado)
                return
            grupo.luces[flanco.lado] = flanco.t_ns

    # ---- ciclo

    def iniciar(self) -> None:
        """Arranca el hilo que cierra los tocados cuando vence su ventana posterior."""
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="captura-tocados", daemon=True)
        self._hilo.start()

    def detener(self, timeout_s: float = 5.0) -> None:
        """Detiene el hilo (no cierra el tocado que esté esperando su ventana)."""
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout_s)

    def _bucle(self) -> None:
        while not self._parar.wait(0.005):
            self.procesar()

    def procesar(self) -> list[TocadoCapturado]:
        """Escribe los tocados cuya ventana posterior ya venció.

        Returns:
            Los tocados escritos en esta llamada (los que fallen se cuentan en `errores`).
        """
        listos: list[_Grupo] = []
        with self._lock:
            listos.extend(self._vencidos)
            self._vencidos.clear()
            grupo = self._grupo
            if grupo is not None:
                t_cam = grupo.t_primero_ns + self._desfase_ns
                if self._reloj_ns() >= t_cam + self._config.post_ms * 1_000_000:
                    listos.append(grupo)
                    self._grupo = None
        resultados = []
        for grupo in listos:
            try:
                resultados.append(self._escribir(grupo))
            except ErrorClip as error:
                self.errores += 1
                logger.error("[Captura] No se pudo escribir el tocado: %s", error)
            except Exception:  # noqa: BLE001 - un fallo de disco no debe matar el hilo
                self.errores += 1
                logger.exception("[Captura] Fallo inesperado al escribir el tocado")
        for res in resultados:
            if self._al_tocado is not None:
                try:
                    self._al_tocado(res)
                except Exception:  # noqa: BLE001
                    logger.exception("[Captura] Falló al_tocado")
        return resultados

    # ---- recorte

    def _escribir(self, grupo: _Grupo) -> TocadoCapturado:
        cfg = self._config
        t_cam_ns = grupo.t_primero_ns + self._desfase_ns
        desde = t_cam_ns - cfg.pre_ms * 1_000_000
        hasta = t_cam_ns + cfg.post_ms * 1_000_000
        frames = self._buffer.extraer(desde, hasta)
        clip = remuestrear(frames, cfg.fps, hasta)
        if clip.repetidos:
            logger.warning(
                "[Captura] %d frame(s) repetido(s) en el clip: la cámara entregó menos de %d fps",
                clip.repetidos,
                cfg.fps,
            )
        if frames[0].t_ns - desde > 1e9 / cfg.fps:
            logger.warning(
                "[Captura] El buffer no cubre toda la ventana previa (faltan %.0f ms)", (frames[0].t_ns - desde) / 1e6
            )
        duracion_ms = round(len(clip.imagenes) / cfg.fps * 1000)
        instantes: dict[str, int | None] = {"A": None, "B": None}
        for lado, s_ns in grupo.luces.items():
            bruto = round((s_ns + self._desfase_ns - clip.t0_ns) / 1e6)
            instantes[lado] = min(max(bruto, 0), duracion_ms)
            if instantes[lado] != bruto:
                logger.warning(
                    "[Captura] Instante de luz %s fuera del clip (%d ms de %d); se ajusta", lado, bruto, duracion_ms
                )

        self._contador += 1
        ahora = datetime.now(timezone.utc)
        id_tocado = f"tocado_{ahora:%Y%m%dT%H%M%S}_{ahora.microsecond // 1000:03d}_{self._contador:04d}"
        metadatos = {
            "id": id_tocado,
            "t_luz_a_ms": instantes["A"],
            "t_luz_b_ms": instantes["B"],
            "luz_a": instantes["A"] is not None,
            "luz_b": instantes["B"] is not None,
            "fuente": grupo.fuente or self._fuente,
            "origen": grupo.origen,
            "fps": cfg.fps,
            "n_frames": len(clip.imagenes),
            "latencia_camara_ms": self._desfase_ns / 1e6,
            "latencia_calibrada": self._calibrado,
            "camara": self._camara_id,
            "envio": "pendiente" if self._enviar else "local",
            "creado_utc": ahora.isoformat(),
        }
        ruta_video = cfg.directorio / f"{id_tocado}.mp4"
        ruta_json = cfg.directorio / f"{id_tocado}.json"
        escribir_mp4(ruta_video, clip.imagenes, cfg.fps)
        ruta_json.write_text(json.dumps(metadatos, ensure_ascii=False, indent=2), encoding="utf-8")
        self.tocados_escritos += 1
        logger.info(
            "[Captura] Tocado %s: luces A=%s B=%s, %d frames",
            id_tocado,
            instantes["A"],
            instantes["B"],
            len(clip.imagenes),
        )
        self._conservar_ultimos(cfg.k_tocados)
        return TocadoCapturado(id_tocado, ruta_video, ruta_json, metadatos)

    def _conservar_ultimos(self, k: int) -> None:
        """Borra los tocados más viejos (por nombre, que lleva la hora) dejando los últimos `k`."""
        jsons = sorted(self._config.directorio.glob("tocado_*.json"))
        for viejo in jsons[: max(0, len(jsons) - k)]:
            for ruta in (viejo, viejo.with_suffix(".mp4")):
                ruta.unlink(missing_ok=True)
