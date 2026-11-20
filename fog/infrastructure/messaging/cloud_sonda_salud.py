"""Sonda de Cloud para GET /health de Fog en el transporte HTTP (DEPLOY11): consulta
`GET /health` de Cloud, que no lleva datos sensibles ni token."""

import httpx

from fog.ports.sonda_salud import SondaSaludPort
from shared import config


class CloudSonda(SondaSaludPort):
    def __init__(self, url: str, timeout_s: float = 2.0, cliente: httpx.AsyncClient | None = None):
        """Crea la sonda.

        Args:
            url: base de Cloud (`https://`, o `http://localhost` en pruebas).
            timeout_s: tiempo límite de la consulta.
            cliente: cliente HTTP ya armado (pruebas).

        Raises:
            RuntimeError: si la URL no es admitida.
        """
        self._url = config.validar_cloud_url(url)
        self._timeout_s = timeout_s
        self._cliente = cliente or httpx.AsyncClient(follow_redirects=False)

    async def responde(self) -> bool:
        try:
            r = await self._cliente.get(f"{self._url}/health", timeout=self._timeout_s)
            return r.status_code == 200 and r.json().get("status") == "ok"
        except Exception:
            return False
