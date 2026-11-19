"""ServicioTocados — tocados capturados por Edge (EDGE02, CU-04, CU-05, CU-06).

Cada tocado se registra en cuanto llega su clip y se **preprocesa** sin abrir revisión (pose,
features, Cloud y razonamiento): la revisión VAR se abre solo con `solicitar_var` (D-04, RF-14),
y entonces la sugerencia ya está lista. El estado "No revisado" se deriva (tocado sin revisión).

Cola de procesamiento, un solo trabajador (la pose usa la CPU):
    1. el tocado con VAR pedido,
    2. el tocado más reciente (el único que admite VAR),
    3. los anteriores pendientes, en segundo plano (sus features sirven al reentrenamiento).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from fog.application.abrir_revision import frame_del_tocado
from fog.application.process_match import ProcessIncomingMatch
from fog.application.forward_verdict import ForwardVerdictToClient
from fog.application.registrar_clasificacion import ContextoClip, RegistrarClasificacion
from fog.domain.audit_models import Combate
from fog.domain.errors import RecursoNoEncontrado, VentanaVarCerrada
from fog.domain.models import (
    InstantesLuz,
    MotivoNoDisponible,
    TrackedSequence,
    UnavailableResult,
    VerdictView,
    lado_de_brazo,
)
from fog.infrastructure.webrtc.session_registry import SessionRegistry
from fog.ports.file_storage import FileStoragePort
from fog.ports.procesador_clip import ProcesadorClipPort
from fog.ports.tocados_repository import DecisionPista, TocadoListado, TocadosRepositoryPort
from fog.ports.unidad_de_trabajo import UnidadDeTrabajoPort

log = logging.getLogger("fog.application")

FUENTES = ("favero", "simulado")
VAR_PLAZO_S = 60.0  # RNF-04 / D-08: la sugerencia en <= 60 s desde la solicitud VAR


@dataclass
class _Trabajo:
    tocado_id: uuid.UUID
    combate: Combate
    uri: str
    fps: float
    instantes: InstantesLuz
    creado: float
    var_pedido: bool = False
    estado: str = "procesando"  # procesando | listo | error
    resultado: VerdictView | UnavailableResult | None = None
    hecho: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass(frozen=True)
class VarAbierto:
    """Resultado de "Solicitar VAR"."""

    revision_id: uuid.UUID
    tocado_id: uuid.UUID
    resultado: VerdictView | UnavailableResult
    luz_a: bool
    luz_b: bool


class ServicioTocados:
    def __init__(
        self,
        uow: UnidadDeTrabajoPort,
        tocados: TocadosRepositoryPort,
        procesador: ProcesadorClipPort,
        process_match: ProcessIncomingMatch,
        forward_verdict: ForwardVerdictToClient,
        registrar_clasificacion: RegistrarClasificacion,
        sessions: SessionRegistry,
        storage: FileStoragePort | None = None,
        *,
        clip_timeout_s: float = 60.0,
        verdict_timeout_s: float = 30.0,
        var_plazo_s: float = VAR_PLAZO_S,
    ):
        self._uow = uow
        self._tocados = tocados
        self._procesador = procesador
        self._process_match = process_match
        self._forward = forward_verdict
        self._registrar = registrar_clasificacion
        self._sessions = sessions
        self._storage = storage
        self._clip_timeout_s = clip_timeout_s
        self._verdict_timeout_s = verdict_timeout_s
        self._var_plazo_s = var_plazo_s
        self._trabajos: dict[uuid.UUID, _Trabajo] = {}
        self._pendientes: list[_Trabajo] = []
        self._aviso: asyncio.Event | None = None
        self._tarea: asyncio.Task | None = None

    # ---- alta

    async def recibir(
        self,
        combate: Combate,
        contenido: bytes,
        nombre: str | None,
        instantes: InstantesLuz,
        fuente: str,
    ) -> uuid.UUID:
        """Guarda el clip, registra el tocado y lo encola para preprocesarlo.

        Args:
            combate: combate activo.
            contenido: bytes del MP4 que recortó Edge.
            nombre: nombre del archivo.
            instantes: instante de cada luz, relativo al primer frame del clip.
            fuente: 'favero' o 'simulado' (el botón de prueba emite 'simulado').

        Returns:
            El `tocado_id`, disponible de inmediato (aunque el preproceso siga en curso).

        Raises:
            ValueError: si `fuente` no es válida.
            SinModeloActivo: si no hay versión de modelo activa.
            ClipTooLargeError, InvalidClipError, TocadoFueraDelClipError: del clip.
        """
        if fuente not in FUENTES:
            raise ValueError(f"fuente desconocida: {fuente!r}")
        await self._registrar.verificar_modelo_activo()
        campos: Mapping[str, int] = {
            k: v
            for k, v in (("t_luz_a_ms", instantes.t_luz_a_ms), ("t_luz_b_ms", instantes.t_luz_b_ms))
            if v is not None
        }
        clip = await self._procesador.guardar(contenido, nombre, campos)
        if clip.desfase_recorte_ms:
            log.warning("tocado de Edge recortado de nuevo en Fog (%d ms): Edge debería enviarlo ya recortado",
                        clip.desfase_recorte_ms)
            instantes = InstantesLuz(
                None if instantes.t_luz_a_ms is None else instantes.t_luz_a_ms - clip.desfase_recorte_ms,
                None if instantes.t_luz_b_ms is None else instantes.t_luz_b_ms - clip.desfase_recorte_ms,
            )
        async with self._uow.transaccion() as tx:
            fila_clip = await tx.clips.crear(
                combate_id=combate.id, origen="captura", camara="frontal", uri=clip.uri,
                sha256=clip.sha256, fps=clip.fps, ancho_px=clip.ancho_px, alto_px=clip.alto_px,
                duracion_ms=clip.duracion_ms,
            )
            tocado = await tx.tocados.crear(
                combate_id=combate.id, fuente=fuente, luz_a=instantes.luz.has_luz_a,
                luz_b=instantes.luz.has_luz_b, t_tocado_ms=instantes.t_tocado_ms,
                t_luz_a_ms=instantes.t_luz_a_ms, t_luz_b_ms=instantes.t_luz_b_ms,
            )
            await tx.tocados.vincular_clip(
                tocado.id, fila_clip.id, frame_del_tocado(instantes.t_tocado_ms, clip.fps)
            )
        trabajo = _Trabajo(tocado.id, combate, clip.uri, clip.fps, instantes, time.monotonic())
        self._trabajos[tocado.id] = trabajo
        self._pendientes.append(trabajo)
        self._despertar()
        return tocado.id

    # ---- consultas

    async def listar(self, combate_id: uuid.UUID, limite: int = 20) -> list[tuple[TocadoListado, str]]:
        """Los últimos tocados con su estado de preproceso (procesando, listo o error)."""
        filas = await self._tocados.listar(combate_id, limite)
        return [(self._con_clip_vigente(f), self._estado(f)) for f in filas]

    def _con_clip_vigente(self, fila: TocadoListado) -> TocadoListado:
        """`tiene_clip` solo si el archivo sigue en el almacén (se purga al cerrar la sesión)."""
        if self._storage is None or fila.clip_uri is None or not fila.tiene_clip:
            return fila
        return dataclasses.replace(fila, tiene_clip=self._storage.ruta_local(fila.clip_uri) is not None)

    def _estado(self, fila: TocadoListado) -> str:
        trabajo = self._trabajos.get(fila.id)
        if trabajo is not None:
            return trabajo.estado
        return "listo" if fila.clasificado else "error"

    async def obtener(self, tocado_id: uuid.UUID) -> tuple[TocadoListado, str]:
        """Un tocado con su estado.

        Raises:
            RecursoNoEncontrado: si no existe.
        """
        fila = await self._tocados.obtener(tocado_id)
        if fila is None:
            raise RecursoNoEncontrado(f"tocado {tocado_id} no existe")
        return fila, self._estado(fila)

    async def registrar_decision(
        self, tocado_id: uuid.UUID, clase: str | None, anulado: bool, usuario: uuid.UUID | None
    ) -> DecisionPista:
        """Registra la decisión en pista sin mirar el procesamiento ni mostrar la sugerencia.

        Raises:
            RecursoNoEncontrado: si el tocado no existe.
            ValueError: si falta la clase y no se anuló, o se dan ambas cosas.
        """
        if anulado == (clase is not None):
            raise ValueError("indica una clase o anulado, no ambas ni ninguna")
        if await self._tocados.obtener(tocado_id) is None:
            raise RecursoNoEncontrado(f"tocado {tocado_id} no existe")
        return await self._tocados.registrar_decision(
            tocado_id, clase=clase, anulado=anulado, registrado_por=usuario
        )

    # ---- solicitar VAR

    async def solicitar_var(self, tocado_id: uuid.UUID) -> VarAbierto:
        """Abre la revisión VAR del tocado con la clasificación ya calculada (o la espera).

        Args:
            tocado_id: tocado más reciente del combate.

        Returns:
            La revisión abierta y el resultado para la pantalla.

        Raises:
            RecursoNoEncontrado: si el tocado no existe.
            VentanaVarCerrada: si ya llegó un tocado posterior.
        """
        fila, _ = await self.obtener(tocado_id)
        trabajo = self._trabajos.get(tocado_id)
        if fila.revision_id is None and fila.cerrado:
            raise VentanaVarCerrada(f"el tocado {tocado_id} quedó cerrado como No revisado")
        if trabajo is not None and not trabajo.hecho.is_set():
            trabajo.var_pedido = True
            self._despertar()
            try:
                await asyncio.wait_for(trabajo.hecho.wait(), self._var_plazo_s)
            except asyncio.TimeoutError:
                log.warning("[%s] la sugerencia superó %.0f s tras Solicitar VAR", tocado_id, self._var_plazo_s)
        resultado = trabajo.resultado if trabajo is not None else None
        if resultado is None:
            resultado = UnavailableResult(
                match_id=str(fila.combate_id), revision_id=str(tocado_id), motivo=MotivoNoDisponible.TIMEOUT
            )
            await self._registrar.execute(
                tocado_id=tocado_id, revision_id=None,
                tracked=TrackedSequence(frames=[], frame_w=0, frame_h=0, locked=False),
                resultado=resultado, latencia_ms=int(self._var_plazo_s * 1000),
            )
        async with self._uow.transaccion() as tx:
            combate = await tx.combates.obtener(fila.combate_id)
            if fila.revision_id is not None:
                revision_id = fila.revision_id
            else:
                revision = await tx.revisiones.crear(
                    tocado_id=tocado_id, aceptada=True, arbitro_id=combate.arbitro_id
                )
                revision_id = revision.id
                modelo = await tx.modelos.obtener_activo()
                clasif = await tx.clasificaciones.obtener_por_tocado_y_modelo(tocado_id, modelo.id)
                if clasif is not None:
                    await tx.revisiones.asignar_clasificacion(revision_id, clasif.id)
        await self._sesion_resuelta(combate, str(revision_id), resultado, fila)
        return VarAbierto(revision_id, tocado_id, resultado, fila.luz_a, fila.luz_b)

    async def _sesion_resuelta(self, combate, revision_id, resultado, fila) -> None:
        """Sesión ya resuelta bajo `revision_id`: el WebSocket entrega la sugerencia al instante."""
        if self._sessions.get(revision_id) is not None:
            return
        sesion = self._sessions.create(
            str(combate.id), revision_id, lado_de_brazo(combate.brazo_a), lado_de_brazo(combate.brazo_b)
        )
        resultado = dataclasses.replace(resultado, revision_id=revision_id)
        if isinstance(resultado, VerdictView):
            await sesion.set_verdict(resultado)
        else:
            await sesion.set_unavailable(resultado)

    # ---- cola

    def _despertar(self) -> None:
        loop = asyncio.get_running_loop()
        if self._aviso is None:
            self._aviso = asyncio.Event()
        if self._tarea is None or self._tarea.done() or self._tarea.get_loop() is not loop:
            self._tarea = loop.create_task(self._bucle())
        self._aviso.set()

    def _siguiente(self) -> _Trabajo | None:
        if not self._pendientes:
            return None
        return max(self._pendientes, key=lambda t: (t.var_pedido, t.creado))

    async def _bucle(self) -> None:
        assert self._aviso is not None
        while True:
            trabajo = self._siguiente()
            if trabajo is None:
                self._aviso.clear()
                await self._aviso.wait()
                continue
            self._pendientes.remove(trabajo)
            try:
                await self._preprocesar(trabajo)
            except Exception:  # noqa: BLE001 - un tocado malo no debe detener la cola
                log.exception("[%s] el preproceso falló", trabajo.tocado_id)
                trabajo.estado = "error"
            finally:
                trabajo.hecho.set()

    async def _preprocesar(self, t: _Trabajo) -> None:
        inicio = t.creado
        revision_key = str(t.tocado_id)
        match_id = str(t.combate.id)
        sesion = self._sessions.create(
            match_id, revision_key, lado_de_brazo(t.combate.brazo_a), lado_de_brazo(t.combate.brazo_b)
        )
        sesion.set_luz(t.instantes.luz)
        sesion.t_tocado_ms = t.instantes.t_tocado_ms
        resultado: VerdictView | UnavailableResult | None
        tracked = TrackedSequence(frames=[], frame_w=0, frame_h=0, locked=False)
        try:
            tracked = await self._procesador.extraer_pose(t.uri, self._clip_timeout_s)
        except Exception as error:  # noqa: BLE001 - timeout o clip ilegible: "no disponible"
            motivo = (
                MotivoNoDisponible.TIMEOUT
                if error.__class__.__name__ == "ExtraccionAgotadaError"
                else MotivoNoDisponible.POSE_INCOMPLETA
            )
            resultado = UnavailableResult(match_id=match_id, revision_id=revision_key, motivo=motivo)
            await sesion.set_unavailable(resultado)
        else:
            resultado = await self._process_match.execute(
                match_id, revision_key, tracked, sesion.weapon_side_a, sesion.weapon_side_b, t.instantes.luz
            )
            if resultado is None:
                try:
                    await asyncio.wait_for(self._forward.execute(revision_key), timeout=self._verdict_timeout_s)
                except asyncio.TimeoutError:
                    resultado = UnavailableResult(
                        match_id=match_id, revision_id=revision_key, motivo=MotivoNoDisponible.TIMEOUT
                    )
                    await sesion.set_unavailable(resultado)
                else:
                    resultado = sesion.verdict or sesion.unavailable or UnavailableResult(
                        match_id=match_id, revision_id=revision_key, motivo=MotivoNoDisponible.TIMEOUT
                    )
        await self._registrar.execute(
            tocado_id=t.tocado_id, revision_id=None, tracked=tracked, resultado=resultado,
            latencia_ms=int((time.monotonic() - inicio) * 1000),
            contexto=ContextoClip(
                fps=t.fps, frame_tocado=frame_del_tocado(t.instantes.t_tocado_ms, t.fps),
                weapon_side_a=sesion.weapon_side_a, weapon_side_b=sesion.weapon_side_b,
            ),
        )
        t.resultado = resultado
        t.estado = "listo"
        log.info("[%s] tocado preprocesado en %.1f s", t.tocado_id, time.monotonic() - inicio)
