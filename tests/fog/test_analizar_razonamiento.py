"""Análisis descriptivo del razonamiento (EXP03-b): resumen, informe y caso de uso
de solo lectura sobre PostgreSQL real."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime

from fog.domain.analisis_razonamiento import ClipAnalizado, resumir
from fog.infrastructure.evidencia import informe_razonamiento
from tests.fog.conftest import clip_de_prueba
from tests.fog.test_api_razonamiento import N, _subir


def clip(estado, causa=None, u1=(), u2=None, lock=0, nombre="c"):
    return ClipAnalizado(nombre, "AttackA", estado, causa, tuple(u1), u2, lock)


def test_resumen_cuenta_estados_causas_censuras_y_lock():
    clips = [
        clip("respaldada", lock=0),
        clip("insuficiente", "sin_subida", lock=3),
        clip("insuficiente", "deteccion", lock=7),
        clip("no_concluyente", u1=("A", "B"), u2=True, lock=20),
        clip("discordante", u1=("A",), u2=False, lock=-1),
    ]
    r = resumir(clips)
    assert r.n == 5
    assert r.estados == {"respaldada": 1, "discordante": 1, "no_concluyente": 1, "insuficiente": 2}
    assert r.causas_insuficiente == {"sin_subida": 1, "deteccion": 1}
    assert (r.u1_clips_con_censura, r.u1_clips_ambos_censurados) == (2, 1)
    assert (r.u2_con_inicio, r.u2_censurados) == (2, 1)
    assert r.lock_tramos == {"0": 1, "1 a 5": 1, "6 a 15": 1, "16 o más": 1, "sin lock (-1)": 1}
    assert (r.lock_min, r.lock_mediana, r.lock_max) == (0, 5.0, 20)


def test_resumen_de_una_muestra_vacia_no_divide_por_cero():
    r = resumir([])
    assert r.n == 0 and r.lock_mediana is None


def test_informe_pone_lado_a_lado_validacion_1_y_train(tmp_path):
    from fog.application.analizar_razonamiento import AnalisisEvento

    muestra = tmp_path / "train.json"
    muestra.write_text(json.dumps({
        "descripcion": "42 clips de prueba",
        "clips": [dict(clip="x", clase="AttackA", estado="insuficiente", causa="sin_subida",
                       u1_censurados=[], u2=None, lock_frame=0)],
    }), encoding="utf-8")
    ev = uuid.uuid4()
    analisis = AnalisisEvento(ev, "1", 3, [clip("respaldada"), clip("respaldada")], {"sin_clasificacion": 1})

    destino = informe_razonamiento.escribir(tmp_path, analisis, informe_razonamiento.cargar_muestra_train(muestra))

    assert destino == tmp_path / str(ev) / "razonamiento_v1.md"
    md = destino.read_text(encoding="utf-8")
    assert "| Medida | Validación 1 (n = 2) | Clips de train (n = 1) |" in md
    assert "| Estado `respaldada` | 2 (100.0 %) | 0 (0.0 %) |" in md
    assert "sin_clasificacion: 1" in md and "42 clips de prueba" in md
    assert "no es una métrica de aceptación" in md


def test_analisis_de_solo_lectura_no_escribe_en_evidencia_ni_en_auditoria(crear_app, tmp_path):
    # Dos revisiones: una con ambos brazos ya extendidos (censurada) y otra normal.
    app, rev1 = _subir(crear_app, [150.0] * N, [150.0] * N)
    match = app.configurar()
    resp = app.subir_clip(match, clip_de_prueba(40), t_tocado_ms="3000")
    assert resp.status_code == 200
    antes = (
        app.sql.escalar("SELECT count(*) FROM sabre.evidencia"),
        app.sql.escalar("SELECT count(*) FROM sabre.registro_auditoria"),
    )

    analisis = asyncio.run(app.container.analizar_razonamiento().execute(app.evento_id))

    despues = (
        app.sql.escalar("SELECT count(*) FROM sabre.evidencia"),
        app.sql.escalar("SELECT count(*) FROM sabre.registro_auditoria"),
    )
    assert despues == antes
    ids = {c.clip for c in analisis.clips}
    assert rev1 in ids
    propio = next(c for c in analisis.clips if c.clip == rev1)
    assert propio.estado == "no_concluyente" and propio.u1_censurados == ("A", "B")
    assert propio.lock_frame == 3
    assert analisis.params_version == "1"
    informe = informe_razonamiento.render(analisis, generado_en=datetime(2026, 10, 28, tzinfo=UTC))
    assert "Validación 1 (n = " in informe
