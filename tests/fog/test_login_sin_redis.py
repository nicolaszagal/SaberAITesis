"""SEC02: el bloqueo de login no depende del Redis que la nube puede escribir."""

import asyncio

from tests.fog.conftest import AUTH_PASSWORD, AUTH_USUARIO

LOGIN = {"usuario": AUTH_USUARIO, "password": AUTH_PASSWORD}
MALO = {"usuario": AUTH_USUARIO, "password": "otra-clave-incorrecta"}


def test_con_el_redis_remoto_vaciado_el_sexto_intento_sigue_dando_429(crear_app):
    app = crear_app(autenticado=False)
    redis_remoto = app.container.redis_client()

    primeros = []
    for _ in range(5):
        primeros.append(app.client.post("/auth/login", json=MALO).status_code)
        # Quien tenga la credencial de la nube borra todo el Redis tras cada intento.
        asyncio.run(redis_remoto.flushall())
    sexto = app.client.post("/auth/login", json=LOGIN)

    assert primeros == [401] * 5
    assert sexto.status_code == 429
