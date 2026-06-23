"""YoloV8PoseAdapter — implementación de PoseEstimatorPort vía ultralytics
YOLO. Tracker: BoT-SORT (botsort.yaml). NO ByteTrack.

Nota de discrepancia (encontrada 2026-06-22, no comunicada antes a
Nicolas): la versión anterior de este archivo y CONTRATO_API.md sección 7
decían "ByteTrack", asumiendo que es el tracker default de ultralytics
.track(). Verificado leyendo directamente
ultralytics/cfg/default.yaml (línea `tracker: botsort.yaml`) en la versión
instalada en backend/.venv (ultralytics==8.4.75): el default real es
BoT-SORT, no ByteTrack. Esto NO se puede resolver desde este repo:
dataset/05_extract_features.py (el script que generó el dataset de
entrenamiento) también llama a model.track(frame, persist=True) sin
tracker= explícito, así que corrió bajo el default de la versión de
ultralytics que estuviera instalada en ESE momento, que no necesariamente
es 8.4.75 (no hay pin de versión registrado en el repo para esa corrida).
Si esa versión también default-eaba a botsort, la documentación estaba
mal pero no hay mismatch real de comportamiento; si default-eaba a
bytetrack, hay un mismatch silencioso entre entrenamiento e inferencia
que ya existía antes de este cambio (este refactor no lo introduce ni lo
corrige, solo lo hace explícito). Pendiente de validar con Nicolas.

Refactor fiel del loop de detección+tracking que antes vivía embebido en
la clase FeatureExtractor de shared/feature_extractor.py (ahora eliminada
de ese módulo): separa "trackear personas y resolver IDs A/B" de "calcular
features biomecánicas", para que cada una sea un puerto independiente y
migrar el detector (p.ej. a MediaPipe) no toque feature_extractor ni
application/.

Por qué no usar model.track(..., persist=True) directamente (decisión de
Nicolas, 2026-06-22, de arreglar esto ahora en vez de diferirlo): persist=
True reutiliza un único tracker interno (predictor.trackers[0]) compartido
por TODAS las llamadas a ese modelo sin resetearlo nunca — si dos combates
corren en paralelo (dos nodos Edge simultáneos), sus IDs de tracking se
mezclan. Además, Model.predict()/.track() reutiliza y muta self.predictor
en cada llamada (ver engine/model.py Model.predict(),
`self.predictor.args = get_cfg(...)`), lo cual tampoco es seguro entre
threads concurrentes incluso sin tracking. Solución: instanciar
manualmente un BOTSORT por sesión (igual al que ultralytics crea
internamente, ver ultralytics/trackers/track.py on_predict_start /
on_predict_postprocess_end, código replicado a mano en _postprocess) y
serializar solo la llamada a model.predict() (stateless en cuanto a
tracking, pero igual muta self.predictor) con un threading.Lock compartido
por todas las sesiones del proceso.
"""

from __future__ import annotations

import threading

import numpy as np
import torch
from ultralytics.trackers.bot_sort import BOTSORT
from ultralytics.utils import YAML, IterableSimpleNamespace
from ultralytics.utils.checks import check_yaml

from fog.domain.models import PersonPose, TrackedFrame, TrackedSequence
from fog.ports.pose_estimator import PoseEstimatorPort, PoseTrackingSession
from shared.feature_extractor import try_lock_ids

# Mismo tracker que ultralytics usaría por default hoy (ver nota de
# discrepancia arriba sobre por qué ya no asumimos que es ByteTrack).
_TRACKER_CONFIG_NAME = "botsort.yaml"

# Mismos defaults que Model.track() le pasa a Model.predict() (ver
# ultralytics/engine/model.py Model.track()): conf bajo porque el tracker
# necesita ver detecciones de baja confianza para no perder IDs; batch=1
# porque procesamos un frame a la vez.
_TRACK_CONF = 0.1
_TRACK_BATCH = 1


def _load_tracker_cfg() -> IterableSimpleNamespace:
    path = check_yaml(_TRACKER_CONFIG_NAME)
    return IterableSimpleNamespace(**YAML.load(path))


class YoloV8PoseAdapter(PoseEstimatorPort):
    def __init__(self, model):
        """model: instancia ultralytics.YOLO ya cargada (yolov8x-pose.pt),
        inyectada por composition.py como Singleton. Este adaptador no
        carga pesos. El lock serializa model.predict() entre todas las
        sesiones activas (ver docstring del módulo)."""
        self._model = model
        self._predict_lock = threading.Lock()

    def start_session(self) -> PoseTrackingSession:
        return _YoloTrackingSession(self._model, self._predict_lock)


class _YoloTrackingSession(PoseTrackingSession):
    def __init__(self, model, predict_lock: threading.Lock):
        self._model = model
        self._predict_lock = predict_lock
        self._tracker = BOTSORT(args=_load_tracker_cfg())

        self._frame_w = 0
        self._frame_h = 0
        self._id_a: int | None = None
        self._id_b: int | None = None
        self._locked = False
        self._lock_frame: int | None = None
        self._frames_no_fencer = 0
        self._frames_single = 0
        self._tracked: list[TrackedFrame] = []
        self._frame_idx = 0
        self._finished = False

    def add_frame(self, frame: np.ndarray) -> None:
        if self._finished:
            raise RuntimeError("add_frame llamado después de finish()")

        if self._frame_idx == 0:
            self._frame_h, self._frame_w = frame.shape[:2]

        with self._predict_lock:
            results = self._model.predict(
                frame, conf=_TRACK_CONF, batch=_TRACK_BATCH, verbose=False
            )
        r = self._postprocess(results[0])
        self._frame_idx += 1

        if not self._locked and r.boxes is not None and len(r.boxes) > 0:
            boxes_xyxy = [b.cpu().numpy() for b in r.boxes.xyxy]
            ids = [int(t) for t in r.boxes.id] if r.boxes.id is not None else None
            cand_a, cand_b = try_lock_ids(boxes_xyxy, ids)
            if cand_a is not None:
                self._id_a, self._id_b = cand_a, cand_b
                self._locked = True
                self._lock_frame = self._frame_idx - 1

        if not self._locked:
            return

        id_to_idx: dict[int, int] = {}
        if r.boxes is not None and r.boxes.id is not None:
            for idx, tid in enumerate(r.boxes.id):
                id_to_idx[int(tid)] = idx

        idx_a = id_to_idx.get(self._id_a)
        idx_b = id_to_idx.get(self._id_b)

        if idx_a is None and idx_b is None:
            self._frames_no_fencer += 1
        elif idx_b is None:
            self._frames_single += 1

        self._tracked.append(TrackedFrame(
            person_a=self._person_pose(r, idx_a),
            person_b=self._person_pose(r, idx_b),
        ))

    def finish(self) -> TrackedSequence:
        self._finished = True
        return TrackedSequence(
            frames=self._tracked,
            frame_w=self._frame_w,
            frame_h=self._frame_h,
            locked=self._locked,
            lock_frame=self._lock_frame,
            frames_no_fencer=self._frames_no_fencer,
            frames_single=self._frames_single,
        )

    def _postprocess(self, result):
        """Replica manual de
        ultralytics.trackers.track.on_predict_postprocess_end para un
        BOTSORT propio de esta sesión, en vez del tracker compartido que
        register_tracker() registra cuando se llama model.track(persist=
        True). Si el tracker no devuelve tracks este frame, se devuelve
        el resultado original sin tocar (mismo comportamiento que el
        `continue` de on_predict_postprocess_end: r.boxes.id queda None,
        try_lock_ids ya maneja ese caso devolviendo (None, None))."""
        det = result.boxes.cpu().numpy()
        feats = getattr(result, "feats", None)
        tracks = self._tracker.update(det, result.orig_img, feats=feats)
        if len(tracks) == 0:
            return result
        idx = tracks[:, -1].astype(int)
        result = result[idx]
        result.update(boxes=torch.as_tensor(tracks[:, :-1]))
        return result

    @staticmethod
    def _person_pose(r, box_idx: int | None) -> PersonPose:
        if box_idx is None:
            return PersonPose.empty()
        box = r.boxes[box_idx]
        kpts = r.keypoints[box_idx]
        return PersonPose(
            keypoints_xy=kpts.xy[0].cpu().numpy().astype(np.float32),
            keypoints_conf=kpts.conf[0].cpu().numpy().astype(np.float32),
            box_xyxy=box.xyxy[0].cpu().numpy().astype(np.float32),
            detected=True,
        )
