"""Razonamiento de la sugerencia (F-035, CU-09, D-15): dominio puro con
secuencias sintéticas. No hay base, ni Redis, ni modelo."""

from __future__ import annotations

from dataclasses import replace

import pytest

from fog.domain.razonamiento import (
    DISCORDANTE,
    INSUFICIENTE,
    NO_CONCLUYENTE,
    RESPALDADA,
    PoseEventos,
    construir_razonamiento,
    detectar_eventos,
    filas_de_razonamiento,
    ventana_atencion,
)
from fog.infrastructure.explicacion.parametros_json import ParametrosExplicacionJson

PARAMS = ParametrosExplicacionJson().cargar()
FPS = 30.0
CLASES = ["AttackA", "AttackB", "ContrattackA", "ContrattackB", "RiposteA", "RiposteB"]
PROHIBIDO = ("el modelo decidió", "porque el modelo", "el modelo aplicó", "el modelo aplica")


def serie(n: int = 30, sube_en: int | None = 5, base: float = 90.0, paso: float = 15.0):
    """Ángulos planos en `base` y, desde `sube_en`, cuatro incrementos hasta 150°."""
    angulos: list[float | None] = [base] * n
    if sube_en is not None:
        for k in range(1, 5):
            for t in range(sube_en + k, n):
                angulos[t] = base + paso * k
    return angulos


def eventos(a_sube, b_sube, *, frame_inicio=0, frame_tocado=20, a=None, b=None, cierre=None):
    pose = PoseEventos(
        frame_inicio=frame_inicio,
        angulo_codo={"A": a if a is not None else serie(sube_en=a_sube),
                     "B": b if b is not None else serie(sube_en=b_sube)},
        cierre=cierre,
    )
    return detectar_eventos(pose, FPS, frame_tocado, PARAMS)


def test_u1_inicio_es_el_primer_frame_de_la_ultima_subida_que_llega_a_135():
    ev = eventos(5, 9)
    assert (ev.extension["A"].frame_idx, ev.extension["B"].frame_idx) == (5, 9)
    # t_ms relativo al tocado (frame 20): negativo = antes.
    assert ev.extension["A"].t_ms == round((5 - 20) / FPS * 1000) == -500


def test_u1_una_subida_que_no_llega_a_135_no_cuenta():
    baja = [90.0 + 5 * k for k in range(5)] + [110.0] * 25  # sube hasta 110°
    assert eventos(None, 5, a=baja).extension["A"] is None


def test_u1_exige_tres_incrementos_consecutivos():
    corta = [90.0, 120.0, 150.0] + [150.0] * 27  # solo dos incrementos
    assert eventos(None, 5, a=corta).extension["A"] is None


def test_u1_la_cima_debe_estar_antes_del_tocado():
    assert eventos(18, 5, frame_tocado=20).extension["A"] is None  # cima en el 22


def test_u1_toma_la_ultima_subida_valida():
    a = serie(sube_en=3)
    a[12:17] = [100.0, 110.0, 120.0, 130.0, 140.0]  # segunda subida que llega a 140°
    a[17:] = [90.0] * (len(a) - 17)
    assert eventos(None, 5, a=a).extension["A"].frame_idx == 12


def test_u1_sobre_el_angulo_crudo_un_hueco_da_evento_faltante_no_inicio_rellenado():
    a = serie(sube_en=5)
    a[7] = None  # hueco en plena subida; el interpolado del modelo sí tendría valor
    ev = eventos(None, 9, a=a)
    assert ev.extension["A"] is None
    assert ev.faltantes["A"] == "deteccion"


def test_u1_hueco_justo_antes_del_inicio_no_afirma_el_inicio():
    a = serie(sube_en=5)
    a[4] = None
    assert eventos(None, 9, a=a).extension["A"] is None


def test_u2_arrancar_sobre_el_umbral_es_censurado_y_marca_el_primer_frame():
    cierre = [0.02] * 30
    ev = eventos(5, 9, frame_inicio=7, cierre=cierre).desplazamiento
    assert ev.censurado_inicio is True
    assert (ev.frame_idx, ev.tirador) == (7, None)


def test_u2_cruce_en_el_frame_10_es_inicio_en_el_frame_10():
    cierre = [0.0] * 10 + [0.02] * 20
    ev = eventos(5, 9, cierre=cierre).desplazamiento
    assert (ev.censurado_inicio, ev.frame_idx) == (False, 10)


def test_u2_con_lock_tardio_el_frame_es_del_clip():
    cierre = [0.0] * 10 + [0.02] * 20
    ev = eventos(5, 9, frame_inicio=7, frame_tocado=30, cierre=cierre).desplazamiento
    assert ev.frame_idx == 17
    assert ev.t_ms == round((17 - 30) / FPS * 1000)


@pytest.mark.parametrize("cierre", [[0.0] * 8 + [0.02, 0.02] + [0.0] * 20, [0.010] * 30, None])
def test_u2_sin_racha_de_tres_frames_sobre_el_umbral_no_hay_evento(cierre):
    assert eventos(5, 9, cierre=cierre).desplazamiento is None


def test_u2_el_umbral_es_estricto_y_dos_frames_no_alcanzan_pero_tres_si():
    assert eventos(5, 9, cierre=[0.0] * 6 + [0.0101] * 3 + [0.0] * 21).desplazamiento.frame_idx == 6


@pytest.mark.parametrize(
    "clase, a_sube, b_sube, estado",
    [
        ("AttackA", 5, 9, RESPALDADA),          # X extiende primero
        ("AttackA", 9, 5, DISCORDANTE),
        ("AttackB", 9, 5, RESPALDADA),
        ("AttackB", 5, 9, DISCORDANTE),
        ("ContrattackA", 9, 5, RESPALDADA),     # el rival extiende primero
        ("ContrattackA", 5, 9, DISCORDANTE),
        ("ContrattackB", 5, 9, RESPALDADA),
        ("ContrattackB", 9, 5, DISCORDANTE),
        ("RiposteA", 9, 5, RESPALDADA),
        ("RiposteA", 5, 9, DISCORDANTE),
        ("RiposteB", 5, 9, RESPALDADA),
        ("RiposteB", 9, 5, DISCORDANTE),
        ("AttackA", 6, 6, NO_CONCLUYENTE),
        ("RiposteB", 6, 6, NO_CONCLUYENTE),
    ],
)
def test_las_seis_clases_y_sus_estados(clase, a_sube, b_sube, estado):
    r = construir_razonamiento(clase, eventos(a_sube, b_sube), None, PARAMS)
    assert r.estado == estado
    assert r.articulo_fie == PARAMS.u4_articulos[clase[:-1]]


def test_plantillas_de_las_clases_respaldadas():
    ataque = construir_razonamiento("AttackA", eventos(5, 9), None, PARAMS)
    assert ataque.frases == (
        "A · ROJ inició la extensión del brazo 133 ms antes que B · VER.",
        "Criterio FIE t.101.2-4: la extensión del brazo precede al ataque.",
    )
    contra = construir_razonamiento("ContrattackB", eventos(5, 9), None, PARAMS)
    assert contra.frases == (
        "A · ROJ extendió el brazo 133 ms antes; la sugerencia es contraataque de B · VER.",
        "Criterio FIE t.106: golpe de detención sobre el ataque.",
    )
    riposte = construir_razonamiento("RiposteB", eventos(5, 9), None, PARAMS)
    assert riposte.frases == (
        "A · ROJ extendió el brazo 133 ms antes; la parada de B · VER no es observable con la pose.",
        "Criterio FIE t.105: la parada da derecho a la riposte.",
    )


def test_plantilla_discordante_nombra_a_quien_extendio_primero():
    r = construir_razonamiento("AttackA", eventos(9, 5), None, PARAMS)
    assert r.frases == (
        "La pose muestra que B · VER extendió el brazo primero, lo que no respalda la sugerencia.",
        "Revise el video antes de decidir.",
    )


def test_u3_margen_en_el_borde_exacto():
    # Con U3 = 1 frame: la diferencia de 0 no desempata y la de 1 sí.
    assert construir_razonamiento("AttackA", eventos(6, 6), None, PARAMS).estado == NO_CONCLUYENTE
    assert construir_razonamiento("AttackA", eventos(6, 7), None, PARAMS).estado == RESPALDADA
    # Con U3 = 2: 1 frame no alcanza, 2 sí.
    p2 = replace(PARAMS, u3_margen_frames=2)
    assert construir_razonamiento("AttackA", eventos(6, 7), None, p2).estado == NO_CONCLUYENTE
    assert construir_razonamiento("AttackA", eventos(6, 8), None, p2).estado == RESPALDADA
    r = construir_razonamiento("AttackA", eventos(6, 7), None, p2)
    assert r.frases[0].startswith("Ambos extendieron el brazo con menos de 67 ms de diferencia")


def test_no_concluyente_con_ventana_dice_donde_se_concentro_el_modelo():
    atencion = [0.0] * 30
    atencion[6:14] = [0.05, 0.05, 0.2, 0.2, 0.2, 0.2, 0.05, 0.05]
    v = ventana_atencion(atencion, list(range(30)), FPS, 20, PARAMS)
    assert (v.desde_frame, v.hasta_frame) == (8, 10)
    r = construir_razonamiento("AttackA", eventos(6, 6), v, PARAMS)
    assert r.frases[1] == "El modelo se concentró entre 0,4 y 0,3 s antes del tocado."


def test_no_concluyente_sin_atencion_deja_una_sola_frase():
    r = construir_razonamiento("AttackA", eventos(6, 6), None, PARAMS)
    assert len(r.frases) == 1


def test_insuficiente_por_deteccion_faltante_nombra_al_tirador():
    b = serie(sube_en=9)
    b[8] = None
    r = construir_razonamiento("AttackA", eventos(5, None, b=b), None, PARAMS)
    assert r.estado == INSUFICIENTE
    assert r.frases == ("Evidencia insuficiente: falta la detección de B · VER en el tramo clave.",)


def test_insuficiente_sin_subida_y_sin_huecos_no_dice_que_falta_la_deteccion():
    r = construir_razonamiento("AttackA", eventos(5, None), None, PARAMS)
    assert r.estado == INSUFICIENTE
    assert "falta la detección" not in r.frases[0]
    assert r.frases[0].startswith("Evidencia insuficiente: no se observa la extensión del brazo de B · VER")


def test_clase_desconocida_falla():
    with pytest.raises(ValueError):
        construir_razonamiento("AtaqueA", eventos(5, 9), None, PARAMS)


def _todos_los_razonamientos():
    ventana = ventana_atencion([0.05] * 20, list(range(20)), FPS, 20, PARAMS)
    escenarios = [eventos(5, 9), eventos(9, 5), eventos(6, 6), eventos(5, None)]
    for clase in CLASES:
        for ev in escenarios:
            for v in (None, ventana):
                yield construir_razonamiento(clase, ev, v, PARAMS)


def test_ninguna_frase_supera_u6_ni_dice_que_el_modelo_decidio():
    vistos = set()
    for r in _todos_los_razonamientos():
        vistos.add(r.estado)
        assert 1 <= len(r.frases) <= PARAMS.u6_max_frases
        assert len(" ".join(r.frases)) <= PARAMS.u6_max_caracteres
        texto = " ".join(r.frases).lower()
        assert not any(p in texto for p in PROHIBIDO)
        assert "bilstm" not in texto
    assert vistos == {RESPALDADA, DISCORDANTE, NO_CONCLUYENTE, INSUFICIENTE}


def test_u6_recorta_primero_la_segunda_frase_y_despues_la_primera():
    ajustado = replace(PARAMS, u6_max_caracteres=70)
    r = construir_razonamiento("AttackA", eventos(5, 9), None, ajustado)
    assert r.frases == ("A · ROJ inició la extensión del brazo 133 ms antes que B · VER.",)
    minimo = replace(PARAMS, u6_max_caracteres=30)
    r = construir_razonamiento("AttackA", eventos(5, 9), None, minimo)
    assert len(r.frases) == 1 and len(r.frases[0]) <= 30 and r.frases[0].endswith("…")
    una = replace(PARAMS, u6_max_frases=1)
    assert len(construir_razonamiento("AttackA", eventos(5, 9), None, una).frases) == 1


def test_ventana_es_la_contigua_mas_corta_con_la_mitad_del_peso():
    atencion = [0.02] * 10 + [0.30, 0.30] + [0.02] * 10
    atencion = [w / sum(atencion) for w in atencion]
    v = ventana_atencion(atencion, list(range(100, 100 + len(atencion))), FPS, 110, PARAMS)
    assert (v.desde_frame, v.hasta_frame) == (110, 111)
    assert v.frame_clave == 110  # empate: el primero
    assert v.desde_ms == 0


def test_ventana_con_lock_tardio_cae_en_el_mismo_frame_del_clip_que_el_evento():
    lock = 7
    a = serie(sube_en=5)
    ev = eventos(None, 9, frame_inicio=lock, frame_tocado=30, a=a)
    atencion = [0.0] * 30
    atencion[5] = 1.0  # el modelo mira el índice 5, donde A empieza a extender
    v = ventana_atencion(atencion, [lock + t for t in range(30)], FPS, 30, PARAMS)
    assert v.frame_clave == ev.extension["A"].frame_idx == lock + 5
    assert v.t_clave_ms == ev.extension["A"].t_ms


def test_ventana_sin_atencion_es_nula_y_largos_distintos_fallan():
    assert ventana_atencion(None, [0, 1], FPS, 1, PARAMS) is None
    with pytest.raises(ValueError):
        ventana_atencion([0.5, 0.5], [0, 1, 2], FPS, 1, PARAMS)


def test_filas_de_evidencia_una_por_evento_y_un_criterio():
    ev = eventos(5, 9, cierre=[0.0] * 10 + [0.02] * 20)
    v = ventana_atencion([0.05] * 20, list(range(20)), FPS, 20, PARAMS)
    r = construir_razonamiento("AttackA", ev, v, PARAMS)

    filas = filas_de_razonamiento(r, PARAMS.version)

    assert [(f.tipo, f.tirador) for f in filas] == [
        ("tocado", None), ("inicio_extension_brazo", "A"), ("inicio_extension_brazo", "B"),
        ("inicio_desplazamiento", None), ("frame_clave", None), ("criterio_fie", None),
    ]
    criterio = filas[-1]
    assert criterio.articulo_fie == "t.101.2-4"
    assert criterio.detalle["estado"] == RESPALDADA
    assert criterio.detalle["params_version"] == "1"
    assert criterio.detalle["frases"] == list(r.frases)
    assert filas[3].detalle == {"censurado_inicio": False}
