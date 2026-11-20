"""HttpCloudTransport — transporte Fog → Cloud por HTTPS (DEPLOY11).

Implementa los dos puertos que en el modo local implementan `RedisFeaturePublisher` y
`RedisVerdictSubscriber`, con una sola petición `POST /v1/clasificar` por revisión:

- `publish` lanza la petición en segundo plano (igual que publicar en un stream no espera el
  resultado) y guarda su resultado por `revision_id`.
- `wait_for_verdict` espera ese resultado, igual que antes esperaba el stream de veredictos.

Así el dominio y los casos de uso (`ProcessIncomingMatch`, `ForwardVerdictToClient`) no cambian.
Si Cloud no responde a tiempo, rechaza al nodo o falla, la revisión queda en el estado que ya
existe, "Clasificación no disponible" con motivo `timeout`; si Cloud rechaza el contenido
(400, 413, 422), con `mensaje_invalido`. El token va solo en la cabecera `Authorization`: no se
registra ni aparece en ningún mensaje.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections.abc import Awaitable, Callable

import httpx

from fog.domain.models import (
    ExtractedFeatures, LuzSignal, MotivoNoDisponible, UnavailableResult, VerdictView, WeaponSide,
)
from fog.ports.feature_publisher import FeatureStreamPublisherPort
from fog.ports.verdict_subscriber import Resultado, VerdictStreamSubscriberPort
from shared import config

log = logging.getLogger("fog.infrastructure")

# Estados con los que Cloud dice "el contenido que enviaste no sirve".
_CONTENIDO_RECHAZADO = (400, 413, 422)
# Las peticiones sin recoger se descartan pasado este tiempo (nadie esperó su resultado).
_RETENCION_S = 600.0


class HttpCloudTransport(FeatureStreamPublisherPort, VerdictStreamSubscriberPort):
    def __init__(
        self,
        url: str,
        token: str,
        timeout_s: float,
        cliente: httpx.AsyncClient | None = None,
    ):
        """Crea el transporte.

        Args:
            url: base de Cloud; solo `https://` (o `http://localhost` en pruebas).
            token: token del nodo; se envía como `Authorization: Bearer`.
            timeout_s: tiempo máximo de cada petición a Cloud.
            cliente: cliente HTTP ya armado (pruebas); por defecto se crea uno con verificación
                TLS y sin seguir redirecciones.

        Raises:
            RuntimeError: si la URL no es admitida (`config.validar_cloud_url`).
        """
        self._url = config.validar_cloud_url(url)
        self._timeout_s = timeout_s
        self._cliente = cliente or httpx.AsyncClient(
            base_url=self._url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(timeout_s),
            follow_redirects=False,
        )
        self._pendientes: dict[str, tuple[asyncio.Task, float]] = {}

    async def cerrar(self) -> None:
        """Cancela las peticiones en curso y cierra el cliente HTTP."""
        for tarea, _ in self._pendientes.values():
            tarea.cancel()
        self._pendientes.clear()
        await self._cliente.aclose()

    async def publish(
        self,
        match_id: str,
        revision_id: str,
        features: ExtractedFeatures,
        luz: LuzSignal,
        weapon_side_a: WeaponSide,
        weapon_side_b: WeaponSide,
    ) -> None:
        seq = features.sequence
        if seq is None:
            raise ValueError("no se puede publicar ExtractedFeatures con sequence=None")
        cuerpo = {
            "match_id": match_id,
            "revision_id": revision_id,
            "shape": f"{seq.shape[0]},{seq.shape[1]}",
            "dtype": str(seq.dtype),
            "features": base64.b64encode(seq.tobytes()).decode("ascii"),
            "has_luz_A": luz.has_luz_a,
            "has_luz_B": luz.has_luz_b,
            "weapon_side_A": weapon_side_a.value,
            "weapon_side_B": weapon_side_b.value,
        }
        self._descartar_vencidas()
        self._pendientes[revision_id] = (
            asyncio.create_task(self._clasificar(match_id, revision_id, cuerpo)), time.monotonic(),
        )

    async def wait_for_verdict(
        self,
        revision_id: str,
        aceptar: Callable[[Resultado], Awaitable[bool]] | None = None,
    ) -> Resultado:
        pendiente = self._pendientes.get(revision_id)
        if pendiente is None:
            # Nada que esperar: no hay petición para esa revisión (por ejemplo, ya se entregó).
            log.warning("[%s] no hay petición a Cloud pendiente", revision_id)
            return UnavailableResult(match_id="", revision_id=revision_id, motivo=MotivoNoDisponible.TIMEOUT)
        tarea, _ = pendiente
        try:
            resultado = await asyncio.shield(tarea)
        except asyncio.CancelledError:
            # Se agotó el tiempo de quien esperaba: la petición ya no le sirve a nadie.
            self._pendientes.pop(revision_id, None)
            tarea.cancel()
            raise
        self._pendientes.pop(revision_id, None)
        if aceptar is not None and not await aceptar(resultado):
            # Con un solo resultado por petición no hay "siguiente entrada" que esperar.
            log.warning("[%s] resultado de Cloud descartado por no ser el esperado", revision_id)
            return UnavailableResult(
                match_id=getattr(resultado, "match_id", ""), revision_id=revision_id,
                motivo=MotivoNoDisponible.TIMEOUT,
            )
        return resultado

    def _descartar_vencidas(self) -> None:
        limite = time.monotonic() - _RETENCION_S
        for revision_id in [r for r, (_, t) in self._pendientes.items() if t < limite]:
            self._pendientes.pop(revision_id)[0].cancel()

    async def _clasificar(self, match_id: str, revision_id: str, cuerpo: dict) -> Resultado:
        """Hace la petición y la convierte en un resultado; nunca lanza (salvo cancelación)."""
        inicio = time.perf_counter()

        def no_disponible(motivo: MotivoNoDisponible) -> UnavailableResult:
            return UnavailableResult(match_id=match_id, revision_id=revision_id, motivo=motivo)

        try:
            respuesta = await self._cliente.post("/v1/clasificar", json=cuerpo)
        except httpx.TimeoutException:
            log.error("[%s] Cloud no respondió en %.0f s", revision_id, self._timeout_s)
            return no_disponible(MotivoNoDisponible.TIMEOUT)
        except httpx.HTTPError as e:
            # Solo el tipo de error: el mensaje de httpx puede incluir la URL.
            log.error("[%s] no se pudo contactar a Cloud (%s)", revision_id, type(e).__name__)
            return no_disponible(MotivoNoDisponible.TIMEOUT)
        log.info("[%s] Cloud respondió %d en %d ms", revision_id, respuesta.status_code,
                 (time.perf_counter() - inicio) * 1000)

        if respuesta.status_code in _CONTENIDO_RECHAZADO:
            return no_disponible(MotivoNoDisponible.MENSAJE_INVALIDO)
        if respuesta.status_code != 200:
            if respuesta.status_code in (401, 403):
                log.error("[%s] Cloud rechazó el token de este nodo (%d)", revision_id, respuesta.status_code)
            return no_disponible(MotivoNoDisponible.TIMEOUT)
        try:
            return self._parsear(match_id, revision_id, respuesta.json())
        except (ValueError, KeyError, TypeError):
            log.error("[%s] respuesta de Cloud ilegible", revision_id)
            return no_disponible(MotivoNoDisponible.TIMEOUT)

    @staticmethod
    def _parsear(match_id: str, revision_id: str, datos: dict) -> Resultado:
        """Convierte el JSON de Cloud en el mismo resultado que daba `cloud:verdicts:*`.

        Raises:
            ValueError: si la revisión de la respuesta no es la pedida o el motivo no existe.
            KeyError: si falta un campo obligatorio de un veredicto disponible.
        """
        if datos["revision_id"] != revision_id:
            raise ValueError("la respuesta es de otra revisión")
        if not datos["disponible"]:
            return UnavailableResult(
                match_id=match_id, revision_id=revision_id,
                motivo=MotivoNoDisponible(datos["motivo_no_disp"]),
            )
        return VerdictView(
            match_id=match_id,
            revision_id=revision_id,
            fencer=datos["fencer"],
            action=datos["action_class"],
            confidence=float(datos["confidence"]),
            probs=datos.get("probs"),
            latencia_inferencia_ms=(
                int(datos["latencia_inferencia_ms"]) if datos.get("latencia_inferencia_ms") is not None else None
            ),
            modelo=datos.get("modelo"),
            atencion=datos.get("atencion"),
        )
