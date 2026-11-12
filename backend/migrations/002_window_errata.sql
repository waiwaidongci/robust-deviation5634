-- 窗口勘误：窗口来源版本追踪 + 勘误批次处理结果
ALTER TABLE climate_windows ADD COLUMN IF NOT EXISTS source_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE climate_windows ADD COLUMN IF NOT EXISTS last_batch_id INTEGER;
CREATE TABLE IF NOT EXISTS window_errata_batches (
    id SERIAL PRIMARY KEY,
    study_id INTEGER NOT NULL REFERENCES archive_studies(id),
    batch_no TEXT NOT NULL,
    source_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    applied INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    rejected INTEGER NOT NULL DEFAULT 0,
    details JSON NOT NULL DEFAULT '[]',
    error TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (study_id,batch_no)
);
CREATE INDEX IF NOT EXISTS errata_study_idx ON window_errata_batches (study_id,id);
