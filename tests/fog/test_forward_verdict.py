from fog.application.forward_verdict import ForwardVerdictToClient
from fog.domain.models import MotivoNoDisponible, UnavailableResult, VerdictView, WeaponSide
from fog.infrastructure.webrtc.session_registry import SessionRegistry
from tests.fog.fakes import FakeModelos, FakeSecuenciaSubscriber, FakeVerdictSubscriber

MODELO = "lstm_6class/run/best_model.pt"


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


async def test_forward_verdict_sets_session_state_and_sends_when_ws_connected():
    sessions = SessionRegistry()
    session = sessions.create("m1", "r1", WeaponSide.RIGHT, WeaponSide.RIGHT)
    session.ws = FakeWebSocket()

    verdict = VerdictView(modelo=MODELO, match_id="m1", revision_id="r1", fencer="ROJ", action="AttackA", confidence=0.91)
    use_case = ForwardVerdictToClient(subscriber=FakeVerdictSubscriber(verdict), sessions=sessions, modelos=FakeModelos())

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
    verdict = VerdictView(modelo=MODELO, match_id="m404", revision_id="r404", fencer="VER", action="AttackB", confidence=0.5)
    use_case = ForwardVerdictToClient(subscriber=FakeVerdictSubscriber(verdict), sessions=sessions, modelos=FakeModelos())

    await use_case.execute("r404")  # no debe lanzar, solo loggear


async def test_forward_verdict_sets_state_without_ws_connected():
    sessions = SessionRegistry()
    session = sessions.create("m2", "r2", WeaponSide.RIGHT, WeaponSide.RIGHT)

    verdict = VerdictView(modelo=MODELO, match_id="m2", revision_id="r2", fencer="ROJ", action="ResponseA", confidence=0.6)
    use_case = ForwardVerdictToClient(subscriber=FakeVerdictSubscriber(verdict), sessions=sessions, modelos=FakeModelos())

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
    use_case = ForwardVerdictToClient(subscriber=FakeVerdictSubscriber(resultado), sessions=sessions, modelos=FakeModelos())

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
    veredicto = VerdictView(modelo=MODELO, match_id="m", revision_id="r-2", fencer="VER", action="RiposteB", confidence=0.7)
    use_case = ForwardVerdictToClient(subscriber=FakeVerdictSubscriber(veredicto), sessions=sessions, modelos=FakeModelos())

    await use_case.execute("r-2")

    assert sesion_2.verdict == veredicto
    assert sesion_1.verdict is None
    assert sesion_1.closed_at is None


# --- SEC02: solo se acepta un resultado esperado ----------------------------


class _Espia(FakeVerdictSubscriber):
    llamadas = 0

    async def wait_for_verdict(self, revision_id, aceptar=None):
        self.llamadas += 1
        return await super().wait_for_verdict(revision_id, aceptar)


async def test_revision_sin_sesion_pendiente_ni_se_espera_ni_toca_nada(caplog):
    sessions = SessionRegistry()
    espia = _Espia(VerdictView(modelo=MODELO, match_id="m", revision_id="x", fencer="ROJ", action="AttackA", confidence=0.9))
    use_case = ForwardVerdictToClient(subscriber=espia, sessions=sessions, modelos=FakeModelos())

    with caplog.at_level("WARNING", logger="fog.application"):
        await use_case.execute("revision-inexistente")

    assert espia.llamadas == 0
    assert sessions.get("revision-inexistente") is None
    assert "no hay sesión pendiente" in caplog.text


async def test_sesion_ya_cerrada_no_acepta_otro_veredicto():
    sessions = SessionRegistry()
    session = sessions.create("m", "r", WeaponSide.RIGHT, WeaponSide.RIGHT)
    original = VerdictView(modelo=MODELO, match_id="m", revision_id="r", fencer="ROJ", action="AttackA", confidence=0.9)
    await session.set_verdict(original)
    falso = VerdictView(modelo=MODELO, match_id="m", revision_id="r", fencer="VER", action="AttackB", confidence=1.0)
    use_case = ForwardVerdictToClient(subscriber=FakeVerdictSubscriber(falso), sessions=sessions, modelos=FakeModelos())

    await use_case.execute("r")

    assert session.verdict == original


async def test_veredicto_de_otro_modelo_se_descarta_y_se_acepta_el_siguiente(caplog):
    sessions = SessionRegistry()
    session = sessions.create("m", "r", WeaponSide.RIGHT, WeaponSide.RIGHT)
    inyectado = VerdictView(modelo="lstm_6class/otro/best_model.pt", match_id="m", revision_id="r", fencer="VER", action="AttackB", confidence=1.0)
    legitimo = VerdictView(modelo=MODELO, match_id="m", revision_id="r", fencer="ROJ", action="AttackA", confidence=0.7)
    use_case = ForwardVerdictToClient(subscriber=FakeSecuenciaSubscriber(inyectado, legitimo), sessions=sessions, modelos=FakeModelos())

    with caplog.at_level("WARNING", logger="fog.application"):
        await use_case.execute("r")

    assert session.verdict.action == "AttackA"
    assert "distinto del activo" in caplog.text


async def test_veredicto_sin_modelo_o_sin_modelo_activo_se_descarta():
    sessions = SessionRegistry()
    session = sessions.create("m", "r", WeaponSide.RIGHT, WeaponSide.RIGHT)
    sin_modelo = VerdictView(match_id="m", revision_id="r", fencer="ROJ", action="AttackA", confidence=0.9)

    con_activo = ForwardVerdictToClient(subscriber=FakeSecuenciaSubscriber(sin_modelo), sessions=sessions, modelos=FakeModelos())
    try:
        await con_activo.execute("r")
    except Exception as exc:
        assert type(exc).__name__ == "SinMasEntradas"
    assert session.verdict is None

    sin_activo = ForwardVerdictToClient(
        subscriber=FakeSecuenciaSubscriber(replace_modelo(sin_modelo)), sessions=sessions, modelos=FakeModelos(None)
    )
    try:
        await sin_activo.execute("r")
    except Exception as exc:
        assert type(exc).__name__ == "SinMasEntradas"
    assert session.verdict is None


def replace_modelo(v):
    from dataclasses import replace

    return replace(v, modelo=MODELO)
