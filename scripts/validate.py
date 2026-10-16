#!/usr/bin/env python3
"""Minimal blocking checks; strict on 182-show coverage, conservative on identity."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def rows(name):
    p = ROOT / name
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []

def main():
    songs = rows("data/easonkg/song_candidates.jsonl")
    facts = rows("data/easonkg/assertions.jsonl")
    shows = rows("data/wiki/fear_dreams_shows.jsonl")
    encore = rows("data/wiki/fear_dreams_encores_raw.jsonl")
    releases = rows("data/wiki/releases.jsonl")
    errors, warnings = [], []
    if not songs or not facts:
        errors.append("EasonKG fact import missing")
    if not shows:
        warnings.append("Wikipedia import has not run; full coverage not established")
    else:
        nums = sorted(x["number"] for x in shows)
        if nums != list(range(1, 183)):
            errors.append("Expected sequential show numbers 1..182")
        if len({x["show_id"] for x in shows}) != len(shows):
            errors.append("Duplicate show_id")
        bydate = Counter(x["date"] for x in shows)
        for event in encore:
            if bydate[event["date"]] == 0:
                errors.append("Encore event without matching show: " + event["date"])
        if len({x["date"] for x in encore}) < len({x["date"] for x in shows}):
            warnings.append("Encore coverage smaller than show dates")
    if shows and (not encore or not releases):
        errors.append("Wikipedia show import lacks encore or release candidates")
    if not rows("data/wiki/fear_dreams_main_templates.jsonl"):
        warnings.append("No main templates extracted; no per-day MAIN data confirmed")
    groups = {}
    for r in facts:
        if r["predicate"] == "reported_release_date":
            groups.setdefault(r["song_title"], set()).add(r["value"])
    conflicts = {k: sorted(v) for k, v in groups.items() if len(v) > 1}
    if conflicts:
        warnings.append("%d song titles have conflicting EasonKG dates" % len(conflicts))
    report = {"errors": errors, "warnings": warnings,
              "counts": {"song_candidates": len(songs), "assertions": len(facts),
                         "shows": len(shows), "encore_line_items": len(encore),
                         "release_candidates": len(releases)},
              "date_conflicts": conflicts}
    path = ROOT / "data" / "quality.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if errors:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
