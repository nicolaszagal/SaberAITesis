"""LocalFileStorage: guarda clips y keypoints por SHA-256 y devuelve (uri, sha256)."""

import hashlib
import re

import numpy as np
import pytest

from fog.infrastructure.storage.local_file_storage import LocalFileStorage


@pytest.fixture
def storage(tmp_path):
    return LocalFileStorage(tmp_path / "storage")


async def test_save_clip_devuelve_uri_y_sha256_del_contenido(storage, tmp_path):
    origen = tmp_path / "tocado.MP4"
    origen.write_bytes(b"video-de-prueba" * 1000)

    uri, sha256 = await storage.save_clip(origen)

    assert sha256 == hashlib.sha256(origen.read_bytes()).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", sha256)
    assert uri == f"local://clips/{sha256[:2]}/{sha256}.mp4"
    guardado = storage._root / uri.removeprefix("local://")
    assert guardado.read_bytes() == origen.read_bytes()


async def test_save_clip_mismo_contenido_no_duplica(storage, tmp_path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    a.write_bytes(b"igual")
    b.write_bytes(b"igual")

    assert await storage.save_clip(a) == await storage.save_clip(b)
    assert len(list((storage._root / "clips").rglob("*.mp4"))) == 1


async def test_save_clip_inexistente_falla_sin_dejar_archivos(storage, tmp_path):
    with pytest.raises(FileNotFoundError):
        await storage.save_clip(tmp_path / "no_existe.mp4")
    assert not (storage._root / "clips").exists()


async def test_save_keypoints_npz_recuperable_y_hash_coincide(storage):
    kp = np.arange(24, dtype=np.float32).reshape(2, 3, 4)

    uri, sha256 = await storage.save_keypoints({"keypoints": kp})

    assert uri == f"local://keypoints/{sha256[:2]}/{sha256}.npz"
    guardado = storage._root / uri.removeprefix("local://")
    assert hashlib.sha256(guardado.read_bytes()).hexdigest() == sha256
    with np.load(guardado) as npz:
        np.testing.assert_array_equal(npz["keypoints"], kp)


async def test_no_quedan_temporales(storage, tmp_path):
    origen = tmp_path / "c.mov"
    origen.write_bytes(b"x")
    await storage.save_clip(origen)
    await storage.save_keypoints({"k": np.zeros(3)})
    assert not list(storage._root.rglob("*.tmp"))


def test_build_engine_sin_database_url_falla_con_mensaje_claro():
    from fog.infrastructure.persistence.database import build_engine

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        build_engine(None)
