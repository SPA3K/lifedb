-- Life Timeline DB schema v1
-- 版本迁移: 变更表结构时递增 schema_version.version, 迁移脚本放 migrations/
CREATE TABLE IF NOT EXISTS schema_version (
  name       TEXT PRIMARY KEY,          -- 固定 'lifedb'
  version    INTEGER NOT NULL,          -- 当前结构版本
  updated_at TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_version(name, version, updated_at)
  VALUES ('lifedb', 1, datetime('now'));

CREATE TABLE IF NOT EXISTS event (
  id           INTEGER PRIMARY KEY,
  ts_start     TEXT NOT NULL,
  ts_end       TEXT,
  modality     TEXT NOT NULL,
  source       TEXT NOT NULL,
  title        TEXT,
  summary      TEXT,
  payload_ref  TEXT,
  payload_hash TEXT,
  lat          REAL,
  lon          REAL,
  tags         TEXT DEFAULT '[]',
  meta         TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_event_ts   ON event(ts_start);
CREATE INDEX IF NOT EXISTS idx_event_ts_end ON event(ts_end);   -- around 区间查询的 OR/UNION 分支
CREATE INDEX IF NOT EXISTS idx_event_mod  ON event(modality, ts_start);
CREATE INDEX IF NOT EXISTS idx_event_geo  ON event(lat, lon);
CREATE UNIQUE INDEX IF NOT EXISTS idx_event_dedup ON event(source, payload_hash);

-- 原始GPS点(一生轨迹csv专用): 秒级定位查询, 不进event表避免淹没跨模态关联
CREATE TABLE IF NOT EXISTS geo_point (
  ts    INTEGER NOT NULL,   -- epoch秒
  lat   REAL NOT NULL,
  lon   REAL NOT NULL,
  alt   REAL,
  speed REAL,
  PRIMARY KEY (ts, lat, lon)
);
CREATE INDEX IF NOT EXISTS idx_geo_ts ON geo_point(ts);
