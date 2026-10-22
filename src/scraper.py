import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_FILE = DATA_DIR / "cache.json"
MAPPINGS_FILE = DATA_DIR / "mappings.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}


def load_mappings() -> dict:
    with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "last_updated": None,
        "openligadb_matches": {},
        "kickbased_season": [],
        "kickbased_players": {},
        "ligainsider_scorers": [],
        "ligainsider_clean_sheets": [],
        "ligainsider_cards": {}
    }


def save_cache(cache: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def fetch_openligadb_matches(season_year: int, cached_matches: dict) -> tuple[dict, bool]:
    """Fetch matchdays 1..34 from OpenLigaDB. Only re-fetch matchdays that are not completely finished."""
    updated = False
    matches_by_md = dict(cached_matches)

    try:
        resp = requests.get(f"https://api.openligadb.de/getmatchdata/bl1/{season_year}", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        all_matches = resp.json()
        grouped = {}
        for m in all_matches:
            md = str(m.get("group", {}).get("groupOrderID", 0))
            grouped.setdefault(md, []).append(m)
        if grouped:
            return grouped, True
    except Exception:
        pass

    for md in range(1, 35):
        md_str = str(md)
        existing = matches_by_md.get(md_str, [])
        if existing and all(m.get("matchIsFinished", False) for m in existing):
            continue
        try:
            url = f"https://api.openligadb.de/getmatchdata/bl1/{season_year}/{md}"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data:
                    matches_by_md[md_str] = data
                    updated = True
        except Exception:
            break

    return matches_by_md, updated


def fetch_kbstats_season(current_max_md: int = 6) -> list[dict]:
    """Fetch all 467 Bundesliga players, their Kickbase season points, and matchday history from api.kbstats.de."""
    teams_resp = requests.get("https://api.kbstats.de/api/v1/teams", headers=HEADERS, timeout=15)
    teams_resp.raise_for_status()
    teams_map = {str(t["id"]): t["name"] for t in teams_resp.json()}

    players_resp = requests.get("https://api.kbstats.de/api/v1/players", headers=HEADERS, timeout=15)
    players_resp.raise_for_status()
    raw_players = players_resp.json()

    players = []
    for p in raw_players:
        full_name = (p.get("name") or f"{p.get('firstName', '')} {p.get('lastName', '')}").strip()
        team_name = teams_map.get(str(p.get("teamId", "")), "")
        total_pts = int(round(float(p.get("totalPoints") or 0)))
        avg_pts = float(p.get("averagePoints") or 0.0)
        mv = int(round(float(p.get("marketValue") or 0)))

        # Map history (ordered from current_max_md backwards: index 0 is current_max_md, index 1 is current_max_md-1, ...)
        md_points = {}
        history = p.get("history") or []
        for idx, h in enumerate(history):
            md_num = current_max_md - idx
            if md_num >= 1 and h.get("hasPlayed") and h.get("points") is not None:
                md_points[str(md_num)] = int(round(float(h["points"])))

        players.append({
            "id": str(p.get("id", "")),
            "name": full_name,
            "name_lower": full_name.lower(),
            "team": team_name,
            "team_lower": team_name.lower(),
            "slug": re.sub(r"[^a-z0-9]+", "-", full_name.lower()).strip("-"),
            "points": total_pts,
            "average": avg_pts,
            "market_value": mv,
            "matchday_points": md_points,
        })

    players.sort(key=lambda x: x["points"], reverse=True)
    return players


def fetch_kickbased_player_matchdays(slug: str) -> dict:
    """Scrape a specific player's per-matchday Kickbase points from kickbased.de."""
    url = f"https://kickbased.de/kickbase-marktwerte/{slug}/"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    matchday_points = {}
    for tr in soup.select("table.seo-table tbody tr"):
        a_tag = tr.find("a", href=re.compile(r"/kickbase-punkte/.*/spieltag-(\d+)/"))
        if not a_tag:
            continue
        m = re.search(r"spieltag-(\d+)", a_tag["href"])
        if not m:
            continue
        md = int(m.group(1))
        tds = tr.find_all("td")
        if len(tds) >= 3:
            pts_txt = tds[-1].get_text(strip=True).replace(".", "")
            try:
                pts = int(pts_txt)
                matchday_points[str(md)] = pts
            except ValueError:
                pass

    return {
        "slug": slug,
        "matchday_points": matchday_points,
        "fetched_at": datetime.now(timezone.utc).isoformat()
    }


def fetch_ligainsider_scorers() -> list[dict]:
    """Scrape Goals, Assists, and Scorer points for all Bundesliga players from Ligainsider."""
    url = "https://www.ligainsider.de/bundesliga/torschuetzenliste/"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    scorers = []
    for row in soup.select("div.leg_column_row"):
        crit_lis = [li.get_text(strip=True) for li in row.select("div[data-criteria-rowfilter] li")]
        team_crit = crit_lis[2] if len(crit_lis) > 2 else ""

        a_tag = row.select_one("div.process_table_column2 a")
        href = a_tag["href"] if a_tag and a_tag.has_attr("href") else ""
        slug = href.strip("/")

        span_first = row.select_one("div.middle_info span")
        strong_last = row.select_one("div.middle_info strong")
        first_name = span_first.get_text(strip=True) if span_first else ""
        last_name = strong_last.get_text(strip=True) if strong_last else ""
        full_name = f"{first_name} {last_name}".strip()

        def get_int(sel: str) -> int:
            el = row.select_one(sel)
            if not el:
                return 0
            txt = el.get_text(strip=True)
            return int(txt) if txt.isdigit() else 0

        goals = get_int("div.process_table_column3")
        assists = get_int("div.process_table_column4")
        scorer_pts = get_int("div.process_table_column5")
        appearances = get_int("div.process_table_column6")

        scorers.append({
            "name": full_name,
            "last_name": last_name,
            "slug": slug,
            "team_key": team_crit,
            "goals": goals,
            "assists": assists,
            "scorer": scorer_pts,
            "appearances": appearances
        })

    return scorers


def fetch_ligainsider_clean_sheets() -> list[dict]:
    """Scrape goalkeeper clean sheets (Weiße Weste) from Ligainsider."""
    url = "https://www.ligainsider.de/bundesliga/ranking-top-10/weisse-weste/"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    keepers = []
    for tr in soup.select("table#DataTable tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 8:
            continue
        a_player = tds[2].find("a")
        name = a_player.get_text(strip=True) if a_player else tds[2].get_text(strip=True)
        slug = a_player["href"].strip("/") if a_player and a_player.has_attr("href") else ""
        team = tds[3].get_text(strip=True)

        def to_int(val: str) -> int:
            v = val.strip()
            return int(v) if v.isdigit() else 0

        appearances = to_int(tds[5].get_text())
        minutes = to_int(tds[6].get_text())
        clean_sheets = to_int(tds[7].get_text())

        keepers.append({
            "name": name,
            "slug": slug,
            "team": team,
            "appearances": appearances,
            "minutes": minutes,
            "clean_sheets": clean_sheets
        })

    return keepers


def fetch_ligainsider_all_cards(team_paths: list[str]) -> dict:
    """Scrape yellow, yellow-red, and red cards for all Bundesliga players across the 18 team kader pages."""
    cards_by_player = {}

    for path in team_paths:
        url = f"https://www.ligainsider.de{path}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for row in soup.select("div.leg_column_row"):
                info_box = row.select_one("div.middle_info_box.firstname")
                if not info_box:
                    continue
                a_tag = info_box.find("a")
                slug = a_tag["href"].strip("/") if a_tag and a_tag.has_attr("href") else ""
                span_f = info_box.find("span")
                strong_l = info_box.find("strong")
                first = span_f.get_text(strip=True) if span_f else ""
                last = strong_l.get_text(strip=True) if strong_l else ""
                full_name = f"{first} {last}".strip()

                def parse_col_int(col_class: str) -> int:
                    col = row.select_one(f"div.{col_class} div.middle_icon_box span")
                    if not col:
                        return 0
                    txt = col.get_text(strip=True)
                    return int(txt) if txt.isdigit() else 0

                appearances = parse_col_int("process_inner_column8")
                goals = parse_col_int("process_inner_column9")
                assists = parse_col_int("process_inner_column10")
                yellow = parse_col_int("process_inner_column11")
                yellow_red = parse_col_int("process_inner_column12")
                red = parse_col_int("process_inner_column13")

                entry = {
                    "name": full_name,
                    "last_name": last,
                    "slug": slug,
                    "team_path": path,
                    "appearances": appearances,
                    "goals": goals,
                    "assists": assists,
                    "yellow_cards": yellow,
                    "yellow_red_cards": yellow_red,
                    "red_cards": red
                }
                if slug:
                    cards_by_player[slug] = entry
                cards_by_player[full_name.lower()] = entry
        except Exception:
            continue

    return cards_by_player


def update_all_data(force: bool = False, min_interval_minutes: int = 15) -> tuple[dict, str]:
    """
    Incremental scraper with timestamp check so not everything is re-scraped unnecessarily.
    Returns (cache_dict, status_message).
    """
    cache = load_cache()
    mappings = load_mappings()
    now = datetime.now(timezone.utc)

    last_updated_str = cache.get("last_updated")
    if not force and last_updated_str:
        try:
            last_dt = datetime.fromisoformat(last_updated_str)
            elapsed_min = (now - last_dt).total_seconds() / 60.0
            if elapsed_min < min_interval_minutes:
                return cache, f"Daten sind aktuell (zuletzt aktualisiert vor {int(elapsed_min)} Min.)."
        except Exception:
            pass

    # Check OpenLigaDB lastchange timestamp to see if match data changed
    matches_by_md, _ = fetch_openligadb_matches(
        mappings["season_year"], cache.get("openligadb_matches", {})
    )
    cache["openligadb_matches"] = matches_by_md

    # Determine highest finished/active matchday
    active_mds = []
    for md_str, m_list in matches_by_md.items():
        if any(m.get("matchIsFinished") or m.get("matchResults") for m in m_list):
            active_mds.append(int(md_str))
    current_max_md = max(active_mds) if active_mds else 0

    # Fetch Kickbase season overview & matchday history from kbstats.de API
    try:
        cache["kickbased_season"] = fetch_kbstats_season(current_max_md=current_max_md or 6)
    except Exception as e:
        print(f"Warning: fetch_kbstats_season failed: {e}")

    # Also merge per-matchday history from kbstats_season into kickbased_players
    kb_players = cache.get("kickbased_players", {})
    for p in cache.get("kickbased_season", []):
        slug = p.get("slug")
        if slug and p.get("matchday_points"):
            existing_md = kb_players.get(slug, {}).get("matchday_points", {})
            merged_md = {**existing_md, **p["matchday_points"]}
            kb_players[slug] = {
                "slug": slug,
                "matchday_points": merged_md,
                "fetched_at": now.isoformat()
            }
    cache["kickbased_players"] = kb_players

    # Scrape Ligainsider Scorers & Clean Sheets
    try:
        cache["ligainsider_scorers"] = fetch_ligainsider_scorers()
    except Exception as e:
        print(f"Warning: fetch_ligainsider_scorers failed: {e}")

    try:
        cache["ligainsider_clean_sheets"] = fetch_ligainsider_clean_sheets()
    except Exception as e:
        print(f"Warning: fetch_ligainsider_clean_sheets failed: {e}")

    # Scrape Ligainsider Team Kader pages for Yellow/Red cards
    try:
        cards = fetch_ligainsider_all_cards(mappings["ligainsider_team_paths"])
        if cards:
            cache["ligainsider_cards"] = cards
    except Exception as e:
        print(f"Warning: fetch_ligainsider_all_cards failed: {e}")

    cache["last_updated"] = now.isoformat()
    cache["current_matchday"] = current_max_md
    save_cache(cache)
    return cache, f"Daten erfolgreich aktualisiert ({now.astimezone().strftime('%d.%m.%Y %H:%M:%S')})."
