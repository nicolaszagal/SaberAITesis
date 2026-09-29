"""ResumirValidacion — resumen de una sesión de validación (L02, T-017,
RNF-03, RNF-06).

Calcula todo desde PostgreSQL: el JSONL de L01 no es la fuente (un fallo de
escritura no revierte el veredicto, así que puede tener huecos); solo se
concilia contra la base. Solo lectura: no corrige el JSONL ni asigna nada
(RNF-01).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fog.domain.errors import RecursoNoEncontrado
from fog.domain.evidencia import LineaEvidencia, construir_linea
from fog.domain.resumen_validacion import VALIDACIONES, resumir_validacion
from fog.ports.consulta_evidencia_repository import ConsultaEvidenciaRepositoryPort
from fog.ports.fuente_evidencia_modelo import FuenteEvidenciaModeloPort
from fog.ports.lector_evidencia import LectorEvidenciaPort
from fog.ports.modelo_version_repository import ModeloVersionRepositoryPort
from fog.ports.verificador_auditoria import VerificadorAuditoriaPort


@dataclass(frozen=True)
class ResumenValidacion:
    """Contenido de `resumen.json` y las líneas de `revisiones.csv`."""

    resumen: dict[str, Any]
    lineas: list[LineaEvidencia]


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


class ResumirValidacion:
    def __init__(
        self,
        consulta: ConsultaEvidenciaRepositoryPort,
        lector: LectorEvidenciaPort,
        verificador: VerificadorAuditoriaPort,
        modelos: ModeloVersionRepositoryPort,
        fuente_modelo: FuenteEvidenciaModeloPort,
        reloj: Callable[[], datetime] = _ahora_utc,
    ):
        self._consulta = consulta
        self._lector = lector
        self._verificador = verificador
        self._modelos = modelos
        self._fuente_modelo = fuente_modelo
        self._reloj = reloj

    async def execute(self, evento_id: uuid.UUID) -> ResumenValidacion:
        """Resume las revisiones con veredicto de un evento.

        Args:
            evento_id: evento (sesión de validación) a resumir.

        Returns:
            El resumen (separado en V1 y V2, con conciliación, integridad y
            evidencia del modelo) y las líneas de evidencia armadas con
            `construir_linea` desde la base, en orden estable.

        Raises:
            RecursoNoEncontrado: si el evento no existe.
        """
        if not await self._consulta.existe_evento(evento_id):
            raise RecursoNoEncontrado(f"evento {str(evento_id)!r}")
        cerradas = await self._consulta.listar_con_veredicto(evento_id)
        lineas = [
            construir_linea(
                evento_id=evento_id,
                revision=c.revision,
                tocado=c.tocado,
                clasificacion=c.clasificacion,
                veredicto=c.veredicto,
                modelo=c.modelo,
                auditoria=c.auditoria,
            )
            for c in cerradas
        ]
        resumen = {
            "evento_id": str(evento_id),
            "generado_en": self._reloj().isoformat(timespec="seconds"),
            "conciliacion": self._conciliar(evento_id, lineas),
            "integridad": await self._integridad(),
            "por_validacion": {
                v: resumir_validacion([x for x in lineas if x.validacion == v])
                for v in VALIDACIONES
            },
            "modelo": await self._modelo(lineas),
        }
        return ResumenValidacion(resumen=resumen, lineas=lineas)

    def _conciliar(
        self, evento_id: uuid.UUID, lineas: list[LineaEvidencia]
    ) -> dict[str, Any]:
        """Compara las revisiones con veredicto en la base contra el JSONL."""
        lectura = self._lector.leer(evento_id)
        en_base = {x.revision_id for x in lineas}
        en_jsonl = set(lectura.revision_ids)
        return {
            "n_base": len(lineas),
            "n_jsonl": len(lectura.revision_ids),
            "jsonl_presente": lectura.presente,
            "lineas_ilegibles": lectura.lineas_ilegibles,
            "faltantes_en_jsonl": sorted(en_base - en_jsonl),
            "sobrantes_en_jsonl": sorted(en_jsonl - en_base),
        }

    async def _integridad(self) -> dict[str, Any]:
        """Resultado de `sabre.fn_verificar_auditoria()` (cadena completa)."""
        alterados = await self._verificador.verificar()
        return {
            "fn_verificar_auditoria": "ok" if not alterados else "alterada",
            "integra": not alterados,
            "registros_alterados": len(alterados),
            "seq_alterados": sorted(a.seq for a in alterados),
        }

    async def _modelo(self, lineas: list[LineaEvidencia]) -> dict[str, Any]:
        """Evidencia del modelo: métricas registradas y tabla M01, sin
        recalcular F1 (se mide offline sobre el test set)."""
        activo = await self._modelos.obtener_activo()
        return {
            "nota": (
                "Referencia offline: F1 macro se mide sobre el test set, "
                "no en la sesión."
            ),
            "activo": None
            if activo is None
            else {
                "nombre": activo.nombre,
                "num_clases": activo.num_clases,
                "f1_macro_test": activo.f1_macro_test,
                "kappa_piloto": activo.kappa_piloto,
            },
            "modelos_en_revisiones": sorted({x.modelo for x in lineas}),
            "tabla_m01": self._fuente_modelo.tabla_resumen_m01(),
        }
