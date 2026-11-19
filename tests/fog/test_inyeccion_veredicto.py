"""SEC02: un XADD a mano en cloud:verdicts:* no se convierte en clasificación."""

import asyncio
import uuid

import fakeredis

from fog.application.forward_verdict import ForwardVerdictToClient
from fog.domain.models import WeaponSide
from fog.infrastructure.messaging.redis_verdict_subscriber import RedisVerdictSubscriber
from fog.infrastructure.sesiones.session_registry import SessionRegistry
from tests.fog.fakes import FakeModelos

MODELO = "lstm_6class/run/best_model.pt"


def _campos(modelo: str, accion: str = "AttackA") -> dict:
    return {
        "revision_id": "x", "match_id": "m", "disponible": "true", "action_class": accion,
        "confidence": "0.99", "fencer": "ROJ", "probs": "{}", "modelo": modelo,
    }


def test_xadd_a_mano_en_una_revision_inexistente_no_genera_clasificacion(crear_app):
    app = crear_app(autenticado=False)
    redis_remoto = fakeredis.FakeAsyncRedis()
    inexistente = str(uuid.uuid4())
    sessions = SessionRegistry()
    uso = ForwardVerdictToClient(
        subscriber=RedisVerdictSubscriber(redis_remoto), sessions=sessions, modelos=FakeModelos()
    )

    async def atacar():
        await redis_remoto.xadd(f"cloud:verdicts:{inexistente}", _campos(MODELO))
        await asyncio.wait_for(uso.execute(inexistente), timeout=2)

    asyncio.run(atacar())

    assert sessions.get(inexistente) is None
    assert app.sql.escalar("SELECT count(*) FROM sabre.clasificacion") == 0


def test_xadd_con_otro_modelo_en_una_revision_pendiente_se_descarta_hasta_el_legitimo():
    redis_remoto = fakeredis.FakeAsyncRedis()
    sessions = SessionRegistry()
    sesion = sessions.create("m", "r-1", WeaponSide.RIGHT, WeaponSide.RIGHT)
    uso = ForwardVerdictToClient(
        subscriber=RedisVerdictSubscriber(redis_remoto), sessions=sessions, modelos=FakeModelos()
    )

    async def escenario():
        await redis_remoto.xadd("cloud:verdicts:r-1", _campos("lstm_6class/falso/best_model.pt", "AttackB"))
        await redis_remoto.xadd("cloud:verdicts:r-1", _campos(MODELO, "AttackA"))
        await asyncio.wait_for(uso.execute("r-1"), timeout=5)

    asyncio.run(escenario())

    assert sesion.verdict.action == "AttackA"
