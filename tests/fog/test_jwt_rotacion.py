"""SEC01: al rotar AUTH_JWT_SECRET, los tokens firmados con el secreto anterior dejan de valer."""

import pytest

from fog.domain.errors import TokenInvalido
from fog.infrastructure.auth.jwt_emisor import JwtEmisor


def test_token_del_secreto_anterior_es_rechazado_con_el_secreto_nuevo():
    anterior = JwtEmisor("secreto-anterior-" + "a" * 32, ttl_s=3600)
    nuevo = JwtEmisor("secreto-nuevo-" + "b" * 32, ttl_s=3600)
    token_viejo = anterior.emitir("arbitro").access_token

    with pytest.raises(TokenInvalido):
        nuevo.validar(token_viejo)
    assert nuevo.validar(nuevo.emitir("arbitro").access_token) == "arbitro"
