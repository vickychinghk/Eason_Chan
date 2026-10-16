#!/usr/bin/env python3
"""Conservative exact-name comparison of EasonKG and Wikipedia candidate claims."""
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    p = ROOT / name
    if not p.is_file():
        raise FileNotFoundError(name)
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]

def date_easonkg(value):
    m = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", value.strip())
    if not m:
        return None
    return f"{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}"

def main():
    facts = load("data/easonkg/assertions.jsonl")
    wiki = [
        row for fn in ("song_album_tracks.jsonl", "song_singles.jsonl",
                       "song_collaborations.jsonl")
        for row in load("data/wiki/" + fn)
    ]
    kg = defaultdict(lambda: defaultdict(set))
    for row in facts:
        kg[row["song_title"]][row["predicate"]].add(row["value"])
    by_name = defaultdict(list)
    for row in wiki:
        by_name[re.sub(r"\s*\*\s*$", "", row["title"])].append(row)
    shared = sorted(set(kg) & set(by_name))
    date_review, album_name_review = [], []
    for title in shared:
        rows = by_name[title]
        wiki_dates = sorted({row["date"] for row in rows if row.get("date")})
        kg_dates = sorted({x for raw in kg[title].get("reported_release_date", [])
                           if (x := date_easonkg(raw))})
        # Not a logical contradiction: Wikipedia track dates describe album issues,
        # while EasonKG may be asserting initial songs or another issue.
        if kg_dates and wiki_dates and set(kg_dates).isdisjoint(wiki_dates):
            date_review.append({"title": title, "kg_dates": kg_dates,
                                "wiki_dates": wiki_dates,
                                "reason": "date_semantics_or_issue_may_differ"})
        wiki_album = sorted({r.get("album_title") for r in rows if r.get("album_title")})
        kg_album = sorted(kg[title].get("所属专辑", set()))
        if wiki_album and kg_album and set(wiki_album).isdisjoint(kg_album):
            album_name_review.append({"title": title, "kg_album_raw": kg_album,
                                      "wiki_album_raw": wiki_album,
                                      "reason": "may_be_alias_reissue_or_other_album"})
    result = {
        "method": "Exact Unicode song-title join; trailing Wiki hit marker * removed. No automatic simplified/traditional folding.",
        "matched_song_titles": len(shared),
        "kg_titles_with_assertions": len(kg),
        "wiki_distinct_title_labels": len(by_name),
        "date_review_candidates": date_review,
        "album_name_review_candidates": album_name_review,
        "caution": "Candidate differences are not verified contradictions; never automatically merge work or album identities.",
    }
    (ROOT / "data/crosscheck.json").write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8")
    print(json.dumps({"matched_titles": len(shared), "review_date": len(date_review),
                      "review_album_label": len(album_name_review)}))

if __name__ == "__main__":
    main()
