from fog.application.forward_verdict import ForwardVerdictToClient
from fog.domain.models import MotivoNoDisponible, UnavailableResult, VerdictView, WeaponSide
from fog.infrastructure.webrtc.session_registry import SessionRegistry
from tests.fog.fakes import FakeVerdictSubscriber


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


async def test_forward_verdict_sets_session_state_and_sends_when_ws_connected():
    sessions = SessionRegistry()
    session = sessions.create("m1", "r1", WeaponSide.RIGHT, WeaponSide.RIGHT)
    session.ws = FakeWebSocket()

    verdict = VerdictView(match_id="m1", revision_id="r1", fencer="ROJ", action="AttackA", confidence=0.91)
    use_case = ForwardVerdictToClient(subscriber=FakeVerdictSubscriber(verdict), sessions=sessions)

    await use_case.execute("r1")

    assert session.verdict == verdict
    assert session.verdict_event.is_set()
    assert session.ws.sent == [{
        "type": "veredicto", "match_id": "m1", "revision_id": "r1", "fencer": "ROJ", "action": "AttackA", "confidence": 0.91,
    }]
    # DEF-16: tras entregar el veredicto, la sesión queda marcada como
    # cerrada para que SessionRegistry.sweep_expired la libere pasado
    # SESSION_TTL_S.
    assert session.closed_at is not None


async def test_forward_verdict_no_op_when_session_missing():
    sessions = SessionRegistry()  # nunca se creó la sesión "r404"
    verdict = VerdictView(match_id="m404", revision_id="r404", fencer="VER", action="AttackB", confidence=0.5)
    use_case = ForwardVerdictToClient(subscriber=FakeVerdictSubscriber(verdict), sessions=sessions)

    await use_case.execute("r404")  # no debe lanzar, solo loggear


async def test_forward_verdict_sets_state_without_ws_connected():
    sessions = SessionRegistry()
    session = sessions.create("m2", "r2", WeaponSide.RIGHT, WeaponSide.RIGHT)

    verdict = VerdictView(match_id="m2", revision_id="r2", fencer="ROJ", action="ResponseA", confidence=0.6)
    use_case = ForwardVerdictToClient(subscriber=FakeVerdictSubscriber(verdict), sessions=sessions)

    await use_case.execute("r2")

    assert session.verdict == verdict
    assert session.verdict_event.is_set()
    assert session.closed_at is not None


async def test_forward_verdict_cloud_no_disponible_cierra_la_sesion_y_avisa_por_ws():
    """Cloud publicó disponible=false (DEF-09, mensaje_invalido): Fog lo
    trata como "no disponible", no como veredicto."""
    sessions = SessionRegistry()
    session = sessions.create("m3", "r3", WeaponSide.RIGHT, WeaponSide.LEFT)
    session.ws = FakeWebSocket()
    resultado = UnavailableResult(
        match_id="m3", revision_id="r3", motivo=MotivoNoDisponible.MENSAJE_INVALIDO
    )
    use_case = ForwardVerdictToClient(subscriber=FakeVerdictSubscriber(resultado), sessions=sessions)

    await use_case.execute("r3")

    assert session.verdict is None
    assert session.unavailable == resultado
    assert session.closed_at is not None
    assert session.ws.sent == [
        {"type": "no_disponible", "match_id": "m3", "revision_id": "r3", "motivo": "mensaje_invalido"}
    ]


async def test_forward_verdict_de_dos_revisiones_del_mismo_combate_no_se_mezclan():
    """Un combate admite N revisiones: cada veredicto llega solo a la
    sesión de su revision_id."""
    sessions = SessionRegistry()
    sesion_1 = sessions.create("m", "r-1", WeaponSide.RIGHT, WeaponSide.RIGHT)
    sesion_2 = sessions.create("m", "r-2", WeaponSide.RIGHT, WeaponSide.RIGHT)
    veredicto = VerdictView(match_id="m", revision_id="r-2", fencer="VER", action="RiposteB", confidence=0.7)
    use_case = ForwardVerdictToClient(subscriber=FakeVerdictSubscriber(veredicto), sessions=sessions)

    await use_case.execute("r-2")

    assert sesion_2.verdict == veredicto
    assert sesion_1.verdict is None
    assert sesion_1.closed_at is None
