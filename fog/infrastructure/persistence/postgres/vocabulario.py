"""Traducción entre los nombres de clase del modelo y los del esquema.

La API, el dominio y los casos de uso hablan siempre con los nombres del
modelo (`AttackA`, `ContrattackA`, `RiposteA`, ...; D-06). Los dominios
`clase_tact` de `docs_claude/sabre_ai_schema.sql` usan `AtaqueA`,
`ContraataqueA`, ... Esta traducción ocurre solo aquí, en los adaptadores de
persistencia: entra al escribir y sale al leer.
"""

from __future__ import annotations

_MODELO_A_ESQUEMA = {
    "AttackA": "AtaqueA",
    "AttackB": "AtaqueB",
    "ContrattackA": "ContraataqueA",
    "ContrattackB": "ContraataqueB",
    "RiposteA": "RiposteA",
    "RiposteB": "RiposteB",
}
_ESQUEMA_A_MODELO = {esquema: modelo for modelo, esquema in _MODELO_A_ESQUEMA.items()}


def clase_a_esquema(clase: str | None) -> str | None:
    """Traduce una clase del modelo al dominio `clase_tact` del esquema.

    Args:
        clase: nombre del modelo (`AttackA`, ...) o None.

    Returns:
        Nombre del esquema (`AtaqueA`, ...), o None si `clase` es None.

    Raises:
        ValueError: si `clase` no es una clase del modelo.
    """
    if clase is None:
        return None
    try:
        return _MODELO_A_ESQUEMA[clase]
    except KeyError:
        raise ValueError(f"clase del modelo desconocida: {clase!r}") from None


def clase_a_modelo(clase: str | None) -> str | None:
    """Inversa de `clase_a_esquema`.

    Args:
        clase: nombre del esquema (`AtaqueA`, ...) o None.

    Returns:
        Nombre del modelo (`AttackA`, ...), o None si `clase` es None.

    Raises:
        ValueError: si `clase` no es un valor del dominio `clase_tact`.
    """
    if clase is None:
        return None
    try:
        return _ESQUEMA_A_MODELO[clase]
    except KeyError:
        raise ValueError(f"clase del esquema desconocida: {clase!r}") from None


def probabilidades_a_esquema(probabilidades: dict | None) -> dict | None:
    """Traduce las llaves de un diccionario de probabilidades al esquema.

    Args:
        probabilidades: `{clase_del_modelo: probabilidad}` o None.

    Returns:
        El diccionario con llaves del esquema, o None.
    """
    if probabilidades is None:
        return None
    return {clase_a_esquema(k): v for k, v in probabilidades.items()}


def probabilidades_a_modelo(probabilidades: dict | None) -> dict | None:
    """Inversa de `probabilidades_a_esquema`.

    Args:
        probabilidades: `{clase_del_esquema: probabilidad}` o None.

    Returns:
        El diccionario con llaves del modelo, o None.
    """
    if probabilidades is None:
        return None
    return {clase_a_modelo(k): v for k, v in probabilidades.items()}
