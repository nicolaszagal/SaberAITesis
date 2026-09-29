"""Migración 0002: las funciones de `sabre` fijan su propio search_path.

El engine (fog/infrastructure/persistence/database.py) ya no fija
`search_path` en la conexión. Esta prueba reproduce ese escenario: inserta
en `sabre.registro_auditoria` (vía el trigger `tg_auditoria_hash`, que
llama a `fn_auditoria_hash()`, la cual referencia `registro_auditoria` sin
calificar) desde una conexión cuyo search_path es el de PostgreSQL por
defecto, y verifica que el trigger igual calcula el hash correctamente.
"""

import json

from sqlalchemy import text


async def _insert_returning_id(conn, sql: str, **params) -> str:
    row = (await conn.execute(text(sql + " RETURNING id"), params)).one()
    return str(row[0])


async def test_insertar_auditoria_sin_search_path_en_la_conexion(migrated_engine):
    async with migrated_engine.connect() as conn:
        # La conexión no trae `sabre` en su search_path (default de Postgres).
        search_path = (await conn.execute(text("SHOW search_path"))).scalar_one()
        assert "sabre" not in search_path

        arbitro_id = await _insert_returning_id(
            conn,
            "INSERT INTO sabre.usuario (nombre, rol) VALUES (:nombre, 'arbitro')",
            nombre="Árbitro de prueba",
        )
        tirador_a_id = await _insert_returning_id(
            conn,
            "INSERT INTO sabre.tirador (alias, brazo_habitual, es_menor) "
            "VALUES (:alias, 'diestro', false)",
            alias="Tirador A de prueba",
        )
        tirador_b_id = await _insert_returning_id(
            conn,
            "INSERT INTO sabre.tirador (alias, brazo_habitual, es_menor) "
            "VALUES (:alias, 'zurdo', false)",
            alias="Tirador B de prueba",
        )
        combate_id = await _insert_returning_id(
            conn,
            "INSERT INTO sabre.combate "
            "(pista, tirador_a_id, tirador_b_id, brazo_a, brazo_b, "
            "arbitro_id, configurado_por) "
            "VALUES (:pista, :tirador_a_id, :tirador_b_id, 'diestro', 'zurdo', "
            ":arbitro_id, :arbitro_id)",
            pista="pista-1",
            tirador_a_id=tirador_a_id,
            tirador_b_id=tirador_b_id,
            arbitro_id=arbitro_id,
        )
        tocado_id = await _insert_returning_id(
            conn,
            "INSERT INTO sabre.tocado (combate_id, fuente, luz_a, luz_b, t_tocado_ms) "
            "VALUES (:combate_id, 'simulado', true, false, 1000)",
            combate_id=combate_id,
        )
        revision_id = await _insert_returning_id(
            conn,
            "INSERT INTO sabre.revision_var (tocado_id, aceptada, arbitro_id) "
            "VALUES (:tocado_id, true, :arbitro_id)",
            tocado_id=tocado_id,
            arbitro_id=arbitro_id,
        )

        snapshot = json.dumps(
            {"revision_id": revision_id, "nota": "prueba search_path"}
        )
        registro = (
            await conn.execute(
                text(
                    "INSERT INTO sabre.registro_auditoria (revision_id, snapshot) "
                    "VALUES (:revision_id, CAST(:snapshot AS JSONB)) "
                    "RETURNING seq, hash_prev, hash"
                ),
                {"revision_id": revision_id, "snapshot": snapshot},
            )
        ).one()

        assert registro.hash_prev is None
        assert len(registro.hash) == 64

        # fn_verificar_auditoria() también referencia registro_auditoria sin
        # calificar: sin search_path pinneado a nivel de función, esto
        # fallaría con "relation registro_auditoria does not exist".
        alterados = (
            await conn.execute(text("SELECT * FROM sabre.fn_verificar_auditoria()"))
        ).all()
        assert alterados == []

        await conn.rollback()
