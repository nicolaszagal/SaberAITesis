"""ESTRES01: prueba de carga de SABRE.AI con 1 a 4 pistas pidiendo revisión VAR a la vez.

MIDE; no implementa soporte multipista (RF-29, F-018 y F-019 son WON'T). La referencia es RNF-04:
sugerencia en <= 60 s (p95) desde que se envía el clip.

Hace login una sola vez (reutiliza el JWT, para no activar el bloqueo de intentos), crea un combate por
pista (`POST /matches/config`) y sube los clips fijos de `scripts/estres/clips.json`
(`POST /matches/{match_id}/clip`). Cada solicitud usa un nombre de archivo único
(`e<escenario>_n<pistas>_r<rep>_<pista>_<k>_<stem>.mp4`) para unir el resultado con los logs de tiempo de Fog
(`ESTRES_TIEMPOS=1`, ver `shared/tiempos.py`) con `desglosar.py`.

Escenarios:
    A  ráfaga: 1..4 pistas suben su clip en el mismo instante (`--pistas 1,2,3,4 --repeticiones 3`).
    B  sostenido: 4 pistas durante `--duracion-s` (600 s), con un intervalo exponencial de media
       `--intervalo-medio-s` entre el fin de una sugerencia y la siguiente solicitud de esa pista
       (obligatorio; lo decide el autor).

Recursos: cada 1 s, CPU y RAM del proceso de Fog (`--fog-pid`, psutil) y de los contenedores indicados
(`--contenedores`, `docker stats` en continuo, por lo que su dato se refresca cada ~1-2 s), y el largo de
`fog:features` (XLEN) con el rezago y los pendientes de su grupo de consumo (`--redis-url`).

Uso (desde backend/ con el .venv; la contraseña va en ESTRES_PASSWORD):
    ESTRES_PASSWORD=... .venv/bin/python scripts/estres/carga.py A --base-url http://127.0.0.1:8021 \\
        --usuario estres --evento <uuid> --arbitro <uuid> --pistas 1,2,3,4 --repeticiones 3 \\
        --salida /ruta/A.jsonl --recursos /ruta/A_recursos.csv --fog-pid 1234
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[2]
CLIPS_JSON = Path(__file__).with_name("clips.json")
DATASET_REPO = BACKEND_DIR.parent  # los clips se citan relativos a `Software/`
PLAZO_RNF04_S = 60.0


def cargar_clips() -> tuple[dict, dict]:
    """Lee `clips.json` y devuelve los clips por stem con su contenido en memoria.

    Returns:
        `(clips_por_stem, pistas)`: cada clip con sus bytes en la clave `contenido`, y el
        orden fijo de stems de cada pista (`P1`..`P4`).

    Raises:
        SystemExit: si falta un archivo o su sha256 no coincide con el de `clips.json`.
    """
    import hashlib

    datos = json.loads(CLIPS_JSON.read_text())
    clips = {}
    for c in datos["clips"]:
        ruta = DATASET_REPO / c["ruta"]
        if not ruta.exists():
            sys.exit(f"falta el clip {ruta}")
        contenido = ruta.read_bytes()
        if hashlib.sha256(contenido).hexdigest() != c["sha256"]:
            sys.exit(f"{c['stem']}: el sha256 no coincide con clips.json (¿cambió el clip?)")
        clips[c["stem"]] = {**c, "contenido": contenido}
    return clips, datos["pistas"]


def percentil(valores: list[float], p: float) -> float | None:
    """Percentil `p` (0-100) por interpolación lineal, como `numpy.percentile`.

    Args:
        valores: muestras.
        p: percentil pedido.

    Returns:
        El percentil, o None si no hay muestras.
    """
    if not valores:
        return None
    v = sorted(valores)
    k = (len(v) - 1) * p / 100
    i = int(k)
    return v[i] if i + 1 >= len(v) else v[i] + (v[i + 1] - v[i]) * (k - i)


class Medidor:
    """Muestrea recursos cada 1 s y los escribe en un CSV (una fila por segundo)."""

    def __init__(self, ruta: Path, fog_pid: int | None, contenedores: list[str], redis_url: str | None):
        self.ruta = ruta
        self.fog_pid = fog_pid
        self.contenedores = contenedores
        self.redis_url = redis_url
        self._ultimo_docker: dict[str, dict] = {}
        self._parar = asyncio.Event()
        self._tareas: list[asyncio.Task] = []
        self.etiqueta = ""

    async def _leer_docker(self) -> None:
        """Lee `docker stats` en continuo y guarda la última lectura por contenedor."""
        if not self.contenedores:
            return
        proc = await asyncio.create_subprocess_exec(
            "docker", "stats", "--format", "{{json .}}", *self.contenedores,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            while not self._parar.is_set():
                linea = await asyncio.wait_for(proc.stdout.readline(), timeout=10)
                if not linea:
                    break
                m = re.search(r"\{.*\}", linea.decode(errors="replace"))
                if not m:
                    continue
                d = json.loads(m.group(0))
                mem = d["MemUsage"].split("/")[0].strip()
                self._ultimo_docker[d["Name"]] = {
                    "cpu": float(d["CPUPerc"].rstrip("%")),
                    "mem_mib": _a_mib(mem),
                }
        except (asyncio.TimeoutError, ValueError, KeyError):
            pass
        finally:
            proc.kill()

    async def _bucle(self) -> None:
        import psutil

        fog = psutil.Process(self.fog_pid) if self.fog_pid else None
        if fog:
            fog.cpu_percent(None)
        cliente_redis = None
        if self.redis_url:
            import redis.asyncio as aioredis

            cliente_redis = aioredis.from_url(self.redis_url, decode_responses=True)
        columnas = ["t_s", "etiqueta", "fog_cpu_pct", "fog_rss_mib", "xlen", "lag", "pendientes"] + [
            f"{c}_{m}" for c in self.contenedores for m in ("cpu_pct", "mem_mib")
        ]
        t0 = time.monotonic()
        with open(self.ruta, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(columnas)
            while not self._parar.is_set():
                fila = [round(time.monotonic() - t0, 2), self.etiqueta]
                if fog:
                    procesos = [fog, *fog.children(recursive=True)]
                    fila += [
                        round(fog.cpu_percent(None), 1),
                        round(sum(p.memory_info().rss for p in procesos) / 2**20, 1),
                    ]
                else:
                    fila += ["", ""]
                xlen = lag = pend = ""
                if cliente_redis:
                    try:
                        xlen = await cliente_redis.xlen("fog:features")
                        for g in await cliente_redis.xinfo_groups("fog:features"):
                            lag, pend = g.get("lag", ""), g.get("pending", "")
                    except Exception:  # noqa: BLE001 — el muestreo no debe tumbar la prueba
                        pass
                fila += [xlen, lag, pend]
                for c in self.contenedores:
                    d = self._ultimo_docker.get(c, {})
                    fila += [d.get("cpu", ""), d.get("mem_mib", "")]
                w.writerow(fila)
                f.flush()
                try:
                    await asyncio.wait_for(self._parar.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass

    async def __aenter__(self) -> "Medidor":
        self._tareas = [asyncio.create_task(self._leer_docker()), asyncio.create_task(self._bucle())]
        await asyncio.sleep(2.5)  # primera lectura de docker stats
        return self

    async def __aexit__(self, *_exc) -> None:
        self._parar.set()
        await asyncio.gather(*self._tareas, return_exceptions=True)


def _a_mib(texto: str) -> float:
    """Convierte `docker stats` (`12.3MiB`, `1.2GiB`, `500kB`) a MiB."""
    m = re.match(r"([\d.]+)\s*([A-Za-z]+)", texto)
    if not m:
        return 0.0
    valor, unidad = float(m.group(1)), m.group(2).lower()
    return valor * {"b": 1 / 2**20, "kb": 1 / 1024, "kib": 1 / 1024, "mb": 1000**2 / 2**20,
                    "mib": 1.0, "gb": 1000**3 / 2**20, "gib": 1024.0}.get(unidad, 1.0)


async def login(cliente: httpx.AsyncClient, usuario: str, password: str) -> dict:
    """Inicia sesión una sola vez y devuelve la cabecera `Authorization`.

    Args:
        cliente: cliente HTTP apuntando a Fog.
        usuario: usuario maestro de Fog.
        password: contraseña del usuario maestro.

    Returns:
        Cabeceras con el JWT, para reutilizar en todas las peticiones.

    Raises:
        SystemExit: si el login falla (no se reintenta: un reintento cuenta para el bloqueo de IP).
    """
    r = await cliente.post("/auth/login", json={"usuario": usuario, "password": password})
    if r.status_code != 200:
        sys.exit(f"login falló: HTTP {r.status_code} {r.text[:120]}")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def configurar_combate(cliente: httpx.AsyncClient, cab: dict, args, pista: str, clip: dict) -> str:
    """Crea el combate de una pista (`POST /matches/config`).

    Args:
        cliente: cliente HTTP.
        cab: cabecera de autorización.
        args: argumentos (evento, árbitro).
        pista: nombre de la pista (`P1`..`P4`).
        clip: primer clip de la pista, del que se toman los brazos armados.

    Returns:
        El `match_id`.

    Raises:
        SystemExit: si la configuración falla.
    """
    r = await cliente.post("/matches/config", headers=cab, json={
        "evento_id": args.evento, "pista": pista, "arbitro_id": args.arbitro,
        "alias_A": "Rojo", "weapon_side_A": clip["weapon_side_A"],
        "alias_B": "Verde", "weapon_side_B": clip["weapon_side_B"],
    })
    if r.status_code != 200:
        sys.exit(f"/matches/config falló en {pista}: HTTP {r.status_code} {r.text[:200]}")
    return r.json()["match_id"]


async def subir_clip(cliente: httpx.AsyncClient, cab: dict, match_id: str, clip: dict, nombre: str) -> dict:
    """Sube un clip y mide la solicitud completa, separando la subida.

    Args:
        cliente: cliente HTTP (la conexión ya está abierta).
        cab: cabecera de autorización.
        match_id: combate de la pista.
        clip: clip de `clips.json` con su contenido en memoria.
        nombre: nombre de archivo único de esta solicitud.

    Returns:
        Registro de la solicitud: tiempos del cliente, estado HTTP y respuesta de Fog.
    """
    datos = {k: str(clip[k]) for k in ("t_luz_a_ms", "t_luz_b_ms") if clip[k] is not None}
    marcas: dict[str, float] = {}

    async def traza(evento: str, _info: dict) -> None:
        if evento == "http11.send_request_body.complete":
            marcas["subida_fin"] = time.perf_counter()

    t0 = time.perf_counter()
    registro = {"archivo": nombre, "stem": clip["stem"], "match_id": match_id, "t_inicio_wall": time.time(),
                "bytes": len(clip["contenido"])}
    try:
        r = await cliente.post(
            f"/matches/{match_id}/clip", headers=cab, data=datos,
            files={"file": (nombre, clip["contenido"], "video/mp4")},
            extensions={"trace": traza}, timeout=httpx.Timeout(180.0),
        )
        total = time.perf_counter() - t0
        registro.update(http=r.status_code, total_s=total,
                        subida_s=marcas.get("subida_fin", t0) - t0)
        if r.status_code == 200:
            j = r.json()
            registro.update(revision_id=j["revision_id"], disponible=j["disponible"], motivo=j["motivo"],
                            timed_out=j["timed_out"], accion=j["action"], confianza=j["confidence"])
        else:
            registro["error"] = r.text[:200]
    except httpx.HTTPError as exc:
        registro.update(http=0, total_s=time.perf_counter() - t0, error=f"{type(exc).__name__}: {exc}")
    registro["fuera_de_60s"] = registro["total_s"] > PLAZO_RNF04_S
    registro["util"] = bool(registro.get("disponible")) and not registro["fuera_de_60s"]
    return registro


async def correr_rafaga(cliente, cab, args, clips, pistas, n: int, rep: int, salida) -> list[dict]:
    """Escenario A: `n` pistas suben su clip en el mismo instante.

    Args:
        cliente: cliente HTTP.
        cab: cabecera de autorización.
        args: argumentos de la línea de comandos.
        clips: clips por stem.
        pistas: orden fijo de stems por pista.
        n: número de pistas simultáneas (1 a 4).
        rep: repetición (0, 1, 2); la pista usa su clip número `rep`.
        salida: archivo JSONL abierto.

    Returns:
        Un registro por pista.
    """
    nombres = [f"P{k + 1}" for k in range(n)]
    elegidos = {p: clips[pistas[p][rep % len(pistas[p])]] for p in nombres}
    matches = {p: await configurar_combate(cliente, cab, args, p, elegidos[p]) for p in nombres}
    # Abre las conexiones antes de la ráfaga (no cuenta en la latencia).
    await asyncio.gather(*(cliente.get("/health") for _ in nombres))
    listo = asyncio.Event()

    async def pista(p: str) -> dict:
        await listo.wait()
        nombre = f"eA_n{n}_r{rep}_{p}_{rep}_{elegidos[p]['stem']}.mp4"
        return await subir_clip(cliente, cab, matches[p], elegidos[p], nombre)

    tareas = [asyncio.create_task(pista(p)) for p in nombres]
    await asyncio.sleep(0.2)
    listo.set()
    resultados = await asyncio.gather(*tareas)
    for p, r in zip(nombres, resultados):
        r.update(escenario="A", pistas=n, rep=rep, pista=p)
        salida.write(json.dumps(r, ensure_ascii=False) + "\n")
        salida.flush()
    return resultados


async def correr_sostenido(cliente, cab, args, clips, pistas, rep: int, salida) -> list[dict]:
    """Escenario B: 4 pistas durante `--duracion-s`, con intervalos exponenciales.

    El intervalo se cuenta desde que la pista recibe su sugerencia hasta su siguiente solicitud
    (una pista no pide otra revisión con la anterior pendiente). Cada pista recorre sus 3 clips
    en orden y vuelve a empezar.

    Args:
        cliente: cliente HTTP.
        cab: cabecera de autorización.
        args: argumentos (`intervalo_medio_s`, `duracion_s`, `semilla`).
        clips: clips por stem.
        pistas: orden fijo de stems por pista.
        rep: repetición (0, 1, 2); cambia la semilla de los intervalos.
        salida: archivo JSONL abierto.

    Returns:
        Todos los registros de la corrida.
    """
    nombres = ["P1", "P2", "P3", "P4"]
    matches = {p: await configurar_combate(cliente, cab, args, p, clips[pistas[p][0]]) for p in nombres}
    await asyncio.gather(*(cliente.get("/health") for _ in nombres))
    fin = time.monotonic() + args.duracion_s
    resultados: list[dict] = []

    async def pista(i: int, p: str) -> None:
        azar = random.Random(f"{args.semilla}-{rep}-{p}")
        k = 0
        while True:
            espera = azar.expovariate(1 / args.intervalo_medio_s)
            if time.monotonic() + espera >= fin:
                return
            await asyncio.sleep(espera)
            stem = pistas[p][k % len(pistas[p])]
            nombre = f"eB_n4_r{rep}_{p}_{k}_{stem}.mp4"
            r = await subir_clip(cliente, cab, matches[p], clips[stem], nombre)
            r.update(escenario="B", pistas=4, rep=rep, pista=p, intervalo_medio_s=args.intervalo_medio_s)
            resultados.append(r)
            salida.write(json.dumps(r, ensure_ascii=False) + "\n")
            salida.flush()
            k += 1

    await asyncio.gather(*(pista(i, p) for i, p in enumerate(nombres)))
    return resultados


async def main_async(args) -> None:
    """Orquesta login, medición de recursos y las corridas del escenario pedido.

    Args:
        args: argumentos de la línea de comandos.

    Raises:
        SystemExit: si falta la contraseña o el login falla.
    """
    password = os.environ.get("ESTRES_PASSWORD")
    if not password:
        sys.exit("falta la variable ESTRES_PASSWORD")
    clips, pistas = cargar_clips()
    limites = httpx.Limits(max_connections=16, max_keepalive_connections=16)
    async with httpx.AsyncClient(base_url=args.base_url, limits=limites, timeout=30.0) as cliente:
        cab = await login(cliente, args.usuario, password)
        medidor = Medidor(Path(args.recursos), args.fog_pid, args.contenedores.split(",") if args.contenedores else [],
                          args.redis_url)
        async with medidor:
            with open(args.salida, "a") as salida:
                if args.escenario == "A":
                    # Repeticiones por fuera y pistas por dentro: intercala 1..4 pistas para que la deriva
                    # térmica del equipo no se confunda con el efecto del número de pistas.
                    for rep in range(args.repeticiones):
                        for n in [int(x) for x in args.pistas.split(",")]:
                            medidor.etiqueta = f"A_n{n}_r{rep}"
                            res = await correr_rafaga(cliente, cab, args, clips, pistas, n, rep, salida)
                            tot = [r["total_s"] for r in res]
                            print(f"A n={n} rep={rep}: " + " ".join(f"{t:.1f}s" for t in tot), flush=True)
                            await asyncio.sleep(args.pausa_s)  # deja vaciar la cola entre corridas
                else:
                    if args.intervalo_medio_s is None:
                        sys.exit("el escenario B exige --intervalo-medio-s (lo decide el autor)")
                    for rep in range(args.repeticiones):
                        medidor.etiqueta = f"B_r{rep}"
                        res = await correr_sostenido(cliente, cab, args, clips, pistas, rep, salida)
                        tot = [r["total_s"] for r in res]
                        print(f"B rep={rep}: n={len(tot)} p50={percentil(tot, 50)} p95={percentil(tot, 95)}",
                              flush=True)
                        await asyncio.sleep(args.pausa_s)


def main() -> None:
    """Punto de entrada: lee los argumentos y corre la prueba."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("escenario", choices=["A", "B"])
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--usuario", required=True)
    ap.add_argument("--evento", required=True)
    ap.add_argument("--arbitro", required=True)
    ap.add_argument("--pistas", default="1,2,3,4", help="escenario A: lista de números de pistas")
    ap.add_argument("--repeticiones", type=int, default=3)
    ap.add_argument("--intervalo-medio-s", type=float, default=None, help="escenario B (lo decide el autor)")
    ap.add_argument("--duracion-s", type=float, default=600.0, help="escenario B")
    ap.add_argument("--semilla", default="estres01", help="semilla de los intervalos del escenario B")
    ap.add_argument("--pausa-s", type=float, default=20.0, help="pausa entre corridas")
    ap.add_argument("--salida", required=True, help="JSONL de resultados (se añade al final)")
    ap.add_argument("--recursos", required=True, help="CSV de recursos")
    ap.add_argument("--fog-pid", type=int, default=None)
    ap.add_argument("--contenedores", default="", help="nombres de contenedor separados por coma")
    ap.add_argument("--redis-url", default=None)
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
