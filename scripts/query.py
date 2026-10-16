#!/usr/bin/env python3
"""Usage: python scripts/query.py 2025-08-10 | jq ."""
import json
import sqlite3
import sys
from pathlib import Path

db_path = Path(__file__).resolve().parents[1] / "data/db/eason.sqlite"

def query(date):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    shows = db.execute(
        "SELECT id,show_no,show_date,city_raw,venue_raw,verification FROM show "
        "WHERE show_date=? ORDER BY show_no", (date,)).fetchall()
    result = []
    for show in shows:
        sid = show["id"]
        main = [dict(row) for row in db.execute(
            "SELECT position,title_raw,conditional,template_title,assignment "
            "FROM show_main_candidate WHERE show_id=? ORDER BY position", (sid,))]
        encore = [dict(row) for row in db.execute(
            "SELECT slot,title_raw,kind,parse_status,source_id "
            "FROM performance WHERE show_id=? AND section='ENCORE' ORDER BY slot",
            (sid,))]
        provenance = db.execute(
            "SELECT note_raw,source_id FROM encore_night WHERE show_date=?",
            (date,)).fetchone()
        result.append({
            "show": dict(show),
            "main": main,
            "main_status": "INFERRED_CITY_TEMPLATE_NOT_DAY_VERIFIED",
            "encore": encore,
            "encore_status": "WIKIPEDIA_LINE_ITEMS_NOT_INDEPENDENTLY_VERIFIED",
            "encore_evidence": dict(provenance) if provenance else None,
        })
    db.close()
    return result

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/query.py YYYY-MM-DD")
    print(json.dumps(query(sys.argv[1]), ensure_ascii=False, indent=2))
