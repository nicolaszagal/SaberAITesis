from fog.application.forward_verdict import ForwardVerdictToClient
from fog.domain.models import VerdictView, WeaponSide
from fog.infrastructure.webrtc.session_registry import SessionRegistry
from tests.fog.fakes import FakeVerdictSubscriber


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


async def test_forward_verdict_sets_session_state_and_sends_when_ws_connected():
    sessions = SessionRegistry()
    session = sessions.create("m1", WeaponSide.RIGHT, WeaponSide.RIGHT)
    session.ws = FakeWebSocket()

    verdict = VerdictView(match_id="m1", fencer="ROJ", action="AttackA", confidence=0.91)
    use_case = ForwardVerdictToClient(subscriber=FakeVerdictSubscriber(verdict), sessions=sessions)

    await use_case.execute("m1")

    assert session.verdict == verdict
    assert session.verdict_event.is_set()
    assert session.ws.sent == [{
        "type": "veredicto", "match_id": "m1", "fencer": "ROJ", "action": "AttackA", "confidence": 0.91,
    }]


async def test_forward_verdict_no_op_when_session_missing():
    sessions = SessionRegistry()  # nunca se creó la sesión "m404"
    verdict = VerdictView(match_id="m404", fencer="VER", action="AttackB", confidence=0.5)
    use_case = ForwardVerdictToClient(subscriber=FakeVerdictSubscriber(verdict), sessions=sessions)

    await use_case.execute("m404")  # no debe lanzar, solo loggear


async def test_forward_verdict_sets_state_without_ws_connected():
    sessions = SessionRegistry()
    session = sessions.create("m2", WeaponSide.RIGHT, WeaponSide.RIGHT)

    verdict = VerdictView(match_id="m2", fencer="ROJ", action="ResponseA", confidence=0.6)
    use_case = ForwardVerdictToClient(subscriber=FakeVerdictSubscriber(verdict), sessions=sessions)

    await use_case.execute("m2")

    assert session.verdict == verdict
    assert session.verdict_event.is_set()
