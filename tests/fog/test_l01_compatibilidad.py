"""Compatibilidad con el L01 de la Validación 1 (19 campos, con `validacion`).

El JSONL de fixtures es una copia del log real de la sesión piloto (94 revisiones, sin datos
personales). `resumen_esperado.json` lo generó el código anterior a SCOPE01 (commit e596d7d)
sobre las líneas con `validacion == "V1"`. No usa base de datos.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import fields
from pathlib import Path

from fog.domain.evidencia import LineaEvidencia
from fog.domain.resumen_validacion import resumir_validacion
from fog.infrastructure.evidencia.lector_jsonl import LectorEvidenciaJsonl

FIXTURES = Path(__file__).parent / "fixtures"
EVENTO = uuid.UUID("0d51ba68-1a6f-4018-a957-3bc7f6db4868")


def _lineas_del_archivo() -> list[dict]:
    texto = (FIXTURES / "l01_v1_19_campos.jsonl").read_text(encoding="utf-8")
    return [json.loads(x) for x in texto.splitlines()]


def test_el_archivo_viejo_trae_el_campo_validacion():
    filas = _lineas_del_archivo()

    assert len(filas) == 94 and all(len(f) == 19 and f["validacion"] == "V1" for f in filas)


def test_el_lector_actual_lee_el_jsonl_de_19_campos(tmp_path):
    (tmp_path / f"{EVENTO}.jsonl").write_bytes((FIXTURES / "l01_v1_19_campos.jsonl").read_bytes())

    lectura = LectorEvidenciaJsonl(tmp_path).leer(EVENTO)

    assert lectura.presente is True
    assert lectura.lineas_ilegibles == 0
    assert lectura.revision_ids == [f["revision_id"] for f in _lineas_del_archivo()]


def test_el_resumen_del_log_viejo_da_las_cifras_del_codigo_anterior():
    """Se descarta `validacion` y se resume todo en un solo bloque."""
    actuales = {c.name for c in fields(LineaEvidencia)}
    lineas = [
        LineaEvidencia(**{k: v for k, v in f.items() if k in actuales})
        for f in _lineas_del_archivo()
    ]
    esperado = json.loads((FIXTURES / "l01_v1_resumen_esperado.json").read_text(encoding="utf-8"))

    assert resumir_validacion(lineas) == esperado
    assert esperado["n_revisiones"] == 94 and esperado["kappa"]["kappa"] == 0.3712
