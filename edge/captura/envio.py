"""Envío automático de los tocados a Fog (EDGE02, CU-04).

Cada tocado escrito por `CapturaTocados` queda en disco con `"envio": "pendiente"`. Un hilo los
sube de a uno, en orden, a `POST /matches/{match_id}/tocados` y marca `"enviado"` (con el
`tocado_id` que devuelve Fog). Si Fog no responde, el tocado sigue pendiente y se reintenta con
espera creciente; los errores 4xx del clip (inválido, demasiado grande) son definitivos y quedan
como `"error"`. No se envía nada a la revisión VAR: Fog solo preprocesa (D-04).

Credenciales: el usuario maestro de Fog, desde las variables `EDGE_FOG_USER` y
`EDGE_FOG_PASSWORD` o, si faltan, desde `.secrets/edge_fog_user.txt` y
`.secrets/edge_fog_password.txt` (nunca desde el repo). Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def credenciales_desde_entorno(secretos: Path = Path(".secrets")) -> tuple[str, str] | None:
    """Usuario y clave de Fog para Edge.

    Returns:
        `(usuario, clave)` o `None` si no están configurados.
    """
    usuario = os.environ.get("EDGE_FOG_USER")
    clave = os.environ.get("EDGE_FOG_PASSWORD")
    try:
        usuario = usuario or (secretos / "edge_fog_user.txt").read_text(encoding="utf-8").strip()
        clave = clave or (secretos / "edge_fog_password.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return (usuario, clave) if usuario and clave else None


def cuerpo_multipart(campos: dict[str, str], archivo: Path, nombre_campo: str = "file") -> tuple[bytes, str]:
    """Arma un `multipart/form-data` con campos de texto y un MP4.

    Returns:
        `(cuerpo, valor del encabezado Content-Type)`.
    """
    limite = uuid.uuid4().hex
    partes: list[bytes] = []
    for nombre, valor in campos.items():
        partes.append(
            f'--{limite}\r\nContent-Disposition: form-data; name="{nombre}"\r\n\r\n{valor}\r\n'.encode()
        )
    partes.append(
        (
            f'--{limite}\r\nContent-Disposition: form-data; name="{nombre_campo}"; filename="{archivo.name}"\r\n'
            "Content-Type: video/mp4\r\n\r\n"
        ).encode()
    )
    partes.append(archivo.read_bytes())
    partes.append(f"\r\n--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"


class EnvioFog:
    """Sube a Fog los tocados pendientes del directorio, sin carreras (un solo hilo)."""

    def __init__(
        self,
        directorio: Path,
        fog_url: str,
        credenciales: tuple[str, str] | None,
        *,
        espera_inicial_s: float = 1.0,
        espera_max_s: float = 15.0,
        timeout_s: float = 30.0,
    ) -> None:
        """Prepara el envío (no corre hasta `iniciar`).

        Args:
            directorio: carpeta `datos/edge/tocados`.
            fog_url: base de Fog, p. ej. `http://127.0.0.1:8000`.
            credenciales: usuario maestro y clave, o `None` (no se envía nada y se avisa).
            espera_inicial_s: primera espera tras un fallo de Fog.
            espera_max_s: tope de la espera creciente.
            timeout_s: plazo de cada petición HTTP.
        """
        self._dir = directorio
        self._fog = fog_url.rstrip("/")
        self._credenciales = credenciales
        self._espera_inicial_s = espera_inicial_s
        self._espera_max_s = espera_max_s
        self._timeout_s = timeout_s
        self._token: str | None = None
        self._aviso = threading.Event()
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self.enviados = 0
        self.errores_definitivos = 0

    def iniciar(self) -> None:
        """Arranca el hilo (y reanuda los pendientes que hayan quedado de una corrida anterior)."""
        if self._credenciales is None:
            logger.error("[Envio] Sin credenciales de Fog (EDGE_FOG_USER/EDGE_FOG_PASSWORD o .secrets): no se envía")
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="envio-fog", daemon=True)
        self._hilo.start()
        self._aviso.set()

    def detener(self, timeout_s: float = 3.0) -> None:
        """Detiene el hilo."""
        self._parar.set()
        self._aviso.set()
        if self._hilo is not None:
            self._hilo.join(timeout_s)

    def encolar(self, *_: Any) -> None:
        """Avisa que hay un tocado nuevo (se puede pasar como `al_tocado`)."""
        self._aviso.set()

    # ---- internos

    def pendientes(self) -> list[Path]:
        """JSON de los tocados con envío pendiente, del más viejo al más nuevo."""
        salida = []
        for ruta in sorted(self._dir.glob("tocado_*.json")):
            try:
                if json.loads(ruta.read_text(encoding="utf-8")).get("envio") == "pendiente":
                    salida.append(ruta)
            except (OSError, ValueError):
                continue
        return salida

    def _bucle(self) -> None:
        espera = self._espera_inicial_s
        while not self._parar.is_set():
            self._aviso.wait(timeout=5.0)
            self._aviso.clear()
            while not self._parar.is_set() and self._credenciales is not None:
                pendientes = self.pendientes()
                if not pendientes:
                    break
                if self.enviar(pendientes[0]):
                    espera = self._espera_inicial_s
                else:
                    self._parar.wait(espera)
                    espera = min(espera * 2, self._espera_max_s)

    def enviar(self, ruta_json: Path) -> bool:
        """Sube un tocado.

        Returns:
            True si quedó resuelto (enviado, o error definitivo que no se reintenta); False si
            Fog no respondió o aún no hay combate y hay que reintentar.
        """
        meta = json.loads(ruta_json.read_text(encoding="utf-8"))
        video = ruta_json.with_suffix(".mp4")
        if not video.exists():
            self._marcar(ruta_json, meta, "error", detalle="el clip ya no existe")
            return True
        try:
            match_id = self._combate_activo()
            if match_id is None:
                logger.warning("[Envio] Fog no tiene combate configurado; %s sigue pendiente", meta["id"])
                return False
            campos = {"fuente": meta.get("fuente") or "favero"}
            if meta.get("origen"):
                campos["origen"] = str(meta["origen"])
            for c in ("t_luz_a_ms", "t_luz_b_ms"):
                if meta.get(c) is not None:
                    campos[c] = str(meta[c])
            cuerpo, tipo = cuerpo_multipart(campos, video)
            respuesta = self._pedir("POST", f"/matches/{match_id}/tocados", cuerpo, {"Content-Type": tipo})
        except _ErrorDefinitivo as error:
            self.errores_definitivos += 1
            self._marcar(ruta_json, meta, "error", detalle=str(error))
            return True
        except (OSError, urllib.error.URLError, _ErrorTransitorio) as error:
            logger.warning("[Envio] Fog no respondió (%s); %s sigue pendiente", error, meta["id"])
            return False
        self.enviados += 1
        self._marcar(ruta_json, meta, "enviado", tocado_id_fog=respuesta.get("tocado_id"))
        logger.info("[Envio] %s enviado a Fog (tocado %s)", meta["id"], respuesta.get("tocado_id"))
        return True

    def _marcar(self, ruta: Path, meta: dict, estado: str, **extra: Any) -> None:
        meta.update(envio=estado, **extra)
        tmp = ruta.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ruta)

    def _combate_activo(self) -> str | None:
        try:
            return self._pedir("GET", "/matches/activo").get("match_id")
        except _ErrorDefinitivo:
            return None  # 404: todavía no se configuró un combate

    def _iniciar_sesion(self) -> None:
        usuario, clave = self._credenciales  # type: ignore[misc]
        cuerpo = json.dumps({"usuario": usuario, "password": clave}).encode()
        r = self._pedir("POST", "/auth/login", cuerpo, {"Content-Type": "application/json"}, autenticar=False)
        self._token = r["access_token"]

    def _pedir(self, metodo: str, ruta: str, cuerpo: bytes | None = None, cabeceras=None, autenticar=True) -> dict:
        for intento in (1, 2):
            if autenticar and self._token is None:
                self._iniciar_sesion()
            h = dict(cabeceras or {})
            if autenticar:
                h["Authorization"] = f"Bearer {self._token}"
            req = urllib.request.Request(self._fog + ruta, data=cuerpo, headers=h, method=metodo)
            try:
                with urllib.request.urlopen(req, timeout=self._timeout_s) as r:
                    return json.loads(r.read() or b"{}")
            except urllib.error.HTTPError as error:
                if error.code == 401 and autenticar and intento == 1:
                    self._token = None  # venció el token: iniciar sesión otra vez
                    continue
                detalle = error.read().decode("utf-8", "replace")[:300]
                if error.code in (400, 404, 413, 422):
                    raise _ErrorDefinitivo(f"{error.code}: {detalle}") from None
                raise _ErrorTransitorio(f"{error.code}: {detalle}") from None
        raise _ErrorTransitorio("no se pudo autenticar")


class _ErrorDefinitivo(Exception):
    """Fog rechazó el tocado y reintentar no cambia nada."""


class _ErrorTransitorio(Exception):
    """Fog falló (5xx, sin conexión): se reintenta."""
