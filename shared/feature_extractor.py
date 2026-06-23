"""
feature_extractor.py — matemática biomecánica compartida por los
adaptadores de Fog (infrastructure/pose/, infrastructure/features/).

Copia literal de las funciones puras de `dataset/05_extract_features.py`
(`extract_person_features`, `try_lock_ids`, `interpolate_sequence`,
`bbox_area`, `bbox_center_x`, `angle_three_points`, `valid_pt`) — no se
reimplementa de memoria, se verificó por lectura directa del archivo.

Diferencia respecto al original: aquí se devuelven los 96 valores por
persona completos (incluye el bloque biomecánico de Fase B, offset 91:96),
porque el pipeline desplegado ahora es `lstm_4class` (192 features, 4
clases, con luz Favero) — ver PLAN_ARQUITECTURA_DDD.md. El truncamiento a
91/persona que tenía la versión anterior (pipeline de 182/6 clases) se
eliminó junto con ese pipeline, que quedó descartado.

Este módulo NO sabe nada de ultralytics ni de torch: solo opera sobre los
arrays planos (keypoints xy/conf, box xyxy) que entrega PoseEstimatorPort.
Eso es lo que permite que infrastructure/pose/ sea intercambiable sin
tocar esta matemática.
"""

import math

import numpy as np

# ──────────────────────────────────────────────
# Constantes de keypoints COCO (idénticas a 05_extract_features.py)
# ──────────────────────────────────────────────
N_KPT = 17

L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16

WEAPON_KPT = {
    "right": {"shoulder": 6, "elbow": 8, "wrist": 10},
    "left":  {"shoulder": 5, "elbow": 7, "wrist": 9},
}

CONF_THR = 0.3

FEAT_POS    = N_KPT * 3   # 51
FEAT_VEL    = N_KPT * 2   # 34
FEAT_STEP   = 4
FEAT_WEAPON = 2
FEAT_BIO    = 5

FEAT_PER_PERSON = FEAT_POS + FEAT_VEL + FEAT_STEP + FEAT_WEAPON + FEAT_BIO  # 96
TOTAL_FEATURES  = FEAT_PER_PERSON * 2                                       # 192

ANOMALY_THR = 0.5


# ──────────────────────────────────────────────
# Interpolación de keypoints anómalos (copia literal)
# ──────────────────────────────────────────────

def interpolate_sequence(sequence):
    """
    Recibe sequence: lista de arrays (96,) para UN tirador.
    Detecta frames con saltos anómalos en la posición relativa (x,y) y los
    reemplaza por interpolación lineal entre el último frame válido y el
    siguiente frame válido.
    """
    T = len(sequence)
    if T < 3:
        return sequence, 0

    seq = [f.copy() for f in sequence]

    def pos_xy(feat):
        return np.array([feat[k * 3 + d] for k in range(N_KPT) for d in range(2)])

    corrected = 0

    for t in range(1, T - 1):
        xy_prev = pos_xy(seq[t - 1])
        xy_curr = pos_xy(seq[t])

        mask = (xy_prev != 0) & (xy_curr != 0)
        if mask.sum() == 0:
            continue

        max_jump = np.abs(xy_curr[mask] - xy_prev[mask]).max()

        if max_jump > ANOMALY_THR:
            next_valid = None
            for t2 in range(t + 1, T):
                xy_next = pos_xy(seq[t2])
                jump_next = np.abs(xy_next[mask] - xy_prev[mask]).max()
                if jump_next <= ANOMALY_THR:
                    next_valid = t2
                    break

            if next_valid is not None:
                alpha = (t - (t - 1)) / (next_valid - (t - 1))
                seq[t] = ((1 - alpha) * seq[t - 1] + alpha * seq[next_valid]).astype(np.float32)
            else:
                seq[t] = seq[t - 1].copy()

            corrected += 1

    return seq, corrected


# ──────────────────────────────────────────────
# Geometría (copia literal)
# ──────────────────────────────────────────────

def angle_three_points(a, b, c):
    if a[0] == 0 or b[0] == 0 or c[0] == 0:
        return 0.0
    ba = np.array(a) - np.array(b)
    bc = np.array(c) - np.array(b)
    cos_angle = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8)
    return float(np.arccos(np.clip(cos_angle, -1.0, 1.0)))


def valid_pt(pts, confs, idx):
    if confs[idx] >= CONF_THR and pts[idx][0] > 0:
        return float(pts[idx][0]), float(pts[idx][1])
    return 0.0, 0.0


# ──────────────────────────────────────────────
# Extracción de features por persona (copia literal de extract_person_features,
# operando sobre arrays planos en vez de sobre `r.boxes[box_idx]`/`r.keypoints[box_idx]`)
# ──────────────────────────────────────────────

def extract_person_features(detected, pts, confs, box_xyxy, frame_w, frame_h, prev_rel,
                             prev_dist_ankles, prev_weapon_ext, weapon_side="right",
                             prev_cm_x=0.0, prev_cm_y=0.0, prev_elbow_angle=0.0):
    """
    Extrae el vector de 96 features para una persona en un frame.

    Args:
        detected: False si no se asignó box a esta persona en este frame
                  (equivalente a box_idx is None en el original).
        pts:      (17, 2) keypoints xy absolutos (0 si no detectado).
        confs:    (17,) confianzas.
        box_xyxy: (4,) x1,y1,x2,y2 absolutos.
    """
    feat            = np.zeros(FEAT_PER_PERSON, dtype=np.float32)
    new_rel         = np.zeros(FEAT_VEL, dtype=np.float32)
    new_dist_ankles = 0.0
    new_weapon_ext  = 0.0

    if not detected:
        return feat, new_rel, new_dist_ankles, new_weapon_ext, 0.0, 0.0, 0.0

    x1, y1, x2, y2 = box_xyxy
    bbox_h = float(y2 - y1) if (y2 - y1) > 0 else frame_h

    lhx, lhy = valid_pt(pts, confs, L_HIP)
    rhx, rhy = valid_pt(pts, confs, R_HIP)

    if lhx > 0 and rhx > 0:
        cm_x = (lhx + rhx) / 2
        cm_y = (lhy + rhy) / 2
    elif lhx > 0:
        cm_x, cm_y = lhx, lhy
    elif rhx > 0:
        cm_x, cm_y = rhx, rhy
    else:
        cm_x = float((x1 + x2) / 2)
        cm_y = float((y1 + y2) / 2)

    # Posición relativa al CM (51 valores)
    offset = 0
    for k in range(N_KPT):
        c = float(confs[k])
        if c >= CONF_THR and pts[k][0] > 0:
            dx = (pts[k][0] - cm_x) / bbox_h
            dy = (pts[k][1] - cm_y) / bbox_h
            feat[offset]     = dx
            feat[offset + 1] = dy
            feat[offset + 2] = c
            new_rel[k * 2]     = dx
            new_rel[k * 2 + 1] = dy
        offset += 3

    # Velocidad articular (34 valores)
    vel_offset = FEAT_POS
    for k in range(N_KPT):
        feat[vel_offset + k * 2]     = new_rel[k * 2]     - prev_rel[k * 2]
        feat[vel_offset + k * 2 + 1] = new_rel[k * 2 + 1] - prev_rel[k * 2 + 1]

    # Pasos e impulso (4 valores)
    step_offset = FEAT_POS + FEAT_VEL

    lax, lay = valid_pt(pts, confs, L_ANKLE)
    rax, ray = valid_pt(pts, confs, R_ANKLE)

    if lax > 0 and rax > 0:
        dist_ankles = math.hypot(rax - lax, ray - lay) / bbox_h
    else:
        dist_ankles = 0.0
    new_dist_ankles = dist_ankles

    lkx, lky = valid_pt(pts, confs, L_KNEE)
    rkx, rky = valid_pt(pts, confs, R_KNEE)

    ang_l = angle_three_points((lhx, lhy), (lkx, lky), (lax, lay))
    ang_r = angle_three_points((rhx, rhy), (rkx, rky), (rax, ray))
    vel_dist = dist_ankles - prev_dist_ankles

    feat[step_offset]     = dist_ankles
    feat[step_offset + 1] = ang_l
    feat[step_offset + 2] = ang_r
    feat[step_offset + 3] = vel_dist

    # Extensión del brazo armado (2 valores)
    weapon_offset = FEAT_POS + FEAT_VEL + FEAT_STEP
    wkpts = WEAPON_KPT[weapon_side]
    shx, shy = valid_pt(pts, confs, wkpts["shoulder"])
    elx, ely = valid_pt(pts, confs, wkpts["elbow"])
    wrx, wry = valid_pt(pts, confs, wkpts["wrist"])

    if shx > 0 and wrx > 0:
        weapon_ext = math.hypot(wrx - shx, wry - shy) / bbox_h
    else:
        weapon_ext = 0.0
    new_weapon_ext = weapon_ext

    feat[weapon_offset]     = weapon_ext
    feat[weapon_offset + 1] = weapon_ext - prev_weapon_ext

    # Bloque biomecánico Fase B (5 valores): velocidad del CM, rapidez del
    # cuerpo, ángulo del codo y su velocidad. Usado por el pipeline
    # lstm_4class (a diferencia del pipeline viejo, que los descartaba).
    bio_offset = FEAT_PER_PERSON - FEAT_BIO
    if prev_cm_x != 0.0:
        cm_vel_x = (cm_x - prev_cm_x) / bbox_h
        cm_vel_y = (cm_y - prev_cm_y) / bbox_h
    else:
        cm_vel_x = 0.0
        cm_vel_y = 0.0
    body_speed = math.hypot(cm_vel_x, cm_vel_y)
    elbow_angle = angle_three_points((shx, shy), (elx, ely), (wrx, wry))
    vel_elbow   = elbow_angle - prev_elbow_angle

    feat[bio_offset]     = cm_vel_x
    feat[bio_offset + 1] = cm_vel_y
    feat[bio_offset + 2] = body_speed
    feat[bio_offset + 3] = elbow_angle
    feat[bio_offset + 4] = vel_elbow

    return (feat, new_rel, new_dist_ankles, new_weapon_ext,
            cm_x, cm_y, elbow_angle)


# ──────────────────────────────────────────────
# Tracking lock (copia literal, operando sobre arrays de boxes/ids planos)
# ──────────────────────────────────────────────

def bbox_area(box_xyxy):
    x1, y1, x2, y2 = box_xyxy
    return float((x2 - x1) * (y2 - y1))


def bbox_center_x(box_xyxy):
    x1, _, x2, _ = box_xyxy
    return float((x1 + x2) / 2)


def try_lock_ids(boxes_xyxy, ids):
    """
    Args:
        boxes_xyxy: lista/array de (4,) por box detectado en el frame.
        ids:        lista de track ids (int o None) paralela a boxes_xyxy.
    """
    if ids is None or len(ids) < 2:
        return None, None
    n = len(boxes_xyxy)
    valid = [i for i in range(n) if ids[i] is not None]
    if len(valid) < 2:
        return None, None
    top2 = sorted(valid, key=lambda i: bbox_area(boxes_xyxy[i]), reverse=True)[:2]
    cx0 = bbox_center_x(boxes_xyxy[top2[0]])
    cx1 = bbox_center_x(boxes_xyxy[top2[1]])
    if cx0 <= cx1:
        return int(ids[top2[0]]), int(ids[top2[1]])
    else:
        return int(ids[top2[1]]), int(ids[top2[0]])
