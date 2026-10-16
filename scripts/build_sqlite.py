#!/usr/bin/env python3
"""Build a queryable SQLite cache; imports are candidate facts, not verified identities."""
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "db" / "eason.sqlite"

DDL = """
PRAGMA foreign_keys=ON;
CREATE TABLE source (id TEXT PRIMARY KEY, uri TEXT, revision TEXT, status TEXT);
CREATE TABLE work (id TEXT PRIMARY KEY, canonical_title TEXT NOT NULL);
CREATE TABLE work_alias (work_id TEXT REFERENCES work(id), title TEXT NOT NULL,
  locale TEXT, alias_kind TEXT, PRIMARY KEY(work_id,title,alias_kind));
CREATE TABLE recording (id TEXT PRIMARY KEY, work_id TEXT REFERENCES work(id),
  rendition TEXT, recorded_on TEXT);
CREATE TABLE release_group (id TEXT PRIMARY KEY, title TEXT NOT NULL, grouping_notes TEXT);
CREATE TABLE release (id TEXT PRIMARY KEY,
  release_group_id TEXT REFERENCES release_group(id), title TEXT NOT NULL,
  released_on TEXT, language TEXT, format TEXT, region TEXT);
CREATE TABLE release_track (release_id TEXT REFERENCES release(id),
  disc_no INTEGER NOT NULL, track_no INTEGER NOT NULL,
  recording_id TEXT REFERENCES recording(id),
  title_raw TEXT, PRIMARY KEY(release_id,disc_no,track_no));
CREATE TABLE song_candidate (id TEXT PRIMARY KEY, title TEXT NOT NULL, source_id TEXT);
CREATE TABLE assertion (id TEXT PRIMARY KEY, candidate_id TEXT REFERENCES song_candidate(id),
  predicate TEXT NOT NULL, value_raw TEXT NOT NULL, source_id TEXT,
  verified INTEGER NOT NULL DEFAULT 0);
CREATE TABLE release_candidate (id TEXT PRIMARY KEY, title TEXT, release_year INTEGER,
  language TEXT, column_type TEXT, type_hint TEXT, label_raw TEXT, source_id TEXT,
  identity_status TEXT NOT NULL);
CREATE TABLE tour (id TEXT PRIMARY KEY, title TEXT);
CREATE TABLE show (id TEXT PRIMARY KEY, tour_id TEXT REFERENCES tour(id),
  show_no INTEGER NOT NULL, show_date TEXT NOT NULL, city_raw TEXT, venue_raw TEXT,
  title_raw TEXT, notes_raw TEXT, source_id TEXT, verification TEXT,
  UNIQUE(tour_id,show_no));
CREATE TABLE main_template (id TEXT PRIMARY KEY, title TEXT,
  positions_json TEXT, applicability TEXT, source_id TEXT);
CREATE TABLE performance (id TEXT PRIMARY KEY, show_id TEXT REFERENCES show(id),
  section TEXT NOT NULL, encore_round INTEGER, slot INTEGER, work_id TEXT REFERENCES work(id),
  recording_id TEXT REFERENCES recording(id), kind TEXT NOT NULL DEFAULT 'UNKNOWN',
  title_raw TEXT NOT NULL, parse_status TEXT, notes_raw TEXT, source_id TEXT);
CREATE TABLE performance_component (performance_id TEXT REFERENCES performance(id),
  component_order INTEGER, work_id TEXT REFERENCES work(id),
  title_raw TEXT, PRIMARY KEY(performance_id,component_order));
CREATE TABLE evidence (entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
  source_id TEXT, source_location TEXT, value_raw TEXT,
  PRIMARY KEY(entity_type,entity_id,source_id,source_location));
CREATE INDEX idx_show_date ON show(show_date);
CREATE INDEX idx_performance_show ON performance(show_id,section,slot);
CREATE INDEX idx_fact_candidate ON assertion(candidate_id,predicate);
CREATE INDEX idx_release_title ON release_candidate(title);
"""

def read(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]

def identity(prefix, *parts):
    raw = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return prefix + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

def main():
    DEST.parent.mkdir(parents=True, exist_ok=True)
    if DEST.exists():
        DEST.unlink()
    db = sqlite3.connect(DEST)
    db.executescript(DDL)
    db.execute("INSERT INTO tour VALUES (?,?)",
               ("fear-and-dreams", "FEAR AND DREAMS"))
    candidates = read(ROOT / "data/easonkg/song_candidates.jsonl")
    facts = read(ROOT / "data/easonkg/assertions.jsonl")
    release_rows = read(ROOT / "data/wiki/releases.jsonl")
    show_rows = read(ROOT / "data/wiki/fear_dreams_shows.jsonl")
    encore_rows = read(ROOT / "data/wiki/fear_dreams_encores_raw.jsonl")
    templates = read(ROOT / "data/wiki/fear_dreams_main_templates.jsonl")
    for c in candidates:
        db.execute("INSERT OR IGNORE INTO song_candidate VALUES (?,?,?)",
                   (identity("candidate:", c["title"]), c["title"], c.get("source")))
    for fact in facts:
        cid = identity("candidate:", fact["song_title"])
        db.execute("INSERT OR IGNORE INTO song_candidate VALUES (?,?,?)",
                   (cid, fact["song_title"], fact.get("source")))
        aid = identity("assertion:", cid, fact["predicate"], fact["value"], fact["source"])
        db.execute("INSERT OR IGNORE INTO assertion VALUES (?,?,?,?,?,0)",
                   (aid, cid, fact["predicate"], fact["value"], fact["source"]))
    for row in release_rows:
        rid = identity("release_candidate:", row["title"], row["release_year"],
                       row.get("language"), row.get("column_type"),
                       row.get("entry_raw"), row.get("label_raw"))
        db.execute("INSERT OR IGNORE INTO release_candidate VALUES (?,?,?,?,?,?,?,?,?)",
                   (rid, row["title"], row["release_year"], row.get("language"),
                    row.get("column_type"), row.get("type_hint"),
                    row.get("label_raw"), row.get("source"),
                    row.get("identity")))
    by_date = {}
    for row in show_rows:
        db.execute("INSERT INTO show VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (row["show_id"], row["tour_id"], row["number"], row["date"],
                    row.get("city_raw"), row.get("venue_raw"), row.get("title_raw"),
                    row.get("notes_raw"), row.get("source"), row["verification"]))
        by_date.setdefault(row["date"], []).append(row["show_id"])
    for n, row in enumerate(encore_rows):
        matches = by_date.get(row["date"], [])
        # Do not join when one date has multiple shows.
        show_id = matches[0] if len(matches) == 1 else None
        pid = identity("performance:", row["date"], row.get("slot"), n)
        db.execute("INSERT INTO performance "
                   "(id,show_id,section,encore_round,slot,kind,title_raw,"
                   "parse_status,notes_raw,source_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (pid, show_id, "ENCORE", None, row["slot"], "UNKNOWN",
                    row["title_raw"], row.get("parse_status"), row.get("note_raw"),
                    row.get("source")))
    for row in templates:
        tid = identity("template:", row["template_title"])
        db.execute("INSERT OR IGNORE INTO main_template VALUES (?,?,?,?,?)",
                   (tid, row["template_title"],
                    json.dumps(row["positions_raw"], ensure_ascii=False),
                    row["applicability"], row["source"]))
    db.commit()
    summary = {table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
               for table in ("song_candidate", "assertion", "release_candidate",
                             "show", "performance", "main_template")}
    print(json.dumps(summary, ensure_ascii=False))
    db.close()

if __name__ == "__main__":
    main()
