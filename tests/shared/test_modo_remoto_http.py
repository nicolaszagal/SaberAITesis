"""DEPLOY11 — scripts del modo remoto con Cloud por HTTP: variables, compose sin Redis y token de nodo."""

import os
import pathlib
import stat
import subprocess

BACKEND = pathlib.Path(__file__).resolve().parents[2]
TOKEN = "k" * 43


def _sh(cmd, tmp_path, **env):
    return subprocess.run(["sh", "-c", cmd], cwd=tmp_path, capture_output=True, text=True, env={**os.environ, **env})


def _entorno(tmp_path, remoto: bool, extra: str = ""):
    (tmp_path / ".env").write_text("POSTGRES_PASSWORD=pw\nPROXY_SHARED_TOKEN=heredado\n")
    (tmp_path / "fog_remoto.env").write_text(
        "CLOUD_TRANSPORTE=http\nCLOUD_URL=https://cloud.test\nCORS_ORIGINS=https://f.test\nPROXY_SHARED_TOKEN=heredado\n" + extra
    )
    cmd = (f'ENV_FILE=.env; ENV_SECRETO=fog_remoto.env; MODO_REMOTO={int(remoto)}; BACKEND_DIR=/b; '
           f'. {BACKEND}/scripts/lib_fog_env.sh; cargar_archivos_env; aplicar_modo; '
           'if usa_http; then h=1; else h=0; fi; '
           'echo "$ENTORNO|${CLOUD_TRANSPORTE:-}|${CLOUD_URL:-}|${PROXY_SHARED_TOKEN:-}|$h|$(archivos_compose)"')
    return _sh(cmd, tmp_path).stdout.strip()


def test_remoto_http_fija_entorno_quita_el_token_de_proxy_y_usa_el_compose_sin_redis(tmp_path):
    entorno, transporte, url, proxy, http, compose = _entorno(tmp_path, remoto=True).split("|")
    assert (entorno, transporte, url, proxy, http) == ("remoto", "http", "https://cloud.test", "", "1")
    assert "docker-compose.http.yml" in compose


def test_el_modo_local_ignora_la_configuracion_http(tmp_path):
    (tmp_path / ".env").write_text("POSTGRES_PASSWORD=pw\nCLOUD_TRANSPORTE=http\nCLOUD_URL=https://cloud.test\n")
    cmd = (f'ENV_FILE=.env; MODO_REMOTO=0; . {BACKEND}/scripts/lib_fog_env.sh; cargar_archivos_env; aplicar_modo; '
           'if usa_http; then echo http; else echo redis; fi; echo "[${CLOUD_URL:-}]"; archivos_compose')
    salida = _sh(cmd, tmp_path).stdout.split("\n")
    assert salida[0] == "redis" and salida[1] == "[]" and "docker-compose.http.yml" not in salida[2]


def test_el_perfil_http_solo_deja_postgres_en_up(tmp_path):
    """`up -d` con el perfil sin Redis levanta únicamente PostgreSQL (los demás servicios van en el perfil local)."""
    import pytest

    cmd = (f'. {BACKEND}/scripts/lib_compose.sh; detectar_compose || exit 3; '
           'compose -f docker-compose.yml -f docker-compose.nativo.yml -f docker-compose.http.yml config --services')
    r = subprocess.run(["sh", "-c", cmd], cwd=BACKEND, capture_output=True, text=True,
                       env={**os.environ, "POSTGRES_PASSWORD": "x", "AUTH_USER": "u", "AUTH_PASSWORD_HASH": "h",
                            "AUTH_JWT_SECRET": "s"})
    if r.returncode == 3:
        pytest.skip("Docker Compose no disponible")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["postgres"]


def test_fog_nativo_con_http_muestra_cloud_sin_redis(tmp_path):
    env = tmp_path / "e.env"
    env.write_text("RESPALDO_DIR=/r\nPOSTGRES_PASSWORD=xyz\nCLOUD_TRANSPORTE=http\nCLOUD_URL=https://cloud.test\n"
                   "CORS_ORIGINS=https://f.test\nPROXY_SHARED_TOKEN=heredado\n")
    base = {**os.environ, "ENV_FILE": str(env), "DATOS_DIR": str(tmp_path / "d"), "VENV_DIR": str(BACKEND / ".venv"),
            "SECRETS_DIR": str(tmp_path / "s")}
    r = subprocess.run(["sh", str(BACKEND / "scripts" / "fog_nativo.sh"), "--remoto", "--mostrar"],
                       cwd=BACKEND, env=base, capture_output=True, text=True)
    assert "CLOUD_TRANSPORTE=http  CLOUD_URL=https://cloud.test" in r.stdout, r.stdout + r.stderr
    assert "CORS_ORIGINS=https://f.test" in r.stdout
    assert "cloud_token.txt" in r.stdout and "FALTA" in r.stdout
    assert "REDIS_URL=" not in r.stdout and "xyz" not in r.stdout and "heredado" not in r.stdout
    assert "BIND_HOST=127.0.0.1" in r.stdout


def test_importar_token_por_el_instalador_deja_el_archivo_600_y_no_lo_muestra(tmp_path):
    origen = tmp_path / "revisor.token"
    origen.write_text(TOKEN + "\n")
    secretos = tmp_path / "s"
    r = subprocess.run(["sh", str(BACKEND / "scripts" / "instalar_fog.sh"), "importar-token", str(origen)],
                       cwd=BACKEND, capture_output=True, text=True,
                       env={**os.environ, "SECRETS_DIR": str(secretos), "ENV_FILE": str(tmp_path / "x.env")})
    assert r.returncode == 0, r.stderr
    destino = secretos / "cloud_token.txt"
    assert destino.read_text().strip() == TOKEN
    assert stat.S_IMODE(destino.stat().st_mode) == 0o600
    assert TOKEN not in r.stdout + r.stderr


def test_importar_token_sin_archivo_valido_falla(tmp_path):
    r = subprocess.run(["sh", str(BACKEND / "scripts" / "instalar_fog.sh"), "importar-token", str(tmp_path / "no-existe")],
                       cwd=BACKEND, capture_output=True, text=True,
                       env={**os.environ, "SECRETS_DIR": str(tmp_path / "s"), "ENV_FILE": str(tmp_path / "x.env")})
    assert r.returncode == 1
