"""Razonamiento de la sugerencia (F-035, F-008, CU-09; D-15 a D-17).

Dominio puro: sin infraestructura. Arma, con plantillas fijas, una o dos frases
cortas que ponen lado a lado tres cosas distintas y no las mezcla:

- la **atención del modelo** (en qué tramo del clip concentró su peso),
- los **eventos de pose** (inicio de extensión del brazo armado y del
  acercamiento, medidos sobre la pose cruda),
- el **criterio FIE de referencia** (el artículo que define la clase sugerida).

El BiLSTM no aplica reglas FIE: el texto nunca dice que el modelo decidió por
una regla. Si los eventos contradicen la sugerencia, el estado es
`discordante`.

Índice a frame: el índice 0 de la secuencia es el frame `frame_inicio`
(`lock_frame`) del clip, así que `frame_idx = frame_inicio + t`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

COLOR_POR_TIRADOR = {"A": "ROJ", "B": "VER"}

RESPALDADA = "respaldada"
DISCORDANTE = "discordante"
NO_CONCLUYENTE = "no_concluyente"
INSUFICIENTE = "insuficiente"
# No es un resultado del razonamiento: marca que el cálculo falló al clasificar.
NO_CALCULADO = "no_calculado"

TIPO_EXTENSION = "inicio_extension_brazo"
TIPO_DESPLAZAMIENTO = "inicio_desplazamiento"
TIPO_TOCADO = "tocado"
TIPO_FRAME_CLAVE = "frame_clave"
TIPO_CRITERIO = "criterio_fie"

# Por qué falta el evento de un tirador (solo cambia la segunda mitad del texto).
MOTIVO_DETECCION = "deteccion"
MOTIVO_SIN_SUBIDA = "sin_subida"


@dataclass(frozen=True)
class ParametrosExplicacion:
    """Parámetros U1 a U6 confirmados por el autor
    (prompts/EXPLICACION/00_README_EXPLICACION.md).

    Attributes:
        version: versión de la tabla de parámetros; se guarda con cada razonamiento.
        u1_angulo_min: ángulo de codo (grados) que debe alcanzar la subida.
        u1_incrementos_min: incrementos consecutivos mínimos de la subida.
        u2_umbral: velocidad relativa del CM (alturas de bbox por frame).
        u2_frames_sostenidos: frames seguidos sobre el umbral.
        u2_frames_censura: si el inicio cae antes de este índice, queda censurado.
        u3_margen_frames: diferencia mínima, en frames, para afirmar "X antes que Y".
        u4_articulos: artículo FIE por familia de clase (`Attack`, ...).
        u5_masa_atencion: fracción del peso de atención que contiene la ventana.
        u6_max_frases: máximo de frases.
        u6_max_caracteres: máximo de caracteres entre todas las frases.
    """

    version: str
    u1_angulo_min: float
    u1_incrementos_min: int
    u2_umbral: float
    u2_frames_sostenidos: int
    u2_frames_censura: int
    u3_margen_frames: int
    u4_articulos: Mapping[str, str]
    u5_masa_atencion: float
    u6_max_frases: int
    u6_max_caracteres: int


@dataclass(frozen=True)
class PoseEventos:
    """Pose cruda del clip, alineada con el índice 0 del .npz.

    Attributes:
        frame_inicio: frame del clip al que corresponde el índice 0 (`lock_frame`).
        angulo_codo: por tirador (`A`, `B`), ángulo del codo armado en grados
            sobre keypoints crudos (None si falta la detección). Es el mismo
            que sirve `GET /revisiones/{id}/pose`.
        cierre: velocidad relativa del CM hacia el rival por frame, de la
            corrección DEF-27; None si no se pudo calcular.
    """

    frame_inicio: int
    angulo_codo: Mapping[str, Sequence[float | None]]
    cierre: Sequence[float] | None = None


@dataclass(frozen=True)
class Evento:
    """Evento medido sobre la pose. `tirador` es None para el acercamiento
    mutuo. `t_ms` es relativo al tocado (negativo = antes)."""

    tipo: str
    tirador: str | None
    frame_idx: int
    t_ms: int
    censurado_inicio: bool = False


@dataclass(frozen=True)
class EventosDetectados:
    """Resultado de `detectar_eventos`.

    Attributes:
        fps: cuadros por segundo del clip.
        frame_tocado: frame del clip en que se simuló el tocado.
        extension: inicio de extensión del brazo por tirador; None si falta.
        faltantes: motivo por el que falta cada evento de `extension`.
        desplazamiento: acercamiento mutuo; no entra en las plantillas.
    """

    fps: float
    frame_tocado: int
    extension: Mapping[str, Evento | None]
    faltantes: Mapping[str, str] = field(default_factory=dict)
    desplazamiento: Evento | None = None


@dataclass(frozen=True)
class Ventana:
    """Ventana contigua más corta con la fracción U5 del peso de atención."""

    desde_frame: int
    hasta_frame: int
    desde_ms: int
    hasta_ms: int
    frame_clave: int
    t_clave_ms: int


@dataclass(frozen=True)
class Razonamiento:
    """Salida de `construir_razonamiento`."""

    estado: str
    frases: tuple[str, ...]
    articulo_fie: str | None
    eventos: EventosDetectados
    ventana: Ventana | None


def _t_ms(frame_idx: int, frame_tocado: int, fps: float) -> int:
    return round((frame_idx - frame_tocado) / fps * 1000)


def suavizar_mediana3(angulos: Sequence[float | None]) -> list[float | None]:
    """Mediana móvil de 3 frames sobre el ángulo crudo.

    Solo suaviza donde la ventana de 3 muestras está completa y es válida; en los
    extremos y junto a un hueco deja el valor crudo, de modo que no inventa
    muestras ni cubre huecos de detección. Los trazos de `/pose` siguen mostrando
    el ángulo crudo; esta serie solo alimenta la búsqueda de U1.

    Args:
        angulos: ángulo de codo crudo por frame (None si falta la detección).

    Returns:
        La serie suavizada, del mismo largo.
    """
    salida = list(angulos)
    for i in range(1, len(angulos) - 1):
        ventana = angulos[i - 1 : i + 2]
        if all(a is not None for a in ventana):
            salida[i] = sorted(ventana)[1]
    return salida


def _inicio_extension(
    angulos: Sequence[float | None], t_tocado: int, params: ParametrosExplicacion
) -> tuple[int | None, bool, str | None]:
    """Índice de inicio de la extensión del brazo armado (U1).

    Trabaja sobre la mediana móvil de 3 frames del ángulo crudo. Si en el primer
    frame válido (en o antes del tocado) el ángulo ya es `u1_angulo_min` o más,
    el inicio queda **censurado**: la extensión empezó antes del clip y el
    índice devuelto es el de ese primer frame. Si no, una subida es una cadena
    de muestras consecutivas válidas, cada una mayor que la anterior, con al
    menos `u1_incrementos_min` incrementos; cuenta si su cima alcanza
    `u1_angulo_min` en o antes del tocado y se toma la última. Si la muestra
    previa al inicio es nula, el inicio real podría ser anterior y no se afirma.

    Returns:
        (índice de inicio, censurado, None) o (None, False, motivo) con el
        motivo por el que falta.
    """
    suave = suavizar_mediana3(angulos)
    n = len(suave)
    primero = next((i for i, a in enumerate(suave) if a is not None), None)
    if (
        primero is not None
        and primero <= t_tocado
        and suave[primero] >= params.u1_angulo_min
    ):
        return primero, True, None
    mejor: tuple[int, int] | None = None
    i = 0
    while i < n:
        if suave[i] is None:
            i += 1
            continue
        j = i
        while j + 1 < n and suave[j + 1] is not None and suave[j + 1] > suave[j]:
            j += 1
        if (
            j - i >= params.u1_incrementos_min
            and suave[j] >= params.u1_angulo_min
            and j <= t_tocado
        ):
            mejor = (i, j)
        i = j + 1
    if mejor is not None:
        inicio = mejor[0]
        if inicio > 0 and suave[inicio - 1] is None:
            return None, False, MOTIVO_DETECCION
        return inicio, False, None
    hay_hueco = any(a is None for a in suave[: max(t_tocado, -1) + 1])
    return None, False, MOTIVO_DETECCION if hay_hueco else MOTIVO_SIN_SUBIDA


def _inicio_desplazamiento(
    cierre: Sequence[float], params: ParametrosExplicacion
) -> int | None:
    """Primer índice de la primera racha sostenida de frames sobre el umbral (U2)."""
    k = params.u2_frames_sostenidos
    for t in range(len(cierre) - k + 1):
        if all(c > params.u2_umbral for c in cierre[t : t + k]):
            return t
    return None


def detectar_eventos(
    pose: PoseEventos, fps: float, frame_tocado: int, params: ParametrosExplicacion
) -> EventosDetectados:
    """Detecta el inicio de extensión del brazo armado (U1) y el del acercamiento (U2).

    Usa el ángulo de codo **crudo** (con mediana móvil de 3 frames), no el
    interpolado que recibe el modelo: un hueco de detección da evento faltante en
    vez de un inicio rellenado. Un brazo ya extendido en el primer frame válido
    da un inicio censurado (`censurado_inicio`). El
    acercamiento sale de la velocidad relativa del CM (DEF-27), idéntica para A y
    B, así que es un solo evento sin tirador y no identifica quién se desplaza
    primero.

    Args:
        pose: ángulos de codo, velocidad relativa y frame del índice 0.
        fps: cuadros por segundo del clip.
        frame_tocado: frame del clip en que se simuló el tocado.
        params: parámetros U1 y U2.

    Returns:
        Los eventos en `frame_idx` y en `t_ms` relativo al tocado.
    """
    t_tocado = frame_tocado - pose.frame_inicio
    extension: dict[str, Evento | None] = {}
    faltantes: dict[str, str] = {}
    for tirador in ("A", "B"):
        idx, censurado, motivo = _inicio_extension(
            pose.angulo_codo[tirador], t_tocado, params
        )
        if idx is None:
            extension[tirador] = None
            faltantes[tirador] = motivo
        else:
            frame = pose.frame_inicio + idx
            extension[tirador] = Evento(
                TIPO_EXTENSION,
                tirador,
                frame,
                _t_ms(frame, frame_tocado, fps),
                censurado,
            )

    desplazamiento = None
    if pose.cierre is not None:
        idx = _inicio_desplazamiento(pose.cierre, params)
        if idx is not None:
            censurado = idx < params.u2_frames_censura
            frame = pose.frame_inicio + (0 if censurado else idx)
            desplazamiento = Evento(
                TIPO_DESPLAZAMIENTO,
                None,
                frame,
                _t_ms(frame, frame_tocado, fps),
                censurado,
            )
    return EventosDetectados(fps, frame_tocado, extension, faltantes, desplazamiento)


def ventana_atencion(
    atencion: Sequence[float] | None,
    mapa_t_a_frame: Sequence[int],
    fps: float,
    frame_tocado: int,
    params: ParametrosExplicacion,
) -> Ventana | None:
    """Ventana contigua más corta con la fracción U5 del peso de atención.

    Args:
        atencion: pesos por índice `t` (suman ~1), o None si Cloud no los envió.
        mapa_t_a_frame: `frame_idx` del clip de cada índice `t`.
        fps: cuadros por segundo del clip.
        frame_tocado: frame del tocado, para el tiempo relativo.
        params: parámetros (U5).

    Returns:
        La ventana y el frame de mayor peso, o None si no hay atención.

    Raises:
        ValueError: si `atencion` y `mapa_t_a_frame` no tienen el mismo largo.
    """
    if not atencion:
        return None
    if len(atencion) != len(mapa_t_a_frame):
        raise ValueError(
            f"atención de largo {len(atencion)} y mapa de largo {len(mapa_t_a_frame)}"
        )
    objetivo = params.u5_masa_atencion * sum(atencion) - 1e-9
    mejor: tuple[int, float, int, int] | None = None  # (largo, -masa, desde, hasta)
    for desde in range(len(atencion)):
        masa = 0.0
        for hasta in range(desde, len(atencion)):
            masa += atencion[hasta]
            if masa >= objetivo:
                candidato = (hasta - desde + 1, -masa, desde, hasta)
                if mejor is None or candidato < mejor:
                    mejor = candidato
                break
    _, _, desde, hasta = mejor
    clave = max(range(len(atencion)), key=lambda t: atencion[t])
    return Ventana(
        desde_frame=mapa_t_a_frame[desde],
        hasta_frame=mapa_t_a_frame[hasta],
        desde_ms=_t_ms(mapa_t_a_frame[desde], frame_tocado, fps),
        hasta_ms=_t_ms(mapa_t_a_frame[hasta], frame_tocado, fps),
        frame_clave=mapa_t_a_frame[clave],
        t_clave_ms=_t_ms(mapa_t_a_frame[clave], frame_tocado, fps),
    )


def _nombre(tirador: str) -> str:
    """Nombre del tirador en las frases: solo su color (`ROJ` o `VER`)."""
    return COLOR_POR_TIRADOR[tirador]


def _segundos(ms: int) -> str:
    return f"{abs(ms) / 1000:.1f}".replace(".", ",")


def _frase_ventana(ventana: Ventana) -> str:
    if ventana.hasta_ms <= 0:
        return (
            f"El modelo se concentró entre {_segundos(ventana.desde_ms)} y "
            f"{_segundos(ventana.hasta_ms)} s antes del tocado."
        )
    lado = "antes" if ventana.desde_ms < 0 else "después"
    desde = f"{_segundos(ventana.desde_ms)} s {lado}"
    return (
        f"El modelo se concentró entre {desde} y "
        f"{_segundos(ventana.hasta_ms)} s después del tocado."
    )


def _ajustar_largo(frases: list[str], params: ParametrosExplicacion) -> tuple[str, ...]:
    """Aplica U6: máximo de frases y de caracteres (se descarta la última frase
    antes de recortar la primera)."""
    frases = frases[: params.u6_max_frases]
    while len(frases) > 1 and len(" ".join(frases)) > params.u6_max_caracteres:
        frases = frases[:-1]
    if len(frases[0]) > params.u6_max_caracteres:
        frases = [frases[0][: params.u6_max_caracteres - 1].rstrip() + "…"]
    return tuple(frases)


def construir_razonamiento(
    clase: str,
    eventos: EventosDetectados,
    ventana: Ventana | None,
    params: ParametrosExplicacion,
) -> Razonamiento:
    """Arma el razonamiento con plantillas fijas (D-15).

    Args:
        clase: clase sugerida con el vocabulario del modelo (`AttackA`, ...).
        eventos: eventos medidos sobre la pose.
        ventana: ventana de atención, o None si no hay.
        params: parámetros U3, U4 y U6.

    Returns:
        El razonamiento con su estado y sus frases (a lo sumo U6).

    Raises:
        ValueError: si `clase` no es una clase del modelo.
    """
    familia, x = clase[:-1], clase[-1]
    if familia not in params.u4_articulos or x not in COLOR_POR_TIRADOR:
        raise ValueError(f"clase del modelo desconocida: {clase!r}")
    articulo = params.u4_articulos[familia]
    y = "B" if x == "A" else "A"

    def resultado(estado: str, *frases: str) -> Razonamiento:
        return Razonamiento(
            estado, _ajustar_largo(list(frases), params), articulo, eventos, ventana
        )

    faltantes = [t for t in ("A", "B") if eventos.extension[t] is None]
    if faltantes:
        z = faltantes[0]
        if eventos.faltantes.get(z) == MOTIVO_SIN_SUBIDA:
            return resultado(
                INSUFICIENTE,
                "Evidencia insuficiente: no se observa la extensión del brazo de "
                f"{_nombre(z)} "
                "en el tramo clave.",
            )
        return resultado(
            INSUFICIENTE,
            f"Evidencia insuficiente: falta la detección de {_nombre(z)} "
            "en el tramo clave.",
        )

    ea, eb = eventos.extension["A"], eventos.extension["B"]
    if ea.censurado_inicio and eb.censurado_inicio:
        frases = [
            "Ambos tiradores tenían el brazo extendido al comienzo del clip; "
            "la pose no desempata."
        ]
        if ventana is not None:
            frases.append(_frase_ventana(ventana))
        return resultado(NO_CONCLUYENTE, *frases)

    # Un inicio censurado precede a cualquier inicio observado; en ese caso no
    # hay diferencia que medir y no se aplica el margen U3.
    censurado = ea.censurado_inicio or eb.censurado_inicio
    if censurado:
        diferencia = 1 if ea.censurado_inicio else -1
    else:
        diferencia = eb.frame_idx - ea.frame_idx
    if not censurado and abs(diferencia) < params.u3_margen_frames:
        margen_ms = round(params.u3_margen_frames / eventos.fps * 1000)
        frases = [
            f"Ambos extendieron el brazo con menos de {margen_ms} ms de diferencia; "
            "la pose no desempata."
        ]
        if ventana is not None:
            frases.append(_frase_ventana(ventana))
        return resultado(NO_CONCLUYENTE, *frases)

    primero = "A" if diferencia > 0 else "B"
    delta_ms = round(abs(diferencia) / eventos.fps * 1000)
    ataque = familia == "Attack"
    if primero != (x if ataque else y):
        return resultado(
            DISCORDANTE,
            f"La pose muestra que {_nombre(primero)} extendió el brazo primero, "
            "lo que no respalda la sugerencia.",
            "Revise el video antes de decidir.",
        )

    # Con inicio censurado no hay diferencia en ms: se dice que ya estaba extendido.
    antes_y = (
        "ya tenía el brazo extendido al comienzo del clip"
        if censurado
        else f"extendió el brazo {delta_ms} ms antes"
    )
    if ataque:
        inicio_x = (
            f"{_nombre(x)} ya tenía el brazo extendido al comienzo del clip, "
            f"antes que {_nombre(y)}."
            if censurado
            else f"{_nombre(x)} inició la extensión del brazo {delta_ms} ms antes que "
            f"{_nombre(y)}."
        )
        return resultado(
            RESPALDADA,
            inicio_x,
            f"Criterio FIE {articulo}: la extensión del brazo precede al ataque.",
        )
    if familia == "Contrattack":
        return resultado(
            RESPALDADA,
            f"{_nombre(y)} {antes_y}; "
            f"la sugerencia es contraataque de {_nombre(x)}.",
            f"Criterio FIE {articulo}: golpe de detención sobre el ataque.",
        )
    return resultado(
        RESPALDADA,
        f"{_nombre(y)} {antes_y}; "
        f"la parada de {_nombre(x)} no es observable con la pose.",
        f"Criterio FIE {articulo}: la parada da derecho a la riposte.",
    )


@dataclass(frozen=True)
class FilaEvidencia:
    """Una fila de `sabre.evidencia`. `tirador` es 'A', 'B' o None."""

    tipo: str
    tirador: str | None = None
    frame_idx: int | None = None
    t_ms: int | None = None
    articulo_fie: str | None = None
    detalle: dict | None = None


def ventana_a_json(ventana: Ventana | None) -> dict | None:
    """Ventana de atención como JSON del `detalle` de `criterio_fie`."""
    if ventana is None:
        return None
    return {
        "desde_ms": ventana.desde_ms,
        "hasta_ms": ventana.hasta_ms,
        "desde_frame": ventana.desde_frame,
        "hasta_frame": ventana.hasta_frame,
    }


def filas_de_razonamiento(
    razonamiento: Razonamiento, params_version: str
) -> list[FilaEvidencia]:
    """Filas de `evidencia` de un razonamiento (D-16).

    Una fila por evento (`inicio_extension_brazo` por tirador, un solo
    `inicio_desplazamiento` sin tirador, `tocado`, `frame_clave` si hay
    atención) y una `criterio_fie` con el estado, las frases y la versión de
    parámetros.

    Args:
        razonamiento: resultado de `construir_razonamiento`.
        params_version: versión de la tabla de parámetros usada.

    Returns:
        Las filas, en el orden en que se escriben.
    """
    eventos = razonamiento.eventos
    filas = [FilaEvidencia(TIPO_TOCADO, frame_idx=eventos.frame_tocado, t_ms=0)]
    for tirador in ("A", "B"):
        e = eventos.extension[tirador]
        if e is not None:
            filas.append(
                FilaEvidencia(
                    e.tipo,
                    e.tirador,
                    e.frame_idx,
                    e.t_ms,
                    detalle={"censurado_inicio": e.censurado_inicio},
                )
            )
    d = eventos.desplazamiento
    if d is not None:
        filas.append(
            FilaEvidencia(
                d.tipo,
                None,
                d.frame_idx,
                d.t_ms,
                detalle={"censurado_inicio": d.censurado_inicio},
            )
        )
    if razonamiento.ventana is not None:
        v = razonamiento.ventana
        filas.append(FilaEvidencia(TIPO_FRAME_CLAVE, None, v.frame_clave, v.t_clave_ms))
    filas.append(
        FilaEvidencia(
            TIPO_CRITERIO,
            articulo_fie=razonamiento.articulo_fie,
            detalle={
                "estado": razonamiento.estado,
                "frases": list(razonamiento.frases),
                "ventana_atencion": ventana_a_json(razonamiento.ventana),
                "params_version": params_version,
            },
        )
    )
    return filas


def fila_no_calculado(params_version: str | None) -> FilaEvidencia:
    """Fila `criterio_fie` que deja constancia de que el cálculo falló.

    Distingue una revisión cuyo razonamiento falló (`no_calculado`) de una
    anterior al registro (`no_registrado`, sin filas).

    Args:
        params_version: versión de parámetros, o None si no se alcanzó a cargar.

    Returns:
        La fila a escribir en lugar de las del razonamiento.
    """
    return FilaEvidencia(
        TIPO_CRITERIO,
        detalle={
            "estado": NO_CALCULADO,
            "frases": [],
            "ventana_atencion": None,
            "params_version": params_version,
        },
    )
