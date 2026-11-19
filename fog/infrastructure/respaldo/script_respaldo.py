"""Adaptador de RespaldoSesionPort que corre `scripts/respaldar_sesion.sh` (FIX03).

El script hace el dump, el `.tgz` (sin clips), el manifiesto y la verificación por restauración en una
base temporal; sale con 0 solo si todo pasó.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from pathlib import Path

from fog.ports.respaldo_sesion import RespaldoSesionPort, ResultadoRespaldo

_COLA = 1500  # caracteres de la salida que se devuelven al operador


class ScriptRespaldo(RespaldoSesionPort):
    def __init__(self, script: str | Path, directorio: str | Path, timeout_s: float = 600.0) -> None:
        """Prepara el adaptador.

        Args:
            script: ruta de `respaldar_sesion.sh`.
            directorio: carpeta desde la que se corre (`backend/`).
            timeout_s: tiempo máximo del respaldo.
        """
        self._script = Path(script)
        self._dir = Path(directorio)
        self._timeout_s = timeout_s

    async def respaldar(self, evento_id: uuid.UUID) -> ResultadoRespaldo:
        return await asyncio.to_thread(self._correr, evento_id)

    def _correr(self, evento_id: uuid.UUID) -> ResultadoRespaldo:
        script = self._script if self._script.is_absolute() else self._dir / self._script
        if not script.exists():
            return ResultadoRespaldo(False, f"no existe el script de respaldo {script}")
        try:
            r = subprocess.run(
                ["sh", str(script), "--evento", str(evento_id)], cwd=self._dir, env=os.environ.copy(),
                capture_output=True, text=True, timeout=self._timeout_s, check=False,
            )
        except subprocess.TimeoutExpired:
            return ResultadoRespaldo(False, f"el respaldo superó {self._timeout_s:.0f} s")
        except OSError as error:
            return ResultadoRespaldo(False, f"no se pudo ejecutar el respaldo: {error}")
        salida = (r.stdout + r.stderr).strip()
        return ResultadoRespaldo(r.returncode == 0, salida[-_COLA:] or f"código de salida {r.returncode}")
