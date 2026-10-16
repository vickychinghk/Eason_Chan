#!/usr/bin/env python3
"""Extract traceable structured facts from Chinese Wikipedia pages.
Unparseable multi-song cells remain raw; never infer a setlist silently.
"""
import copy
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "wiki"
API = "https://zh.wikipedia.org/w/api.php"
PAGES = {
    "artist": "陳奕迅",
    "songs": "陳奕迅歌曲列表",
    "tour": "陳奕迅 Fear and Dreams世界巡迴演唱會",
}
SOURCE_URLS = {
    "artist": "https://zh.wikipedia.org/wiki/陳奕迅",
    "songs": "https://zh.wikipedia.org/wiki/陳奕迅歌曲列表",
    "tour": "https://zh.wikipedia.org/wiki/FEAR_AND_DREAMS",
}
DATE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
YEAR = re.compile(r"(19\d{2}|20\d{2})")
HEADERS = {"巡回演出": "shows", "巡迴演出": "shows",
           "Encore曲目": "encores", "唱片列表": "releases",
           "演唱曲目": "templates",
           "個人專輯之歌曲列表": "album_tracks",
           "單曲列表": "singles",
           "非個人專輯之合唱歌曲列表": "collaborations",
           "雙語歌曲列表": "bilingual"}


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


def iso_release_date(raw):
    """Keep unavailable precision as NULL rather than guessing day/month."""
    raw = short(raw or "")
    m = re.search(r"(?:19|20)\d{2}-\d{1,2}-\d{1,2}", raw)
    if m:
        from datetime import date
        try:
            return date.fromisoformat("-".join([
                m.group().split("-")[0],
                m.group().split("-")[1].zfill(2),
                m.group().split("-")[2].zfill(2),
            ])).isoformat()
        except ValueError:
            return None
    return as_date(raw)


def album_title(cell):
    """Extract link text while retaining full original notes and language tag."""
    if not cell:
        return ""
    anchor = cell.find("a", href=True)
    return short(text(anchor)) if anchor and short(text(anchor)) else short(text(cell))


def parse_song_lists(soup, source):
    """Parsed facts stay candidates. Album dates are NOT first-ever song dates."""
    albums, singles, collabs, pairs = [], [], [], []
    for section, table in section_tables(soup):
        if section not in ("album_tracks", "singles", "collaborations", "bilingual"):
            continue
        grid = matrix(table)
        if len(grid) < 2:
            continue
        heads = [short(text(c)) for c in grid[0]]
        header = "|".join(heads)
        if section == "album_tracks":
            if "唱片名稱" not in header or "曲目" not in header or "歌名" not in header:
                continue
            fields = ["date_raw", "album_raw", "track_raw", "title", "mv_raw",
                      "composer", "lyricist", "arranger", "producer", "notes"]
        elif section == "singles":
            if "發行日期" not in header or "歌名" not in header:
                continue
            fields = ["date_raw", "title", "composer", "lyricist",
                      "arranger", "producer", "mv_raw", "notes"]
        elif section == "collaborations":
            if "發行日期" not in header or "歌名" not in header:
                continue
            fields = ["date_raw", "title", "with_artist", "composer", "lyricist",
                      "arranger", "producer", "mv_raw", "notes"]
        else:
            if "粵語" not in header or "國語" not in header:
                continue
            fields = ["pair_no", "yue_raw", "en_raw", "cmn_raw"]
        for cells in grid[1:]:
            vals = [short(text(c)) for c in cells]
            if len(vals) < len(fields) - 1:
                continue
            item = {key: (vals[i] if i < len(vals) else "")
                    for i, key in enumerate(fields)}
            if section == "bilingual":
                if not re.fullmatch(r"\d{1,3}", item["pair_no"]):
                    continue
                if not any(item[x] for x in ("yue_raw", "en_raw", "cmn_raw")):
                    continue
                item["pair_no"] = int(item["pair_no"])
                item["relation"] = "wiki_reported_language_variant"
                item["source"] = source
                pairs.append(item)
                continue
            if not item["title"] or not item["date_raw"]:
                continue
            # A year-only entry must not be silently rounded to January 1.
            item["date"] = iso_release_date(item["date_raw"])
            item["source"] = source
            item["identity"] = "unresolved_recording_candidate"
            if section == "album_tracks":
                item["album_title"] = album_title(cells[1])
                item["album_style_raw"] = cells[1].get("style", "") if len(cells) > 1 and cells[1] else ""
                if not item["album_title"]:
                    continue
                track = re.fullmatch(r"(\d+)-(\d+)", item["track_raw"])
                if track:
                    item["disc_no"], item["track_no"] = map(int, track.groups())
                else:
                    item["disc_no"] = 1
                    item["track_no"] = (int(item["track_raw"])
                                        if item["track_raw"].isdigit() else None)
                # Documented Wiki legend: blue album, salmon EP, green compilation.
                color = item["album_style_raw"].lower()
                item["album_kind_hint"] = ("studio_album" if "lightsteelblue" in color
                                           else "ep" if "lightsalmon" in color
                                           else "compilation" if "darkseagreen" in color
                                           else "unknown")
                item["date_semantics"] = "album_listing_date_NOT_confirmed_first_single_release"
                albums.append(item)
            elif section == "singles":
                item["date_semantics"] = "wiki_listed_standalone_single_release"
                singles.append(item)
            else:
                item["date_semantics"] = "wiki_listed_collaboration_release"
                collabs.append(item)
    return albums, singles, collabs, pairs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    snapshots = {}
    for which in PAGES:
        html, revision, title = get_html(which)
        snapshots[which] = {
            "title": title, "revision": revision, "url": SOURCE_URLS[which],
        }
        # HTML snapshots deliberately not committed; only source ID is stored.
        if which == "artist":
            artist = BeautifulSoup(html, "lxml")
        elif which == "songs":
            songpage = BeautifulSoup(html, "lxml")
        else:
            tour = BeautifulSoup(html, "lxml")
    artist_src = "zhwiki:artist:" + snapshots["artist"]["revision"]
    tour_src = "zhwiki:tour:" + snapshots["tour"]["revision"]
    song_src = "zhwiki:songs:" + snapshots["songs"]["revision"]
    albums = parse_releases([t for _, t in section_tables(artist)], artist_src)
    album_tracks, singles, collabs, bilingual = parse_song_lists(songpage, song_src)
    tables = list(section_tables(tour))
    shows = parse_shows([t for s, t in tables if s == "shows"], tour_src)
    encores, encore_nights = parse_encores([t for s, t in tables if s == "encores"], tour_src)
    templates = parse_main_templates(tour, tour_src)
    changes = parse_main_changes(tour, tour_src)
    jsonl(OUT / "releases.jsonl", albums)
    jsonl(OUT / "song_album_tracks.jsonl", album_tracks)
    jsonl(OUT / "song_singles.jsonl", singles)
    jsonl(OUT / "song_collaborations.jsonl", collabs)
    jsonl(OUT / "song_bilingual_versions.jsonl", bilingual)
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
        "song_album_tracks": len(album_tracks), "song_singles": len(singles),
        "song_collaborations": len(collabs), "song_bilingual_pairs": len(bilingual),
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
    if len(album_tracks) < 200 or len(bilingual) < 20:
        report["issues"].append("SONG_LIST_TABLE_PARSE_FAILED")
    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if report["issues"] and any(x.endswith("PARSE_FAILED") or x == "SHOW_COUNT_OR_SEQUENCE_NOT_182" for x in report["issues"]):
        raise SystemExit("Importer incomplete. Preserve report; do not publish as verified.")


if __name__ == "__main__":
    main()
