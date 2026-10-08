"""Genera el hash Argon2id de la contraseña del usuario maestro (AUTH_PASSWORD_HASH).

La contraseña se pide por `getpass` (no queda en el historial del shell ni en
argumentos de proceso) y debe tener al menos 12 caracteres. Imprime solo el
hash. El hash contiene `$`: en un `.env` hay que ponerlo entre comillas
simples para que Docker Compose y `sh` lo lean literal; `--env` imprime la línea
`AUTH_PASSWORD_HASH='...'` lista para pegar.

Uso (desde backend/):
    python scripts/crear_hash_password.py [--env]
"""

import argparse
import getpass
import sys

from argon2 import PasswordHasher

MIN_CARACTERES = 12


def validar_password(password: str) -> None:
    """Exige la longitud mínima de la contraseña.

    Args:
        password: contraseña en claro.

    Raises:
        ValueError: si tiene menos de 12 caracteres.
    """
    if len(password) < MIN_CARACTERES:
        raise ValueError(f"La contraseña debe tener al menos {MIN_CARACTERES} caracteres.")


def calcular_hash(password: str) -> str:
    """Calcula el hash Argon2id de una contraseña.

    Args:
        password: contraseña en claro, ya validada.

    Returns:
        El hash en formato codificado (`$argon2id$...`).
    """
    return PasswordHasher().hash(password)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--env", action="store_true", help="imprimir la línea AUTH_PASSWORD_HASH='...' para el .env"
    )
    args = parser.parse_args()

    password = getpass.getpass("Contraseña del usuario maestro: ")
    try:
        validar_password(password)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if getpass.getpass("Repetir contraseña: ") != password:
        print("Las contraseñas no coinciden.", file=sys.stderr)
        return 1

    hash_ = calcular_hash(password)
    print(f"AUTH_PASSWORD_HASH='{hash_}'" if args.env else hash_)
    return 0


if __name__ == "__main__":
    sys.exit(main())
