"""scripts/rotar_secretos.sh (SEC01): retiro, generación, idempotencia y no filtrar valores."""

import hashlib
import pathlib
import shutil
import stat
import subprocess
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = BACKEND / "scripts" / "rotar_secretos.sh"

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="requiere openssl")

VIEJOS = {
    "auth_maestro.txt": "VIEJO-maestro-en-claro",
    "clave_prueba.txt": "VIEJO-clave-prueba",
    "proxy_token.txt": "VIEJO-proxy-token",
}
FOG_ANTERIOR = (
    "ENTORNO=remoto\nAUTH_USER=arbitro\nAUTH_PASSWORD_HASH='$argon2id$VIEJO'\n"
    "AUTH_JWT_SECRET=VIEJO-jwt\nPROXY_SHARED_TOKEN=VIEJO-proxy-token\nCORS_ORIGINS=\n"
    "REDIS_URL_REMOTO=rediss://sabre:VIEJO-redis@host:1/0\nPOSTGRES_PASSWORD=sabre_local\n"
    "FOG_HOST_PORT=8011\nPROXY_SALTOS_CONFIANZA=2\nPOSTGRES_DB_NAME=sabre_expo\n"
)
HASH_NUEVO = "AUTH_PASSWORD_HASH='$argon2id$NUEVO-hash-de-prueba'\n"


@pytest.fixture
def entorno(tmp_path):
    """Carpeta de secretos con lo vigente de antes de la rotación y un .env."""
    secretos = tmp_path / "secretos"
    (secretos / "redis").mkdir(parents=True)
    for nombre, valor in VIEJOS.items():
        (secretos / nombre).write_text(valor)
    (secretos / "redis" / "ca.crt").write_text("CA-VIEJA")
    (secretos / "redis" / "ca 2.key").write_text("CA-VIEJA-DUPLICADA")
    (secretos / "fog_remoto.env").write_text(FOG_ANTERIOR)
    # La contraseña maestra se pide por terminal; la prueba entrega el hash ya creado.
    (secretos / "auth_password_hash.env").write_text(HASH_NUEVO)
    env = tmp_path / ".env"
    env.write_text("POSTGRES_PASSWORD=sabre_local\nFOG_HOST_PORT=8001\n")
    return secretos, env


def _rotar(secretos, env, *args):
    return subprocess.run(
        ["sh", str(SCRIPT), *args],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "SECRETS_DIR": str(secretos),
            "ENV_FILE": str(env),
            "PYTHON": sys.executable,
        },
        timeout=180,
    )


def _sha(ruta):
    return hashlib.sha256(pathlib.Path(ruta).read_bytes()).hexdigest()


def test_retira_lo_vigente_sin_borrar_evidencia(entorno):
    secretos, env = entorno

    res = _rotar(secretos, env)

    assert res.returncode == 0, res.stderr
    retirado = secretos / "_retirado_2026-10-27"
    for nombre, valor in VIEJOS.items():
        assert (retirado / nombre).read_text() == valor
    assert (retirado / "redis" / "ca.crt").read_text() == "CA-VIEJA"
    assert (retirado / "redis" / "ca 2.key").exists()
    assert (retirado / "env.previo").read_text().startswith("POSTGRES_PASSWORD=sabre_local")
    assert not (secretos / "auth_maestro.txt").exists()
    assert not (secretos / "clave_prueba.txt").exists()


def test_genera_secretos_nuevos_con_permisos_600(entorno):
    secretos, env = entorno

    assert _rotar(secretos, env).returncode == 0

    for ruta in [
        "auth_jwt_secret.txt", "proxy_token.txt", "postgres_password.txt",
        "fog_remoto.env", "redis/ca.crt", "redis/ca.key", "redis/server.key",
        "redis/fog.key", "redis/cloud.key", "redis/redis_password.txt",
    ]:
        assert stat.S_IMODE((secretos / ruta).stat().st_mode) == 0o600, ruta
    assert len((secretos / "auth_jwt_secret.txt").read_text()) >= 64
    assert (secretos / "redis" / "ca.crt").read_text() != "CA-VIEJA"
    pg = (secretos / "postgres_password.txt").read_text()
    assert pg.isalnum() and pg != "sabre_local"
    assert f"POSTGRES_PASSWORD={pg}\n" in env.read_text()
    assert "FOG_HOST_PORT=8001" in env.read_text()


def test_fog_remoto_env_usa_valores_nuevos_y_conserva_los_no_secretos(entorno):
    secretos, env = entorno

    assert _rotar(secretos, env).returncode == 0

    fog = (secretos / "fog_remoto.env").read_text()
    for viejo in ("VIEJO-jwt", "VIEJO-proxy-token", "VIEJO-redis", "sabre_local", "$argon2id$VIEJO"):
        assert viejo not in fog
    assert "AUTH_USER=arbitro" in fog and "POSTGRES_DB_NAME=sabre_expo" in fog
    assert HASH_NUEVO in fog
    assert f"AUTH_JWT_SECRET={(secretos / 'auth_jwt_secret.txt').read_text()}\n" in fog
    assert f"PROXY_SHARED_TOKEN={(secretos / 'proxy_token.txt').read_text()}\n" in fog
    assert "@PENDIENTE:6379/0" in fog


def test_no_imprime_valores_de_secretos(entorno):
    secretos, env = entorno

    res = _rotar(secretos, env)

    salida = res.stdout + res.stderr
    for archivo in ("auth_jwt_secret.txt", "proxy_token.txt", "postgres_password.txt"):
        valor = (secretos / archivo).read_text()
        assert valor not in salida
        assert _sha(secretos / archivo)[:8] in salida
    assert (secretos / "redis" / "redis_password.txt").read_text().strip() not in salida
    assert "NEUVO" not in salida and "$argon2id" not in salida


def test_es_idempotente_y_forzar_rota_de_nuevo(entorno):
    secretos, env = entorno
    assert _rotar(secretos, env).returncode == 0
    antes = {p: _sha(p) for p in secretos.rglob("*") if p.is_file() and "_retirado" not in str(p)}

    segunda = _rotar(secretos, env)

    assert segunda.returncode == 0 and "Ya rotado" in segunda.stdout
    despues = {p: _sha(p) for p in secretos.rglob("*") if p.is_file() and "_retirado" not in str(p)}
    assert despues == antes

    jwt_anterior = (secretos / "auth_jwt_secret.txt").read_text()
    forzada = _rotar(secretos, env, "--forzar")
    assert forzada.returncode == 0, forzada.stderr
    assert (secretos / "auth_jwt_secret.txt").read_text() != jwt_anterior
    assert list((secretos / "_retirado_2026-10-27").glob("forzado_*/auth_jwt_secret.txt"))
