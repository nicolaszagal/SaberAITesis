"""Cierre de sesión: respaldo verificado y, solo si pasa, purga de clips (D-22)."""

from __future__ import annotations

import asyncio
import itertools
import uuid
from datetime import date

import pytest
from dependency_injector import providers

from fog.infrastructure.respaldo.script_respaldo import ScriptRespaldo
from fog.ports.respaldo_sesion import RespaldoSesionPort, ResultadoRespaldo
from shared import config
from tests.fog.conftest import clip_de_prueba


class RespaldoFalso(RespaldoSesionPort):
    def __init__(self, ok=True, detalle="respaldo verificado"):
        self.ok, self.detalle, self.eventos = ok, detalle, []

    async def respaldar(self, evento_id):
        self.eventos.append(evento_id)
        return ResultadoRespaldo(self.ok, self.detalle)


# La base se comparte entre las pruebas del módulo y el almacén direcciona por hash: cada clip lleva un
# número de frames distinto para que su archivo sea único (el caso del archivo compartido se prueba aparte).
_UNICO = itertools.count(4)


# La base se comparte entre las pruebas del módulo y el almacén direcciona por hash: cada clip lleva un
# número de frames distinto para que su archivo sea único (el caso del archivo compartido se prueba aparte).
_UNICO = itertools.count(4)


def _subir(app, match_id, frames=None):
    """Carga manual de un clip (POST /matches/{id}/clip) y devuelve el revision_id."""
    frames = next(_UNICO) if frames is None else frames
    r = app.subir_clip(match_id, clip=clip_de_prueba(frames))
    assert r.status_code == 200, r.text
    return r.json()["revision_id"]


def _videos(app):
    return list(app.storage_dir.rglob("*.mp4"))


def _cerrar(app, match_id):
    return app.client.post("/sesion/cerrar", json={"match_id": match_id})


def test_respaldo_ok_purga_los_clips_y_deja_la_auditoria_verificable(crear_app):
    app = crear_app()
    falso = RespaldoFalso()
    app.container.respaldo_sesion.override(providers.Object(falso))
    match_id = app.configurar()
    revision = _subir(app, match_id)
    assert app.veredicto(revision).status_code == 200  # hay registro de auditoría
    sha = app.sql.filas("SELECT sha256 FROM sabre.clip WHERE combate_id = :m", m=match_id)[0]["sha256"]
    assert _videos(app)

    r = _cerrar(app, match_id)

    assert r.status_code == 200, r.text
    assert r.json()["clips_borrados"] >= 1 and r.json()["respaldo"] == "respaldo verificado"
    assert not _videos(app) and not list(app.storage_dir.rglob("*.mov"))
    evento = app.sql.filas("SELECT evento_id FROM sabre.combate WHERE id = :m", m=match_id)[0]["evento_id"]
    assert falso.eventos == [evento]  # respaldó el evento del combate indicado
    assert app.sql.filas("SELECT sha256 FROM sabre.clip WHERE combate_id = :m", m=match_id)[0]["sha256"] == sha
    assert app.sql.filas("SELECT count(*) AS n FROM sabre.fn_verificar_auditoria()")[0]["n"] == 0
    assert _cerrar(app, match_id).json()["clips_borrados"] == 0  # idempotente


def test_si_el_respaldo_falla_no_se_borra_nada_y_se_informa(crear_app):
    app = crear_app()
    falso = RespaldoFalso(ok=False, detalle="la verificación falló: conteos distintos")
    app.container.respaldo_sesion.override(providers.Object(falso))
    match_id = app.configurar()
    _subir(app, match_id)
    antes = _videos(app)

    r = _cerrar(app, match_id)

    assert r.status_code == 500
    assert r.json()["codigo"] == "respaldo_fallido"
    assert "la verificación falló: conteos distintos" in r.json()["detail"]
    assert "no se borró nada" in r.json()["detail"]
    assert _videos(app) == antes and antes
    falso.ok, falso.detalle = True, "ok"  # se puede reintentar cuando el respaldo vuelva a andar
    assert _cerrar(app, match_id).status_code == 200
    assert not _videos(app)


def test_solo_se_borran_los_clips_de_la_sesion_cerrada(crear_app):
    """Otra sesión (otro evento) conserva sus clips hasta que se cierre la suya."""
    app = crear_app()
    app.container.respaldo_sesion.override(providers.Object(RespaldoFalso()))
    otro_evento = app.sql.escalar(
        "INSERT INTO sabre.evento (nombre, fecha, tipo) VALUES ('Otra sesión', :f, 'piloto') RETURNING id",
        f=date(2026, 11, 19))
    m_a = app.configurar()
    _subir(app, m_a)
    m_b = app.configurar(evento_id=str(otro_evento))
    _subir(app, m_b)
    assert len(_videos(app)) == 2

    assert _cerrar(app, m_b).status_code == 200

    assert len(_videos(app)) == 1  # quedó el de la sesión A


def test_un_clip_identico_de_otra_sesion_no_pierde_su_archivo(crear_app):
    """El almacén direcciona por hash: si otra sesión usa el mismo archivo, no se borra."""
    app = crear_app()
    app.container.respaldo_sesion.override(providers.Object(RespaldoFalso()))
    otro_evento = app.sql.escalar(
        "INSERT INTO sabre.evento (nombre, fecha, tipo) VALUES ('Otra sesión 2', :f, 'piloto') RETURNING id",
        f=date(2026, 11, 20))
    m_a = app.configurar()
    _subir(app, m_a, frames=40)
    m_b = app.configurar(evento_id=str(otro_evento))
    _subir(app, m_b, frames=40)  # mismo contenido que el de la sesión A
    assert len(_videos(app)) == 1

    assert _cerrar(app, m_b).status_code == 200

    assert len(_videos(app)) == 1  # el archivo compartido sigue: lo usa la sesión A


def test_combate_inexistente_o_invalido(crear_app):
    app = crear_app()
    falso = RespaldoFalso()
    app.container.respaldo_sesion.override(providers.Object(falso))
    r = _cerrar(app, str(uuid.uuid4()))
    assert r.status_code == 404 and r.json()["codigo"] == "combate_inexistente"
    assert app.client.post("/sesion/cerrar", json={"match_id": "no-es-uuid"}).status_code == 422
    assert app.client.post("/sesion/cerrar", json={}).status_code == 422
    assert falso.eventos == []


def test_cerrar_sesion_exige_jwt(crear_app):
    app = crear_app(autenticado=False)
    assert app.client.post("/sesion/cerrar", json={"match_id": str(uuid.uuid4())}).status_code == 401


# ------------------------------------------------------------------ adaptador del script


def _script(tmp_path, cuerpo):
    ruta = tmp_path / "respaldo.sh"
    ruta.write_text(cuerpo, encoding="utf-8")
    return ruta


def test_script_respaldo_ok_falla_o_no_existe(tmp_path):
    evento = uuid.uuid4()
    ok = ScriptRespaldo(_script(tmp_path, 'echo "args: $@"\n'), tmp_path)
    r = asyncio.run(ok.respaldar(evento))
    assert r.ok and f"--evento {evento}" in r.detalle
    mal = ScriptRespaldo(_script(tmp_path, 'echo "verificación: conteos distintos" >&2; exit 3\n'), tmp_path)
    r = asyncio.run(mal.respaldar(evento))
    assert not r.ok and "conteos distintos" in r.detalle
    r = asyncio.run(ScriptRespaldo(tmp_path / "nada.sh", tmp_path).respaldar(evento))
    assert not r.ok and "no existe" in r.detalle
    lento = ScriptRespaldo(_script(tmp_path, "sleep 5\n"), tmp_path, timeout_s=0.3)
    r = asyncio.run(lento.respaldar(evento))
    assert not r.ok and "superó" in r.detalle
