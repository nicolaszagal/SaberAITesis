"""Genera `requirements-fog.linux-x86_64.lock` a partir de `requirements-fog.lock` (DEPLOY10).

Parte de las versiones exactas del lock de macOS (las mismas de torch, torchvision y ultralytics de
`constraints.txt`) y les agrega las dependencias que solo existen en Linux (CUDA, triton...). Las lee de
los metadatos de PyPI (PEP 658) para Linux x86_64 con Python 3.14 y, cuando una dependencia solo pide un
rango, fija la versión más reciente que lo cumple. NO es un `pip freeze` de un Linux real: es una resolución
por metadatos. Debe confirmarse en el equipo Linux con `sh scripts/instalar_fog.sh instalar` y `probar`.

Si alguna versión del lock de macOS no tiene rueda para Linux x86_64 / cp314, termina con error (no
inventa otra versión).

Uso: python3 scripts/generar_lock_linux.py [--entrada requirements-fog.lock] [--salida requirements-fog.linux-x86_64.lock]
Requiere red y `packaging` (viene con pip; use el python del .venv).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

ENTORNO = {
    "platform_system": "Linux", "sys_platform": "linux", "os_name": "posix", "platform_machine": "x86_64",
    "python_version": "3.14", "python_full_version": "3.14.5", "implementation_name": "cpython",
    "platform_python_implementation": "CPython",
}
_RUEDA_VALIDA = re.compile(r"(py3-none-any|py2\.py3-none-any|(py3|cp314)-(none|cp314)-(manylinux|linux).*x86_64|cp3\d+-abi3-manylinux.*x86_64)\.whl$")
_cache: dict[str, dict] = {}


def _json_pypi(nombre: str) -> dict:
    if nombre not in _cache:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{nombre}/json", timeout=60) as r:
            _cache[nombre] = json.load(r)
    return _cache[nombre]


def _rueda(nombre: str, version: str) -> str | None:
    """URL de la rueda compatible con Linux x86_64 / cp314 de una versión, o None."""
    for archivo in _json_pypi(nombre)["releases"].get(version, []):
        if _RUEDA_VALIDA.search(archivo["filename"]) and not archivo.get("yanked"):
            return archivo["url"]
    return None


def _requisitos(nombre: str, version: str, extras: set[str]) -> list[Requirement]:
    url = _rueda(nombre, version)
    if url is None:
        raise SystemExit(f"{nombre}=={version}: no hay rueda para Linux x86_64 / cp314. Se detiene (no se cambia la versión).")
    with urllib.request.urlopen(url + ".metadata", timeout=60) as r:
        texto = r.read().decode()
    salida = []
    for linea in texto.splitlines():
        if not linea.startswith("Requires-Dist:"):
            continue
        req = Requirement(linea.split(":", 1)[1].strip())
        if req.marker is None or any(req.marker.evaluate({**ENTORNO, "extra": e}) for e in (extras or {""})):
            salida.append(req)
    return salida


def resolver(fijas: dict[str, str]) -> dict[str, str]:
    """Devuelve `fijas` más las dependencias solo-Linux, resueltas con la versión más reciente que cumple.

    Itera hasta un punto fijo: reúne los rangos que piden todos los paquetes elegidos, elige para cada
    dependencia nueva la versión más reciente que cumple la unión de rangos y repite, porque otra versión
    puede traer otras dependencias.

    Args:
        fijas: nombre canónico -> versión del lock de macOS.

    Returns:
        Diccionario completo nombre -> versión para Linux.

    Raises:
        SystemExit: si una versión fijada no tiene rueda de Linux, un rango choca con una versión fijada
            o no hay versión que cumpla.
    """
    elegidas = dict(fijas)
    for _ in range(30):
        rangos: dict[str, SpecifierSet] = {}
        extras_de: dict[str, set[str]] = {}
        for nombre, version in elegidas.items():
            for req in _requisitos(nombre, version, extras_de.get(nombre, set()) | _ya_calculado.get(nombre, set())):
                dep = canonicalize_name(req.name)
                rangos[dep] = rangos.get(dep, SpecifierSet()) & req.specifier
                extras_de.setdefault(dep, set()).update(req.extras)
        # Un paquete cuyos extras cambian trae otras dependencias: se recalcula con ellos en la vuelta siguiente.
        siguiente = dict(elegidas)
        for dep, rango in rangos.items():
            if dep in fijas:
                if not rango.contains(fijas[dep], prereleases=True):
                    raise SystemExit(f"alguien pide {dep}{rango} pero el lock fija {dep}=={fijas[dep]}")
                continue
            candidatas = sorted(
                (Version(v) for v in _json_pypi(dep)["releases"] if rango.contains(v) and not Version(v).is_prerelease),
                reverse=True,
            )
            elegida = next((str(v) for v in candidatas if _rueda(dep, str(v))), None)
            if elegida is None:
                raise SystemExit(f"{dep}: ninguna versión que cumpla {rango or '*'} tiene rueda para Linux x86_64 / cp314")
            siguiente[dep] = elegida
        if siguiente == elegidas and all(extras_de.get(n, set()) <= _ya_calculado.get(n, set()) for n in elegidas):
            return elegidas
        for n, e in extras_de.items():
            _ya_calculado.setdefault(n, set()).update(e)
        elegidas = siguiente
    raise SystemExit("la resolución no converge en 30 vueltas")


_ya_calculado: dict[str, set[str]] = {}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--entrada", default="requirements-fog.lock")
    p.add_argument("--salida", default="requirements-fog.linux-x86_64.lock")
    args = p.parse_args()
    fijas = {}
    for linea in Path(args.entrada).read_text().splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#"):
            nombre, version = linea.split("==")
            fijas[canonicalize_name(nombre)] = version
    final = {n: v for n, v in resolver(fijas).items() if n != "pip"}  # pip no se bloquea (no está en el lock de macOS)
    solo_linux = {n: v for n, v in sorted(final.items()) if n not in fijas}
    cuerpo = [f"{n}=={v}" for n, v in sorted(final.items())]
    cabecera = [
        "# Dependencias bloqueadas de Fog para Linux x86_64 (DEPLOY10).",
        f"# Mismas versiones que {args.entrada} ({len(fijas)} paquetes) + {len(solo_linux)} solo de Linux (CUDA, triton...).",
        "# Generado por scripts/generar_lock_linux.py a partir de metadatos de PyPI; NO es un `pip freeze` de un Linux",
        "# real. Tras instalar en el equipo Linux, compare con `pip freeze` y corra `probar`.",
        "# python: 3.14.5",
    ]
    Path(args.salida).write_text("\n".join(cabecera + cuerpo) + "\n")
    print(f"{len(final)} paquetes ({len(solo_linux)} solo Linux) -> {args.salida}")
    for n, v in solo_linux.items():
        print(f"  + {n}=={v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
