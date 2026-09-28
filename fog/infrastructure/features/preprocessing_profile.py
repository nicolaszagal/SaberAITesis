"""Perfil de preprocesamiento de features por versión de modelo.

El recorte (clamp) a ±kσ y la ablación de columnas dependen del checkpoint
con el que se calcularon las estadísticas, no del extractor. Cada versión de
modelo declara su perfil en `preprocessing_profiles.json` (o en el archivo
que indique `FEATURE_PREPROCESSING_PROFILES_PATH`), de modo que cambiarlo no
requiere tocar código (RNF-10).

Los valores de `lstm_6class` replican `dataset/lstm_6class/dataset.py`
(`_standardize_and_clamp`, `_VEL_CLAMP`, `ABLATE_INDICES`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from shared.feature_extractor import TOTAL_FEATURES

DEFAULT_PROFILES_PATH = Path(__file__).with_name("preprocessing_profiles.json")


@dataclass(frozen=True)
class PreprocessingProfile:
    """Recorte y ablación aplicados tras estandarizar.

    Attributes:
        name: nombre de la versión de modelo a la que pertenece el perfil.
        clamp_sigma: las columnas de `clamp_columns` se recortan a ±clamp_sigma.
        clamp_indices: índices de columna (ordenados, sin repetir) a recortar.
        ablate_indices: columnas que se anulan (0.0) tras recortar.
    """

    name: str
    clamp_sigma: float
    clamp_indices: tuple[int, ...]
    ablate_indices: tuple[int, ...]

    @staticmethod
    def from_dict(name: str, data: dict) -> "PreprocessingProfile":
        """Construye y valida un perfil a partir de su definición JSON.

        Args:
            name: nombre de la versión de modelo.
            data: dict con `clamp_sigma` (float > 0), `clamp_columns` (lista de
                rangos [inicio, fin) sobre las 192 columnas) y `ablate_indices`
                (lista de columnas).

        Returns:
            El perfil validado.

        Raises:
            ValueError: si falta un campo, un rango es inválido o un índice
                queda fuera de [0, 192).
        """
        missing = {"clamp_sigma", "clamp_columns", "ablate_indices"} - set(data)
        if missing:
            raise ValueError(f"Perfil '{name}': faltan campos {sorted(missing)}")

        sigma = float(data["clamp_sigma"])
        if sigma <= 0:
            raise ValueError(f"Perfil '{name}': clamp_sigma debe ser > 0, recibido {sigma}")

        clamp: set[int] = set()
        for rng in data["clamp_columns"]:
            if len(rng) != 2:
                raise ValueError(f"Perfil '{name}': rango inválido {rng!r}, se espera [inicio, fin)")
            start, end = int(rng[0]), int(rng[1])
            if not 0 <= start < end <= TOTAL_FEATURES:
                raise ValueError(
                    f"Perfil '{name}': rango {rng!r} fuera de [0, {TOTAL_FEATURES}] o vacío"
                )
            clamp.update(range(start, end))

        ablate = sorted({int(i) for i in data["ablate_indices"]})
        if any(not 0 <= i < TOTAL_FEATURES for i in ablate):
            raise ValueError(f"Perfil '{name}': ablate_indices fuera de [0, {TOTAL_FEATURES})")

        return PreprocessingProfile(
            name=name,
            clamp_sigma=sigma,
            clamp_indices=tuple(sorted(clamp)),
            ablate_indices=tuple(ablate),
        )


def load_profile(name: str, path: str | Path | None = None) -> PreprocessingProfile:
    """Carga el perfil de una versión de modelo desde el JSON de perfiles.

    Args:
        name: versión de modelo (p. ej. "lstm_6class").
        path: JSON de perfiles; None usa el que viene junto a este módulo.

    Returns:
        El perfil validado.

    Raises:
        ValueError: si `name` no está definido en el archivo o el perfil es inválido.
        FileNotFoundError: si el archivo de perfiles no existe.
    """
    profiles_path = Path(path) if path else DEFAULT_PROFILES_PATH
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    if name not in profiles:
        raise ValueError(
            f"Perfil de preprocesamiento '{name}' no definido en {profiles_path}. "
            f"Disponibles: {sorted(profiles)}"
        )
    return PreprocessingProfile.from_dict(name, profiles[name])


def clamp_and_ablate(x: np.ndarray, profile: PreprocessingProfile) -> np.ndarray:
    """Aplica el recorte y la ablación del perfil sobre una secuencia ya estandarizada.

    Args:
        x: (T, 192) secuencia estandarizada; se modifica in situ.
        profile: perfil de la versión de modelo.

    Returns:
        El mismo arreglo `x`.
    """
    if profile.clamp_indices:
        idx = list(profile.clamp_indices)
        x[:, idx] = np.clip(x[:, idx], -profile.clamp_sigma, profile.clamp_sigma)
    if profile.ablate_indices:
        x[:, list(profile.ablate_indices)] = 0.0
    return x
