"""RedisVerdictSubscriber: lee `cloud:verdicts:{revision_id}` (CONTRATO_API.md
sección 6), incluidos los campos de auditoría y la forma disponible=false."""

from fog.domain.models import MotivoNoDisponible, UnavailableResult, VerdictView
from fog.infrastructure.messaging.redis_verdict_subscriber import RedisVerdictSubscriber


class _RedisFalso:
    def __init__(self, campos: dict[bytes, bytes]):
        self._campos = campos
        self.claves: list[str] = []

    async def xread(self, streams, count, block):
        (clave,) = streams
        self.claves.append(clave)
        return [(clave, [(b"1-0", self._campos)])]


async def test_lee_veredicto_con_campos_de_auditoria():
    campos = {
        b"match_id": b"m1", b"disponible": b"true", b"action_class": b"RiposteB",
        b"confidence": b"0.81", b"fencer": b"VER",
        b"probs": b'{"RiposteB": 0.81, "AttackA": 0.19}',
        b"latencia_inferencia_ms": b"14", b"modelo": b"lstm_6class/run/best_model.pt",
    }

    veredicto = await RedisVerdictSubscriber(_RedisFalso(campos)).wait_for_verdict("r1")

    assert veredicto == VerdictView(
        match_id="m1", revision_id="r1", fencer="VER", action="RiposteB", confidence=0.81,
        probs={"RiposteB": 0.81, "AttackA": 0.19}, latencia_inferencia_ms=14,
        modelo="lstm_6class/run/best_model.pt",
    )


async def test_lee_no_disponible_de_cloud_sin_key_error():
    campos = {b"match_id": b"m2", b"disponible": b"false", b"motivo_no_disp": b"mensaje_invalido"}

    resultado = await RedisVerdictSubscriber(_RedisFalso(campos)).wait_for_verdict("r2")

    assert resultado == UnavailableResult(
        match_id="m2", revision_id="r2", motivo=MotivoNoDisponible.MENSAJE_INVALIDO
    )


async def test_entrada_sin_campos_de_auditoria_sigue_siendo_valida():
    campos = {b"action_class": b"AttackA", b"confidence": b"0.5", b"fencer": b"ROJ"}

    veredicto = await RedisVerdictSubscriber(_RedisFalso(campos)).wait_for_verdict("m3")

    assert veredicto.probs is None and veredicto.modelo is None


async def test_lee_el_stream_de_su_revision_y_no_el_del_combate():
    redis = _RedisFalso({b"match_id": b"m", b"disponible": b"false", b"motivo_no_disp": b"mensaje_invalido"})

    await RedisVerdictSubscriber(redis).wait_for_verdict("rev-9")

    assert redis.claves == ["cloud:verdicts:rev-9"]


async def test_no_disponible_sin_match_id_usa_cadena_vacia():
    """Cloud omite `match_id` cuando no pudo leerlo del mensaje inválido."""
    campos = {b"revision_id": b"r5", b"disponible": b"false", b"motivo_no_disp": b"mensaje_invalido"}

    resultado = await RedisVerdictSubscriber(_RedisFalso(campos)).wait_for_verdict("r5")

    assert resultado == UnavailableResult(
        match_id="", revision_id="r5", motivo=MotivoNoDisponible.MENSAJE_INVALIDO
    )
