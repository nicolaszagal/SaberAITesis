-- =====================================================================
-- SABRE.AI: esquema de base de datos (PostgreSQL 16)
-- Sistema de video arbitraje asistido con BiLSTM para esgrima (sable)
-- Trazabilidad: RF-01 a RF-30, RNF-05, RNF-07, RNF-11, RNF-16 (Backlog V1.5)
--
-- Criterio de diseño:
--   * La base guarda hechos y relaciones (combate, revisión, veredicto, versión
--     de modelo, auditoría). Los binarios pesados (video, keypoints, features)
--     viven en almacenamiento de objetos (volumen o MinIO); aquí solo su URI y
--     su hash SHA-256 para verificar integridad.
--   * Redis Streams sigue siendo el bus Fog <-> Cloud; no es base de registro.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS sabre;
SET search_path TO sabre;

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid(), digest()

-- ---------------------------------------------------------------------
-- Dominios
-- ---------------------------------------------------------------------
CREATE DOMAIN lado        AS CHAR(1)  CHECK (VALUE IN ('A','B'));
CREATE DOMAIN brazo       AS TEXT     CHECK (VALUE IN ('diestro','zurdo'));
CREATE DOMAIN clase_tact  AS TEXT     CHECK (VALUE IN ('AtaqueA','AtaqueB','ContraataqueA',
                                                       'ContraataqueB','RiposteA','RiposteB'));
CREATE DOMAIN sha256_hex  AS CHAR(64) CHECK (VALUE ~ '^[0-9a-f]{64}$');
CREATE DOMAIN probabilidad AS NUMERIC(5,4) CHECK (VALUE BETWEEN 0 AND 1);

-- ---------------------------------------------------------------------
-- Personas y usuarios
-- ---------------------------------------------------------------------
CREATE TABLE usuario (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre        TEXT NOT NULL,
    rol           TEXT NOT NULL CHECK (rol IN ('arbitro','operador','administrador')),
    activo        BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Datos mínimos del tirador (minimización; puede usarse un alias).
-- La identidad NO entra al cálculo de la clasificación (F-036).
CREATE TABLE tirador (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alias                  TEXT NOT NULL,
    brazo_habitual         brazo NOT NULL,
    es_menor               BOOLEAN NOT NULL,
    consentimiento_firmado BOOLEAN NOT NULL DEFAULT FALSE,   -- RNF-16 (Ley 29733)
    consentimiento_fecha   DATE,
    firmante               TEXT,                             -- apoderado si es menor
    creado_en              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (NOT consentimiento_firmado OR consentimiento_fecha IS NOT NULL),
    CHECK (NOT (es_menor AND consentimiento_firmado) OR firmante IS NOT NULL)
);

-- ---------------------------------------------------------------------
-- Competencia y combate (CU-01, F-039)
-- ---------------------------------------------------------------------
CREATE TABLE evento (
    id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre    TEXT NOT NULL,
    fecha     DATE NOT NULL,
    lugar     TEXT,
    tipo      TEXT NOT NULL CHECK (tipo IN ('piloto','formativo','oficial'))
);

CREATE TABLE combate (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evento_id     UUID REFERENCES evento(id),
    pista         TEXT NOT NULL,
    fase          TEXT CHECK (fase IN ('poule','eliminacion','entrenamiento')),
    tirador_a_id  UUID NOT NULL REFERENCES tirador(id),
    tirador_b_id  UUID NOT NULL REFERENCES tirador(id),
    brazo_a       brazo NOT NULL,          -- copia al momento del combate
    brazo_b       brazo NOT NULL,
    arbitro_id    UUID NOT NULL REFERENCES usuario(id),
    configurado_por UUID NOT NULL REFERENCES usuario(id),
    creado_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (tirador_a_id <> tirador_b_id)
);

-- ---------------------------------------------------------------------
-- Entrada: clip y tocado (CU-02, CU-03, CU-04)
-- ---------------------------------------------------------------------
CREATE TABLE clip (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    combate_id      UUID NOT NULL REFERENCES combate(id),
    origen          TEXT NOT NULL CHECK (origen IN ('carga','captura')),
    camara          TEXT NOT NULL CHECK (camara IN ('frontal','cenital','unica')),
    uri             TEXT NOT NULL,
    sha256          sha256_hex NOT NULL,
    fps             NUMERIC(6,2) NOT NULL CHECK (fps > 0),
    ancho_px        INT NOT NULL,
    alto_px         INT NOT NULL,
    duracion_ms     INT NOT NULL CHECK (duracion_ms > 0),
    t0_utc          TIMESTAMPTZ,           -- timestamp del primer frame (sincronía)
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_clip_combate ON clip(combate_id);

CREATE TABLE tocado (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    combate_id    UUID NOT NULL REFERENCES combate(id),
    fuente        TEXT NOT NULL CHECK (fuente IN ('simulado','favero')),
    luz_a         BOOLEAN NOT NULL,
    luz_b         BOOLEAN NOT NULL,
    t_tocado_utc  TIMESTAMPTZ,             -- señal Favero real
    t_tocado_ms   INT,                     -- offset dentro del clip (simulado)
    registrado_por UUID REFERENCES usuario(id),
    creado_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (luz_a OR luz_b),
    CHECK (t_tocado_utc IS NOT NULL OR t_tocado_ms IS NOT NULL)
);
CREATE INDEX ix_tocado_combate ON tocado(combate_id);

-- Clips (una o dos cámaras) que cubren un tocado
CREATE TABLE tocado_clip (
    tocado_id  UUID NOT NULL REFERENCES tocado(id),
    clip_id    UUID NOT NULL REFERENCES clip(id),
    frame_tocado INT NOT NULL CHECK (frame_tocado >= 0),   -- F-004
    PRIMARY KEY (tocado_id, clip_id)
);

-- ---------------------------------------------------------------------
-- Modelo y clasificación (CU-06, CU-13)
-- ---------------------------------------------------------------------
CREATE TABLE modelo_version (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre          TEXT NOT NULL UNIQUE,          -- p. ej. lstm_v2-6c-r01
    checkpoint_uri  TEXT NOT NULL,
    checkpoint_sha256 sha256_hex NOT NULL UNIQUE,
    pose_modelo     TEXT NOT NULL,                 -- p. ej. yolov8x-pose
    num_features    INT NOT NULL,
    num_clases      INT NOT NULL CHECK (num_clases = 6),
    reglamento      TEXT NOT NULL DEFAULT 'FIE 2026',
    f1_macro_test   NUMERIC(5,4),
    kappa_piloto    NUMERIC(5,4),
    padre_id        UUID REFERENCES modelo_version(id),   -- linaje de reentrenamiento
    activo          BOOLEAN NOT NULL DEFAULT FALSE,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Solo una versión activa a la vez (RNF-10)
CREATE UNIQUE INDEX ux_modelo_activo ON modelo_version(activo) WHERE activo;

CREATE TABLE clasificacion (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tocado_id          UUID NOT NULL REFERENCES tocado(id),
    modelo_version_id  UUID NOT NULL REFERENCES modelo_version(id),
    disponible         BOOLEAN NOT NULL,
    motivo_no_disp     TEXT CHECK (motivo_no_disp IN ('pose_incompleta','confianza_baja',
                                     'clase_fuera_mvp','timeout','sin_senal_favero',
                                     'mensaje_invalido')),
    clase              clase_tact,
    tirador            lado,
    confianza          probabilidad,
    probabilidades     JSONB,          -- {"AtaqueA":0.61, ...} post filtro Favero
    keypoints_uri      TEXT NOT NULL,  -- keypoints crudos (.npz), F-034 / T-018
    keypoints_sha256   sha256_hex NOT NULL,
    features_uri       TEXT,
    latencia_ms        INT CHECK (latencia_ms >= 0),
    latencia_inferencia_ms INT CHECK (latencia_inferencia_ms >= 0),  -- BiLSTM en Cloud (F-027); NULL si no disponible
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Determinismo (F-036): un resultado por tocado y versión de modelo
    UNIQUE (tocado_id, modelo_version_id),
    CHECK ( (disponible AND clase IS NOT NULL AND tirador IS NOT NULL
             AND confianza IS NOT NULL AND motivo_no_disp IS NULL)
         OR (NOT disponible AND clase IS NULL AND motivo_no_disp IS NOT NULL) ),
    CHECK (clase IS NULL OR right(clase,1) = tirador)
);

-- Justificación y evidencia (CU-09, F-035)
CREATE TABLE evidencia (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clasificacion_id  UUID NOT NULL REFERENCES clasificacion(id),
    tipo              TEXT NOT NULL CHECK (tipo IN ('inicio_extension_brazo','inicio_desplazamiento',
                                                    'tocado','frame_clave','criterio_fie')),
    tirador           lado,
    frame_idx         INT,
    t_ms              INT,
    articulo_fie      TEXT,            -- p. ej. t.101.2
    detalle           JSONB
);
CREATE INDEX ix_evidencia_clasif ON evidencia(clasificacion_id);

-- ---------------------------------------------------------------------
-- Revisión VAR y veredicto (CU-05, CU-07, CU-10)
-- No se registra qué tirador solicitó la revisión (decisión del PO).
-- ---------------------------------------------------------------------
CREATE TABLE revision_var (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tocado_id         UUID NOT NULL REFERENCES tocado(id),
    aceptada          BOOLEAN NOT NULL,
    arbitro_id        UUID NOT NULL REFERENCES usuario(id),
    clasificacion_id  UUID REFERENCES clasificacion(id),
    abierta_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
    cerrada_en        TIMESTAMPTZ,
    CHECK (aceptada OR clasificacion_id IS NULL)
);
CREATE INDEX ix_revision_tocado ON revision_var(tocado_id);

CREATE TABLE veredicto (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    revision_id    UUID NOT NULL UNIQUE REFERENCES revision_var(id),
    decision       TEXT NOT NULL CHECK (decision IN ('mantener','cambiar','anular')),
    clase_final    clase_tact,
    arbitro_id     UUID NOT NULL REFERENCES usuario(id),
    registrado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ( (decision = 'cambiar' AND clase_final IS NOT NULL)
         OR (decision = 'anular'  AND clase_final IS NULL)
         OR  decision = 'mantener')
);

-- ---------------------------------------------------------------------
-- Auditoría inalterable (CU-11, CU-12, RNF-05)
-- Cadena de hashes: cada registro incluye el hash del anterior.
-- ---------------------------------------------------------------------
CREATE TABLE registro_auditoria (
    seq          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    revision_id  UUID NOT NULL UNIQUE REFERENCES revision_var(id),
    snapshot     JSONB NOT NULL,        -- revisión + clasificación + veredicto + modelo
    hash_prev    sha256_hex,
    hash         sha256_hex NOT NULL,
    creado_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE FUNCTION fn_auditoria_hash() RETURNS trigger AS $$
DECLARE prev TEXT;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('sabre.registro_auditoria'));
    SELECT hash INTO prev FROM registro_auditoria ORDER BY seq DESC LIMIT 1;
    NEW.hash_prev := prev;
    NEW.hash := encode(digest(coalesce(prev,'') || NEW.snapshot::text, 'sha256'), 'hex');
    RETURN NEW;
END $$ LANGUAGE plpgsql SET search_path = sabre, pg_temp;

CREATE TRIGGER tg_auditoria_hash BEFORE INSERT ON registro_auditoria
    FOR EACH ROW EXECUTE FUNCTION fn_auditoria_hash();

CREATE FUNCTION fn_bloquear_cambios() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Los registros de auditoría no pueden modificarse';
END $$ LANGUAGE plpgsql SET search_path = sabre, pg_temp;

CREATE TRIGGER tg_auditoria_inmutable BEFORE UPDATE OR DELETE ON registro_auditoria
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_cambios();
CREATE TRIGGER tg_veredicto_inmutable BEFORE UPDATE OR DELETE ON veredicto
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_cambios();
CREATE TRIGGER tg_clasificacion_inmutable BEFORE UPDATE OR DELETE ON clasificacion
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_cambios();

-- Verificación de la cadena (CU-12): devuelve los registros alterados
CREATE FUNCTION fn_verificar_auditoria()
RETURNS TABLE(seq BIGINT, esperado TEXT, guardado TEXT) AS $$
    WITH c AS (
        SELECT r.seq, r.hash,
               encode(digest(coalesce(lag(r.hash) OVER (ORDER BY r.seq),'')
                             || r.snapshot::text,'sha256'),'hex') AS calc
        FROM sabre.registro_auditoria r)
    SELECT c.seq, c.calc, c.hash FROM c WHERE c.calc <> c.hash;
$$ LANGUAGE sql STABLE SET search_path = sabre, pg_temp;

-- ---------------------------------------------------------------------
-- Reentrenamiento (CU-14, T-018)
-- ---------------------------------------------------------------------
CREATE TABLE lote_reentrenamiento (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    modelo_base_id     UUID NOT NULL REFERENCES modelo_version(id),
    modelo_result_id   UUID REFERENCES modelo_version(id),
    dataset_uri        TEXT NOT NULL,
    dataset_sha256     sha256_hex NOT NULL,
    creado_por         UUID NOT NULL REFERENCES usuario(id),
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE lote_revision (
    lote_id      UUID NOT NULL REFERENCES lote_reentrenamiento(id),
    revision_id  UUID NOT NULL REFERENCES revision_var(id),
    PRIMARY KEY (lote_id, revision_id)
);

-- Vista de muestras etiquetadas: la etiqueta es la decisión final declarada
-- por el árbitro (`veredicto.clase_final`, obligatoria con mantener y cambiar).
-- "mantener"/"cambiar" describen la relación con la decisión original en pista.
CREATE VIEW v_muestras_confirmadas AS
SELECT r.id AS revision_id,
       c.keypoints_uri, c.keypoints_sha256,
       c.clase AS clase_sugerida,
       v.clase_final AS etiqueta,
       v.decision, m.nombre AS modelo, v.registrado_en
FROM revision_var r
JOIN veredicto v      ON v.revision_id = r.id
JOIN clasificacion c  ON c.id = r.clasificacion_id
JOIN modelo_version m ON m.id = c.modelo_version_id
WHERE v.decision <> 'anular' AND c.disponible;
