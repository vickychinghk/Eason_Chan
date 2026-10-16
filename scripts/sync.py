#!/usr/bin/env python3
"""Extract traceable structured facts from two Chinese Wikipedia pages.
Unparseable multi-song cells remain raw; never infer a setlist silently.
"""
import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "wiki"
API = "https://zh.wikipedia.org/w/api.php"
PAGES = {
    "artist": "陳奕迅",
    "tour": "陳奕迅 Fear and Dreams世界巡迴演唱會",
}
SOURCE_URLS = {
    "artist": "https://zh.wikipedia.org/wiki/陳奕迅",
    "tour": "https://zh.wikipedia.org/wiki/FEAR_AND_DREAMS",
}
DATE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
YEAR = re.compile(r"(19\d{2}|20\d{2})")
HEADERS = {"巡回演出": "shows", "巡迴演出": "shows",
           "Encore曲目": "encores", "唱片列表": "releases",
           "演唱曲目": "templates"}


def text(tag):
    return tag.get_text(" ", strip=True).replace("\xa0", " ").strip() if tag else ""


def short(value):
    return " ".join(value.split())


def as_date(value):
    m = DATE.search(value or "")
    if not m:
        return None
    try:
        return "%04d-%02d-%02d" % tuple(map(int, m.groups()))
    except ValueError:
        return None


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True)
                            + "\n" for row in rows), encoding="utf-8")


def get_html(which):
    fixture = ROOT / "sources" / "html" / (which + ".html")
    if fixture.is_file():
        return fixture.read_text(encoding="utf-8"), "local-fixture", PAGES[which]
    headers = {
        "User-Agent": "EasonChanArchive/0.1 (educational discography indexing; GitHub vickychinghk/Eason_Chan)",
        "Accept": "application/json",
    }
    response = requests.get(API, params={
        "action": "parse", "page": PAGES[which], "redirects": 1,
        "prop": "text|revid", "format": "json", "formatversion": 2,
        "disableeditsection": 1,
    }, headers=headers, timeout=50)
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(str(payload["error"]))
    p = payload["parse"]
    html = p["text"] if isinstance(p["text"], str) else p["text"]["*"]
    return html, str(p.get("revid", "unknown")), p.get("title", PAGES[which])


def matrix(table):
    """Expand rowspan and colspan, retaining the original cell tags."""
    cells, occupancy = [], {}
    for r, tr in enumerate(table.find_all("tr")):
        row, c = [], 0
        for tag in tr.find_all(["th", "td"], recursive=False):
            while (r, c) in occupancy:
                c += 1
            rs = int(tag.get("rowspan", 1))
            cs = int(tag.get("colspan", 1))
            for rr in range(r, r + rs):
                for cc in range(c, c + cs):
                    occupancy[rr, cc] = tag
            c += cs
        width = max((cc for (rr, cc) in occupancy if rr == r), default=-1) + 1
        row = [occupancy.get((r, col)) for col in range(width)]
        cells.append(row)
    return cells


def section_tables(soup):
    """Associate tables with the nearest section headline (not visual position)."""
    section = None
    for el in soup.find_all(["h2", "h3", "table"]):
        if el.name in ("h2", "h3"):
            label = short(text(el)).replace("[编辑]", "").replace("编辑", "")
            if el.name == "h2":
                section = HEADERS.get(label)
            elif label.startswith("主歌單更迭"):
                section = None
        elif el.name == "table" and not el.find_parent("table"):
            yield section, el


def cell_lines(cell):
    if not cell:
        return []
    tag = copy.copy(cell)
    tag = BeautifulSoup(str(cell), "html.parser")
    for br in tag.find_all(["br", "hr"]):
        br.replace_with("\n")
    for sub in tag.find_all(["li", "p"]):
        sub.insert_after("\n")
    value = tag.get_text(separator="", strip=False).replace("\xa0", " ")
    return [short(x) for x in value.split("\n") if short(x)]


def parse_shows(tables, source):
    rows = []
    for table in tables:
        grid = matrix(table)
        headers = " ".join(text(x) for x in (grid[0] if grid else []))
        if not ("场次" in headers or "場次" in headers) or "日期" not in headers:
            continue
        for row in grid[1:]:
            values = [short(text(x)) for x in row]
            if len(values) < 2 or not values[0].isdigit():
                continue
            number, date = int(values[0]), as_date(values[1])
            if not date:
                continue
            # Original table columns: number, date, title, venue, city, organiser, notes.
            rows.append({
                "show_id": "fad-%03d" % number, "tour_id": "fear-and-dreams",
                "number": number, "date": date,
                "title_raw": values[2] if len(values) > 2 else None,
                "venue_raw": values[3] if len(values) > 3 else None,
                "city_raw": values[4] if len(values) > 4 else None,
                "notes_raw": values[6] if len(values) > 6 and values[6] else None,
                "source": source, "verification": "wiki_unverified",
            })
    # Deduplicate when multiple tables contain overlapping rows; fail on conflict.
    unique = {}
    for r in rows:
        if r["show_id"] in unique and r["date"] != unique[r["show_id"]]["date"]:
            raise ValueError("Conflicting dates for " + r["show_id"])
        unique[r["show_id"]] = r
    return sorted(unique.values(), key=lambda x: x["number"])


def parse_encores(tables, source):
    rows, nights = [], []
    for table in tables:
        grid = matrix(table)
        if not grid:
            continue
        header = [text(x) for x in grid[0]]
        if not ("演唱日期" in " ".join(header) and "歌曲名稱" in " ".join(header)):
            continue
        # May have blank first column for row-spanned city.
        di = next((i for i, c in enumerate(header) if "演唱日期" in c), 1)
        si = next((i for i, c in enumerate(header) if "歌曲名稱" in c), di + 1)
        ni = next((i for i, c in enumerate(header) if "備註" in c), si + 1)
        for gridrow in grid[1:]:
            if max(di, si) >= len(gridrow):
                continue
            date = as_date(text(gridrow[di]))
            if not date:
                continue
            pieces = cell_lines(gridrow[si])
            original = short(text(gridrow[si]))
            if not original:
                continue
            nights.append({"date": date, "raw_cell": original,
                           "note_raw": short(text(gridrow[ni])) if ni < len(gridrow) else "",
                           "source": source})
            for pos, piece in enumerate(pieces or [original], start=1):
                # Split only on explicit HTML line breaks; one line may still contain
                # multiple titles. No guess based on whitespace or punctuation.
                rows.append({
                    "date": date, "slot": pos, "title_raw": piece,
                    "parse_status": "html_line_not_identity_verified",
                    "section": "ENCORE", "source": source,
                })
    return rows, nights


def release_names(cell):
    if cell is None:
        return []
    output = []
    for chunk in cell_lines(cell):
        bracketed = re.findall(r"《([^》]+)》", chunk)
        if bracketed:
            for name in bracketed:
                output.append((name.strip(), chunk))
        elif chunk and not re.match(r"^[－—\s　]+$", chunk):
            # Unbracketed names can be ambiguous: retain as candidate, not official.
            output.append((chunk, chunk))
    return output


def parse_releases(tables, source):
    rows = []
    for table in tables:
        grid = matrix(table)
        if not grid:
            continue
        headers = [text(t) for t in grid[0]]
        if not ("年份" in " ".join(headers) and "粵語專輯" in " ".join(headers)):
            continue
        kinds = {2: ("album_or_compilation", "yue"),
                 3: ("album_or_compilation", "cmn"),
                 4: ("live_or_compilation", None),
                 5: ("digital", None)}
        for row in grid[1:]:
            if not row:
                continue
            year_match = YEAR.search(text(row[0]))
            if not year_match:
                continue
            year = int(year_match.group())
            label = short(text(row[1])) if len(row) > 1 else ""
            for col, (kind, lang) in kinds.items():
                if col >= len(row) or not row[col]:
                    continue
                for title, raw in release_names(row[col]):
                    rows.append({
                        "title": title, "release_year": year,
                        "column_type": kind, "language": lang,
                        "label_raw": label, "entry_raw": raw,
                        "type_hint": ("ep" if re.search(r"EP\b", raw, re.I)
                                      else "compilation" if re.search(r"精選|精选", raw)
                                      else "single" if re.search(r"Single", raw, re.I)
                                      else "unspecified"),
                        "release_date": None, "first_release": None,
                        "identity": "candidate_release_not_deduplicated",
                        "source": source,
                    })
    # Same cell may repeat due to page rowspan; row fingerprint is lossless here.
    unique = {json.dumps(x, ensure_ascii=False, sort_keys=True): x for x in rows}
    return list(unique.values())


def parse_main_templates(soup, source):
    """Read Wikipedia's collapsed city blocks; conditional positions stay raw."""
    templates = []
    for block in soup.select("div.hidden-div.mw-collapsible"):
        lines = [short(x) for x in block.get_text("\n", strip=True).split("\n") if short(x)]
        title = next((x for x in lines if "FEAR AND DREAMS" in x.upper() and "站" in x), "")
        if not title:
            continue
        positions = []
        for line in lines:
            match = re.match(r"^(\d{1,2})[.．]\s*(.+)$", line)
            if match:
                positions.append({"position": int(match.group(1)),
                                  "title_raw": match.group(2),
                                  "conditional": bool(re.search(r"第[一二三四五六七八九十\d]+[場场]|第一至|僅|仅|[\/／]", match.group(2)))})
        if len(positions) >= 15:
            templates.append({
                "template_title": title, "positions_raw": positions,
                "applicability": "unresolved_per_show",
                "warning": "This template has conditional positions; verify show-specific overrides.",
                "source": source,
            })
    return templates



def parse_main_changes(soup, source):
    """Retain explicit change history; descriptions are not applied as global rules."""
    heading = next((x for x in soup.find_all("h3") if "主歌單更迭歷史" in text(x)), None)
    if not heading:
        return []
    start = heading.parent if heading.parent.name == "div" else heading
    events = []
    for node in start.next_siblings:
        if not getattr(node, "name", None):
            continue
        if node.name == "h2" or (node.name == "div" and "mw-heading2" in node.get("class", [])):
            break
        if node.name != "ul":
            continue
        for li in node.find_all("li", recursive=False):
            first = li.get_text(" ", strip=True)
            date = as_date(first)
            if not date:
                continue
            number = re.search(r"演唱會第\s*(\d+)\s*場", first)
            sub = li.find(["ul", "ol"], recursive=False)
            changes = [short(text(x)) for x in sub.find_all("li", recursive=False)] if sub else []
            if not changes:
                changes = [short(first)]
            events.append({"effective_on": date, "show_number": int(number.group(1)) if number else None,
                           "changes_raw": changes, "source": source,
                           "applicability": "requires_confirmation"})
    return events

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    snapshots = {}
    for which in PAGES:
        html, revision, title = get_html(which)
        snapshots[which] = {
            "title": title, "revision": revision, "url": SOURCE_URLS[which],
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        # HTML snapshots deliberately not committed; only source ID is stored.
        if which == "artist":
            artist = BeautifulSoup(html, "lxml")
        else:
            tour = BeautifulSoup(html, "lxml")
    artist_src = "zhwiki:artist:" + snapshots["artist"]["revision"]
    tour_src = "zhwiki:tour:" + snapshots["tour"]["revision"]
    albums = parse_releases([t for _, t in section_tables(artist)], artist_src)
    tables = list(section_tables(tour))
    shows = parse_shows([t for s, t in tables if s == "shows"], tour_src)
    encores, encore_nights = parse_encores([t for s, t in tables if s == "encores"], tour_src)
    templates = parse_main_templates(tour, tour_src)
    changes = parse_main_changes(tour, tour_src)
    jsonl(OUT / "releases.jsonl", albums)
    jsonl(OUT / "fear_dreams_shows.jsonl", shows)
    jsonl(OUT / "fear_dreams_encores_raw.jsonl", encores)
    jsonl(OUT / "fear_dreams_encore_nights.jsonl", encore_nights)
    jsonl(OUT / "fear_dreams_main_templates.jsonl", templates)
    jsonl(OUT / "fear_dreams_main_changes.jsonl", changes)
    (ROOT / "sources" / "wikipedia.json").write_text(
        json.dumps(snapshots, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dates = {row["date"] for row in shows}
    report = {
        "shows": len(shows), "show_number_range": ([shows[0]["number"], shows[-1]["number"]]
                                                   if shows else None),
        "encore_rows": len(encores), "encore_dates": len({x["date"] for x in encores}),
        "encores_missing_shows": sorted({x["date"] for x in encores} - dates),
        "shows_missing_encores": sorted(dates - {x["date"] for x in encores}),
        "releases": len(albums), "main_templates": len(templates),
        "main_change_events": len(changes),
        "issues": [],
    }
    if len(shows) != 182 or [x["number"] for x in shows] != list(range(1, 183)):
        report["issues"].append("SHOW_COUNT_OR_SEQUENCE_NOT_182")
    if not albums:
        report["issues"].append("RELEASE_TABLE_PARSE_FAILED")
    if not encores:
        report["issues"].append("ENCORE_TABLE_PARSE_FAILED")
    if not templates:
        report["issues"].append("MAIN_TEMPLATE_PARSE_FAILED")
    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if "SHOW_COUNT_OR_SEQUENCE_NOT_182" in report["issues"] or not albums or not encores:
        raise SystemExit("Importer incomplete. Preserve report; do not publish as verified.")


if __name__ == "__main__":
    main()
