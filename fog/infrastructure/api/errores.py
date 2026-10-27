"""Errores HTTP con código estable.

Los clientes distinguen las causas de un mismo estado (p. ej. los dos 409 de
`/pose`) por `codigo`, no por el texto de `detail`, que puede cambiar.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse

SIN_CLASIFICACION = "sin_clasificacion"
KEYPOINTS_ALTERADOS = "keypoints_alterados"
VEREDICTO_YA_REGISTRADO = "veredicto_ya_registrado"


class ErrorConCodigo(HTTPException):
    """HTTPException cuyo cuerpo es `{"detail": ..., "codigo": ...}`.

    Args:
        status_code: estado HTTP.
        detail: texto para personas; puede cambiar.
        codigo: identificador estable de la causa.
    """

    def __init__(self, status_code: int, detail: str, codigo: str):
        super().__init__(status_code=status_code, detail=detail)
        self.codigo = codigo


async def _manejar_error_con_codigo(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ErrorConCodigo):
        return await http_exception_handler(request, exc)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "codigo": exc.codigo},
        headers=exc.headers,
    )


def registrar_manejadores(app: FastAPI) -> None:
    """Registra el manejador de `ErrorConCodigo` en la app."""
    app.add_exception_handler(ErrorConCodigo, _manejar_error_con_codigo)
