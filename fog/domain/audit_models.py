"""Entidades del dominio de auditoría (docs_claude/sabre_ai_schema.sql).

Bounded context propio dentro de Fog: a diferencia de `domain/models.py`
(estado runtime de una sesión WebRTC: `Match`, `TrackedSequence`, etc.),
estas entidades son la proyección 1:1 de las tablas que persiste
`infrastructure/persistence/postgres/` (ver PLAN_ARQUITECTURA_DDD.md
sección 1) — sin lógica de negocio propia, solo la forma de cada fila.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Usuario:
    id: uuid.UUID
    nombre: str
    rol: str  # 'arbitro' | 'operador' | 'administrador'
    activo: bool
    creado_en: datetime


@dataclass(frozen=True)
class Tirador:
    id: uuid.UUID
    alias: str
    brazo_habitual: str  # 'diestro' | 'zurdo'
    es_menor: bool
    consentimiento_firmado: bool
    consentimiento_fecha: date | None
    firmante: str | None
    creado_en: datetime


@dataclass(frozen=True)
class Evento:
    id: uuid.UUID
    nombre: str
    fecha: date
    lugar: str | None
    tipo: str  # 'piloto' | 'formativo' | 'oficial'


@dataclass(frozen=True)
class Combate:
    id: uuid.UUID
    evento_id: uuid.UUID | None
    pista: str
    fase: str | None
    tirador_a_id: uuid.UUID
    tirador_b_id: uuid.UUID
    brazo_a: str  # 'diestro' | 'zurdo'
    brazo_b: str
    arbitro_id: uuid.UUID
    configurado_por: uuid.UUID
    creado_en: datetime


@dataclass(frozen=True)
class Clip:
    id: uuid.UUID
    combate_id: uuid.UUID
    origen: str  # 'carga' | 'captura'
    camara: str  # 'frontal' | 'cenital' | 'unica'
    uri: str
    sha256: str
    fps: float
    ancho_px: int
    alto_px: int
    duracion_ms: int
    t0_utc: datetime | None
    creado_en: datetime


@dataclass(frozen=True)
class Tocado:
    id: uuid.UUID
    combate_id: uuid.UUID
    fuente: str  # 'simulado' | 'favero'
    luz_a: bool
    luz_b: bool
    t_tocado_utc: datetime | None
    t_tocado_ms: int | None
    registrado_por: uuid.UUID | None
    creado_en: datetime
    t_luz_a_ms: int | None = None  # instante de la luz A; None = apagada
    t_luz_b_ms: int | None = None


@dataclass(frozen=True)
class ModeloVersion:
    id: uuid.UUID
    nombre: str
    checkpoint_uri: str
    checkpoint_sha256: str
    pose_modelo: str
    num_features: int
    num_clases: int
    reglamento: str
    f1_macro_test: float | None
    kappa_piloto: float | None
    padre_id: uuid.UUID | None
    activo: bool
    creado_en: datetime


@dataclass(frozen=True)
class Clasificacion:
    id: uuid.UUID
    tocado_id: uuid.UUID
    modelo_version_id: uuid.UUID
    disponible: bool
    motivo_no_disp: str | None
    clase: str | None
    tirador: str | None  # 'A' | 'B'
    confianza: float | None
    probabilidades: dict | None
    keypoints_uri: str
    keypoints_sha256: str
    features_uri: str | None
    latencia_ms: int | None
    creado_en: datetime
    # Tiempo del clasificador en Cloud (F-027); None si no hubo inferencia.
    latencia_inferencia_ms: int | None = None


@dataclass(frozen=True)
class Revision:
    id: uuid.UUID
    tocado_id: uuid.UUID
    aceptada: bool
    arbitro_id: uuid.UUID
    clasificacion_id: uuid.UUID | None
    abierta_en: datetime
    cerrada_en: datetime | None


@dataclass(frozen=True)
class Veredicto:
    id: uuid.UUID
    revision_id: uuid.UUID
    decision: str  # 'mantener' | 'cambiar' | 'anular'
    clase_final: str | None
    arbitro_id: uuid.UUID
    registrado_en: datetime


@dataclass(frozen=True)
class Auditoria:
    seq: int
    revision_id: uuid.UUID
    snapshot: dict
    hash_prev: str | None
    hash: str
    creado_en: datetime


@dataclass(frozen=True)
class ResumenRevision:
    """Fila de la lista de revisiones (GET /revisiones). Los campos de
    sugerencia y veredicto son None mientras no exista la fila que los
    origina. `clase` está en el vocabulario del modelo."""

    id: uuid.UUID
    combate_id: uuid.UUID
    abierta_en: datetime
    cerrada_en: datetime | None
    disponible: bool | None
    clase: str | None
    confianza: float | None
    decision: str | None
    clase_final: str | None


@dataclass(frozen=True)
class DetalleRevision:
    """Revisión con su sugerencia, veredicto y sello de auditoría
    (GET /revisiones/{id}). Clases y probabilidades en el vocabulario del
    modelo."""

    id: uuid.UUID
    combate_id: uuid.UUID
    abierta_en: datetime
    cerrada_en: datetime | None
    disponible: bool | None
    motivo_no_disp: str | None
    clase: str | None
    tirador: str | None
    confianza: float | None
    probabilidades: dict | None
    decision: str | None
    clase_final: str | None
    registrado_en: datetime | None
    auditoria_seq: int | None
    auditoria_hash: str | None


@dataclass(frozen=True)
class RegistroAlterado:
    """Fila que devuelve `sabre.fn_verificar_auditoria()`: el hash guardado
    no coincide con el recalculado (CU-12)."""

    seq: int
    esperado: str
    guardado: str
