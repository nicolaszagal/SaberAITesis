"""Lógica aislable de scripts/instalar_fog.sh (DEPLOY10): manifiestos, equivalencia y bloqueos.

Solo usa la biblioteca estándar para correr con el `python3` del sistema antes de que exista el
`.venv`. No toca la base ni Docker; eso lo hace el script de shell.

Uso desde el shell:
    python3 scripts/instalador.py manifiesto-crear <carpeta> [--excluir nombre ...]
    python3 scripts/instalador.py manifiesto-verificar <carpeta> [--nombre MODELO.sha256]
    python3 scripts/instalador.py base-vacia <conteos>          # "rev,clas,ver,aud"
    python3 scripts/instalador.py bloqueo --datos <dir> --commit <sha> --dispositivo <cpu|mps|cuda> [--remoto]
    python3 scripts/instalador.py fusionar <origen> <destino>     # sin pisar archivos existentes
    python3 scripts/instalador.py generar-env [--plantilla .env.example] [--destino .env] [--volumen-existente]
    python3 scripts/instalador.py lista-clips --dataset <dir> [--extra <dir>]
    python3 scripts/instalador.py estado-probar --datos <dir>
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import secrets
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

NOMBRE_MANIFIESTO = "MANIFEST.sha256"
PREFIJO_REPORTE = "equivalencia_"
# Archivos que el propio paquete escribe fuera del manifiesto.
_LINEA_MANIFIESTO = re.compile(r"^([0-9a-fA-F]{64}) [ *](.+)$")


def sha256_archivo(ruta: Path) -> str:
    """Calcula el SHA-256 de un archivo en bloques.

    Args:
        ruta: archivo a hashear.

    Returns:
        Hash en hexadecimal (64 caracteres).
    """
    digest = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def leer_manifiesto(ruta: Path) -> dict[str, str]:
    """Lee un manifiesto en formato `shasum -a 256` (`<hash>  <ruta relativa>`).

    Args:
        ruta: archivo del manifiesto.

    Returns:
        Ruta relativa -> hash.

    Raises:
        ValueError: si una línea no tiene el formato esperado o repite una ruta.
    """
    entradas: dict[str, str] = {}
    for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), start=1):
        if not linea.strip():
            continue
        m = _LINEA_MANIFIESTO.match(linea)
        if not m:
            raise ValueError(f"{ruta.name}:{n}: línea con formato inválido")
        relativa = m.group(2)
        if relativa in entradas:
            raise ValueError(f"{ruta.name}:{n}: ruta repetida {relativa}")
        entradas[relativa] = m.group(1).lower()
    return entradas


def crear_manifiesto(carpeta: Path, excluir: tuple[str, ...] = ()) -> int:
    """Escribe `MANIFEST.sha256` con todos los archivos de la carpeta (recursivo).

    Args:
        carpeta: raíz del paquete.
        excluir: nombres de archivo (relativos a la carpeta) que no entran al manifiesto.

    Returns:
        Cantidad de archivos registrados.
    """
    omitidos = {NOMBRE_MANIFIESTO, *excluir}
    lineas = []
    for archivo in sorted(p for p in carpeta.rglob("*") if p.is_file()):
        relativa = archivo.relative_to(carpeta).as_posix()
        if relativa in omitidos:
            continue
        lineas.append(f"{sha256_archivo(archivo)}  {relativa}")
    (carpeta / NOMBRE_MANIFIESTO).write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return len(lineas)


def verificar_manifiesto(carpeta: Path, nombre: str = NOMBRE_MANIFIESTO, estricto: bool = True) -> list[str]:
    """Compara los archivos de una carpeta con su manifiesto.

    Args:
        carpeta: raíz del paquete.
        nombre: archivo del manifiesto dentro de la carpeta.
        estricto: si es True, un archivo que no figura en el manifiesto también es un problema.

    Returns:
        Lista de problemas; vacía si todo coincide.
    """
    ruta = carpeta / nombre
    if not ruta.is_file():
        return [f"falta {nombre} en {carpeta}"]
    try:
        esperado = leer_manifiesto(ruta)
    except ValueError as exc:
        return [str(exc)]
    if not esperado:
        return [f"{nombre} está vacío"]
    problemas = []
    for relativa, hash_esperado in esperado.items():
        archivo = carpeta / relativa
        if not archivo.is_file():
            problemas.append(f"falta {relativa}")
        elif sha256_archivo(archivo) != hash_esperado:
            problemas.append(f"hash distinto: {relativa}")
    if estricto:
        for archivo in sorted(p for p in carpeta.rglob("*") if p.is_file()):
            relativa = archivo.relative_to(carpeta).as_posix()
            if relativa != nombre and relativa not in esperado:
                problemas.append(f"archivo fuera del manifiesto: {relativa}")
    return problemas


def fusionar_sin_pisar(origen: Path, destino: Path) -> dict[str, list[str]]:
    """Copia los archivos de `origen` a `destino` sin pisar ni borrar nada.

    Un archivo que ya existe con el mismo contenido se cuenta como igual; con contenido distinto
    se conserva el de `destino` y se informa como conflicto.

    Args:
        origen: carpeta con los archivos a restaurar (p. ej. el `storage` extraído del .tgz).
        destino: carpeta de destino (p. ej. `datos/storage`).

    Returns:
        Diccionario con las listas `copiados`, `iguales` y `conflictos` (rutas relativas).
    """
    resultado: dict[str, list[str]] = {"copiados": [], "iguales": [], "conflictos": []}
    for archivo in sorted(p for p in origen.rglob("*") if p.is_file()):
        relativa = archivo.relative_to(origen)
        meta = destino / relativa
        if meta.exists():
            clave = "iguales" if sha256_archivo(meta) == sha256_archivo(archivo) else "conflictos"
            resultado[clave].append(relativa.as_posix())
            continue
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_bytes(archivo.read_bytes())
        resultado["copiados"].append(relativa.as_posix())
    return resultado


def ruta_de_clip(clip: dict, dataset_dir: Path, extra_dir: Path | None = None) -> Path:
    """Ubica el archivo de un clip de referencia y verifica su hash.

    Args:
        clip: entrada de `clips_referencia.json`.
        dataset_dir: raíz del dataset (se usa `ruta_dataset` del clip).
        extra_dir: carpeta alternativa con `<stem>.mp4` (p. ej. `datos/referencia/clips`); tiene prioridad.

    Returns:
        Ruta del `.mp4`.

    Raises:
        FileNotFoundError: si el clip no está en ninguna ubicación.
        ValueError: si el hash del archivo no coincide con el registrado.
    """
    candidatas = [dataset_dir / clip["ruta_dataset"]]
    if extra_dir is not None:
        candidatas.insert(0, extra_dir / f"{clip['stem']}.mp4")
    for ruta in candidatas:
        if ruta.is_file():
            if sha256_archivo(ruta) != clip["sha256"]:
                raise ValueError(f"{ruta}: el hash no coincide con clips_referencia.json")
            return ruta
    raise FileNotFoundError(f"clip {clip['stem']} no encontrado (buscado en: {', '.join(map(str, candidatas))})")


def rutas_clips(clips_json: Path, dataset_dir: Path, extra_dir: Path | None = None) -> dict[str, Path]:
    """Ubica todos los clips de `clips_referencia.json` (ver `ruta_de_clip`).

    Args:
        clips_json: `scripts/datos/clips_referencia.json`.
        dataset_dir: raíz del dataset.
        extra_dir: carpeta alternativa con prioridad.

    Returns:
        stem -> ruta del `.mp4`.

    Raises:
        FileNotFoundError: si falta algún clip.
        ValueError: si algún hash no coincide.
    """
    clips = json.loads(clips_json.read_text(encoding="utf-8"))["clips"]
    return {c["stem"]: ruta_de_clip(c, dataset_dir, extra_dir) for c in clips}


def generar_env(plantilla: str, valores: dict[str, str]) -> str:
    """Rellena las claves vacías de `.env.example`; las claves ausentes o comentadas no se tocan.

    Args:
        plantilla: contenido de `.env.example`.
        valores: clave -> valor ya con sus comillas si hacen falta (p. ej. el hash entre comillas simples).

    Returns:
        El texto del `.env`.

    Raises:
        ValueError: si una clave de `valores` no aparece como `CLAVE=` en la plantilla.
    """
    lineas = plantilla.splitlines()
    for clave, valor in valores.items():
        for i, linea in enumerate(lineas):
            if linea.startswith(f"{clave}="):
                lineas[i] = f"{clave}={valor}"
                break
        else:
            raise ValueError(f"la plantilla no tiene la clave {clave}=")
    return "\n".join(lineas) + "\n"


def _cmd_generar_env(args) -> int:
    """Crea `.env` desde la plantilla: genera los aleatorios y pide el resto (nunca copia de otro equipo)."""
    from crear_hash_password import calcular_hash, validar_password  # requiere argon2 (el .venv)

    destino = Path(args.destino)
    if destino.exists():
        print(f"{destino} ya existe: no se toca.", file=sys.stderr)
        return 1
    if not sys.stdin.isatty():
        print("Se necesita una terminal interactiva para pedir la contraseña maestra.", file=sys.stderr)
        return 1
    if args.volumen_existente:
        print("Ya existe el volumen de PostgreSQL (sabre_pgdata): la contraseña debe ser la de esa base.")
        clave_pg = getpass.getpass("Contraseña de PostgreSQL de la base existente: ")
        if not clave_pg.isalnum():
            print("Use solo letras y números (se inserta en una URL).", file=sys.stderr)
            return 1
    else:
        clave_pg = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
    usuario = input("Usuario maestro de Fog (AUTH_USER): ").strip()
    respaldo = input("Carpeta de respaldos (RESPALDO_DIR, fuera de Docker y del repo): ").strip()
    if not usuario or not respaldo:
        print("AUTH_USER y RESPALDO_DIR son obligatorios.", file=sys.stderr)
        return 1
    password = getpass.getpass("Contraseña del usuario maestro (mínimo 16 caracteres): ")
    try:
        validar_password(password)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if getpass.getpass("Repetir contraseña: ") != password:
        print("Las contraseñas no coinciden.", file=sys.stderr)
        return 1
    texto = generar_env(Path(args.plantilla).read_text(encoding="utf-8"), {
        "POSTGRES_PASSWORD": clave_pg,
        "AUTH_USER": usuario,
        "AUTH_PASSWORD_HASH": f"'{calcular_hash(password)}'",
        "AUTH_JWT_SECRET": secrets.token_urlsafe(48),
        "RESPALDO_DIR": respaldo,
    })
    fd = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(texto)
    print(f"{destino} creado (permisos 600). Los secretos no se muestran.")
    return 0


def base_tiene_revisiones(conteos: str) -> bool:
    """Indica si la base ya tiene revisiones (lo que impide importar sobre ella).

    Args:
        conteos: salida de `SQL_CONTEOS` de lib_respaldo.sh: `revisiones,clasificaciones,veredictos,auditoría`.

    Returns:
        True si el conteo de revisiones es mayor que cero.

    Raises:
        ValueError: si el texto no tiene cuatro enteros separados por comas.
    """
    partes = conteos.strip().split(",")
    if len(partes) != 4 or not all(p.strip().isdigit() for p in partes):
        raise ValueError(f"conteos con formato inesperado: {conteos!r}")
    return int(partes[0]) > 0


def comparar_salidas(esperado: dict, obtenido: dict, cota: float | None) -> dict:
    """Compara la salida de `probar` con la referencia (clase y probabilidades por clip).

    Aprobado exige la misma clase en todos los clips y que la diferencia máxima de probabilidad
    (sobre las 6 clases de cada clip) no supere `cota`. El hash de keypoints es informativo: dos
    equipos pueden dar keypoints con diferencias de punto flotante sin cambiar la clase.

    Args:
        esperado: `clips` de referencia_salidas.json: stem -> {clase, probabilidades, keypoints_sha256}.
        obtenido: misma forma, de la corrida actual; un clip fallido trae {"error": "..."}.
        cota: diferencia máxima de probabilidad aceptada; None si el autor aún no la fijó.

    Returns:
        Diccionario con `aprobado`, `motivo`, `clases_iguales`, `total`, `diferencia_maxima`,
        `keypoints_iguales` y `clips` (detalle por clip).
    """
    detalle = {}
    iguales = 0
    keypoints_iguales = 0
    dif_max = 0.0
    sin_comparar = []
    for stem, ref in esperado.items():
        obt = obtenido.get(stem)
        if obt is None or "error" in obt:
            sin_comparar.append(stem)
            detalle[stem] = {"error": (obt or {}).get("error", "clip no procesado")}
            continue
        misma_clase = obt["clase"] == ref["clase"]
        dif = max(abs(obt["probabilidades"][c] - ref["probabilidades"][c]) for c in ref["probabilidades"])
        same_kp = obt.get("keypoints_sha256") == ref.get("keypoints_sha256")
        iguales += misma_clase
        keypoints_iguales += same_kp
        dif_max = max(dif_max, dif)
        detalle[stem] = {
            "clase_esperada": ref["clase"], "clase_obtenida": obt["clase"], "misma_clase": misma_clase,
            "diferencia_maxima": round(dif, 6), "keypoints_iguales": same_kp,
        }
    total = len(esperado)
    if cota is None:
        aprobado, motivo = False, "no hay cota de probabilidad confirmada (referencia_salidas.json: cota_probabilidad)"
    elif sin_comparar:
        aprobado, motivo = False, f"clips sin procesar: {', '.join(sin_comparar)}"
    elif iguales != total:
        aprobado, motivo = False, f"misma clase en {iguales}/{total}"
    elif dif_max > cota:
        aprobado, motivo = False, f"diferencia máxima {dif_max:.6f} supera la cota {cota}"
    else:
        aprobado, motivo = True, "equivalente a la referencia"
    return {
        "aprobado": aprobado, "motivo": motivo, "clases_iguales": iguales, "total": total,
        "diferencia_maxima": round(dif_max, 6), "keypoints_iguales": keypoints_iguales, "clips": detalle,
    }


def ultimo_reporte(datos: Path) -> tuple[Path, dict] | None:
    """Busca el reporte de equivalencia más reciente en `datos/evidencia`.

    Args:
        datos: carpeta `datos` del backend (contiene `evidencia/`).

    Returns:
        (ruta, contenido) o None si no hay ninguno legible.
    """
    carpeta = datos / "evidencia"
    for ruta in sorted(carpeta.glob(f"{PREFIJO_REPORTE}*.json"), key=lambda p: p.name, reverse=True):
        try:
            return ruta, json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return None


def evaluar_bloqueo(reporte: dict | None, commit: str, dispositivo: str, remoto: bool) -> tuple[bool, str]:
    """Decide si `fog_nativo.sh` puede arrancar.

    Reglas: en modo remoto se exige una `probar` aprobada de este commit; con un dispositivo distinto
    de `cpu` (también en local) se exige que esa `probar` se haya corrido con ese dispositivo.

    Args:
        reporte: último reporte de equivalencia del equipo, o None.
        commit: commit actual del backend.
        dispositivo: `FOG_DEVICE` vigente.
        remoto: True si el arranque es en modo remoto.

    Returns:
        (permitido, motivo).
    """
    if not remoto and dispositivo == "cpu":
        return True, "modo local con cpu: no exige equivalencia"
    if reporte is None:
        return False, "no hay ninguna prueba de equivalencia en este equipo (sh scripts/instalar_fog.sh probar)"
    if not reporte.get("aprobado"):
        return False, f"la última prueba de equivalencia no pasó ({reporte.get('motivo', 'sin motivo')})"
    if reporte.get("commit") != commit:
        return False, f"la última prueba es del commit {str(reporte.get('commit'))[:9]}, no del actual {commit[:9]}"
    if reporte.get("dispositivo") != dispositivo:
        return False, f"la última prueba usó FOG_DEVICE={reporte.get('dispositivo')}, no {dispositivo}"
    return True, "equivalencia aprobada para este commit y dispositivo"


def _cmd_bloqueo(args) -> int:
    hallado = ultimo_reporte(Path(args.datos))
    permitido, motivo = evaluar_bloqueo(hallado[1] if hallado else None, args.commit, args.dispositivo, args.remoto)
    print(motivo, file=sys.stdout if permitido else sys.stderr)
    return 0 if permitido else 1


def _cmd_estado_probar(args) -> int:
    hallado = ultimo_reporte(Path(args.datos))
    if hallado is None:
        print("sin pruebas de equivalencia en este equipo")
        return 0
    ruta, r = hallado
    estado = "APROBADA" if r.get("aprobado") else "NO APROBADA"
    print(f"{estado} · {r.get('fecha')} · commit {str(r.get('commit'))[:9]} · FOG_DEVICE={r.get('dispositivo')}"
          f" · {r.get('clases_iguales')}/{r.get('total')} clases · dif. máx. {r.get('diferencia_maxima')}"
          f" · {ruta.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos (ver docstring del módulo).

    Args:
        argv: argumentos; por defecto `sys.argv[1:]`.

    Returns:
        Código de salida.
    """
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("manifiesto-crear")
    c.add_argument("carpeta")
    c.add_argument("--excluir", action="append", default=[])
    v = sub.add_parser("manifiesto-verificar")
    v.add_argument("carpeta")
    v.add_argument("--nombre", default=NOMBRE_MANIFIESTO)
    v.add_argument("--no-estricto", action="store_true")
    b = sub.add_parser("base-vacia")
    b.add_argument("conteos")
    g = sub.add_parser("bloqueo")
    g.add_argument("--datos", required=True)
    g.add_argument("--commit", required=True)
    g.add_argument("--dispositivo", default="cpu")
    g.add_argument("--remoto", action="store_true")
    f = sub.add_parser("fusionar")
    f.add_argument("origen")
    f.add_argument("destino")
    ge = sub.add_parser("generar-env")
    ge.add_argument("--plantilla", default=".env.example")
    ge.add_argument("--destino", default=".env")
    ge.add_argument("--volumen-existente", action="store_true")
    lc = sub.add_parser("lista-clips")
    lc.add_argument("--dataset", required=True)
    lc.add_argument("--extra")
    lc.add_argument("--clips-json", default=str(Path(__file__).with_name("datos") / "clips_referencia.json"))
    e = sub.add_parser("estado-probar")
    e.add_argument("--datos", required=True)
    args = p.parse_args(argv)

    if args.cmd == "manifiesto-crear":
        n = crear_manifiesto(Path(args.carpeta), tuple(args.excluir))
        print(f"{n} archivos en {NOMBRE_MANIFIESTO}")
        return 0
    if args.cmd == "manifiesto-verificar":
        problemas = verificar_manifiesto(Path(args.carpeta), args.nombre, estricto=not args.no_estricto)
        for problema in problemas:
            print(f"  ✗ {problema}", file=sys.stderr)
        if not problemas:
            print(f"  {args.nombre}: OK")
        return 1 if problemas else 0
    if args.cmd == "base-vacia":
        # Código 0 = sin revisiones (se puede importar); 1 = tiene revisiones.
        return 1 if base_tiene_revisiones(args.conteos) else 0
    if args.cmd == "bloqueo":
        return _cmd_bloqueo(args)
    if args.cmd == "generar-env":
        return _cmd_generar_env(args)
    if args.cmd == "lista-clips":
        try:
            rutas = rutas_clips(Path(args.clips_json), Path(args.dataset), Path(args.extra) if args.extra else None)
        except (FileNotFoundError, ValueError) as exc:
            print(exc, file=sys.stderr)
            return 1
        for ruta in rutas.values():
            print(ruta)
        return 0
    if args.cmd == "fusionar":
        r = fusionar_sin_pisar(Path(args.origen), Path(args.destino))
        print(f"  copiados {len(r['copiados'])}, ya estaban {len(r['iguales'])}, conflictos {len(r['conflictos'])}")
        for c in r["conflictos"]:
            print(f"  ! conflicto (se conserva el existente): {c}", file=sys.stderr)
        return 1 if r["conflictos"] else 0
    return _cmd_estado_probar(args)


def ahora_utc() -> str:
    """Fecha y hora UTC en ISO 8601 con segundos (sello de los reportes).

    Returns:
        Texto como `2026-11-18T20:41:20Z`.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    sys.exit(main())
