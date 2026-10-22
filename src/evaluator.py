import csv
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CSV_FILE = DATA_DIR / "bingo_answers.csv"
MAPPINGS_FILE = DATA_DIR / "mappings.json"
MANUAL_FILE = DATA_DIR / "manual_events.json"

PLAYERS = ["Denny", "Tom", "Jörg", "Robert"]


def load_bingo_csv() -> list[dict]:
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_manual_events() -> dict:
    if MANUAL_FILE.exists():
        try:
            with open(MANUAL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_manual_events(data: dict) -> None:
    with open(MANUAL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_bayern(team_str: str) -> bool:
    t = (team_str or "").lower()
    return "bayern" in t or "münchen" in t or "munchen" in t


def get_final_score(match: dict) -> tuple[int, int] | None:
    if not match.get("matchIsFinished"):
        return None
    results = match.get("matchResults", [])
    if not results:
        return None
    # Endergebnis usually has resultTypeID == 2 or highest resultOrderID
    end_res = sorted(results, key=lambda r: r.get("resultTypeID", 0), reverse=True)[0]
    return int(end_res.get("pointsTeam1", 0)), int(end_res.get("pointsTeam2", 0))


def did_comeback_two_goals(match: dict, team_is_team1: bool) -> tuple[bool, str]:
    """
    Check if a team trailed by >= 2 goals at any point in the match and ended up drawing or winning.
    """
    score = get_final_score(match)
    if score is None:
        return False, ""
    ft1, ft2 = score
    team_final = ft1 if team_is_team1 else ft2
    opp_final = ft2 if team_is_team1 else ft1
    if team_final < opp_final:
        return False, ""

    goals = sorted(match.get("goals", []), key=lambda g: (g.get("matchMinute") or 0, g.get("goalID") or 0))
    max_deficit = 0
    for g in goals:
        s1 = int(g.get("scoreTeam1", 0))
        s2 = int(g.get("scoreTeam2", 0))
        t_score = s1 if team_is_team1 else s2
        o_score = s2 if team_is_team1 else s1
        deficit = o_score - t_score
        if deficit > max_deficit:
            max_deficit = deficit

    if max_deficit >= 2:
        opp_name = match["team2"]["shortName"] if team_is_team1 else match["team1"]["shortName"]
        md = match.get("group", {}).get("groupOrderID", "?")
        return True, f"{ft1}:{ft2} vs. {opp_name} (ST {md})"
    return False, ""


def compute_team_stats(cache: dict, mappings: dict, start_md: int = 4) -> dict:
    """
    Compute per-team statistics from OpenLigaDB matches.
    - Long-term season totals (all matchdays >= 1):
      goals_conceded_season
    - Series & Single-match events (only from start_md onwards, i.e. from Matchday 5):
      current_unbeaten, max_unbeaten, current_wins, max_wins,
      lost_to_paderborn, lost_by_5, comeback_2
    """
    matches_by_md = cache.get("openligadb_matches", {})
    stats = {}

    def ensure_team(t_name: str):
        if t_name not in stats:
            stats[t_name] = {
                "goals_conceded_season": 0,
                "goals_conceded_from_md": 0,
                "current_unbeaten": 0,
                "max_unbeaten": 0,
                "current_wins": 0,
                "max_wins": 0,
                "lost_to_paderborn": False,
                "paderborn_match_info": "Offen",
                "lost_by_5": False,
                "max_loss_margin": 0,
                "comeback_2": False,
                "comeback_info": []
            }

    for md in sorted(matches_by_md.keys(), key=lambda x: int(x)):
        md_num = int(md)
        for m in matches_by_md[md]:
            t1 = m.get("team1", {}).get("teamName", "")
            t2 = m.get("team2", {}).get("teamName", "")
            if not t1 or not t2:
                continue
            ensure_team(t1)
            ensure_team(t2)

            score = get_final_score(m)
            if score is None:
                if md_num >= start_md:
                    if "Paderborn" in t1 and stats[t2]["paderborn_match_info"] == "Offen":
                        stats[t2]["paderborn_match_info"] = f"Nächstes Spiel: ST {md_num}"
                    elif "Paderborn" in t2 and stats[t1]["paderborn_match_info"] == "Offen":
                        stats[t1]["paderborn_match_info"] = f"Nächstes Spiel: ST {md_num}"
                continue

            s1, s2 = score
            stats[t1]["goals_conceded_season"] += s2
            stats[t2]["goals_conceded_season"] += s1

            # Series (5 unbeaten, 4 wins) and single-match events only count from start_md (Matchday 5)
            if md_num < start_md:
                continue

            stats[t1]["goals_conceded_from_md"] += s2
            stats[t2]["goals_conceded_from_md"] += s1

            for team_name, my_s, opp_s, opp_name, is_t1 in [
                (t1, s1, s2, t2, True),
                (t2, s2, s1, t1, False)
            ]:
                st = stats[team_name]
                if my_s > opp_s:
                    st["current_wins"] += 1
                    st["current_unbeaten"] += 1
                elif my_s == opp_s:
                    st["current_wins"] = 0
                    st["current_unbeaten"] += 1
                else:
                    st["current_wins"] = 0
                    st["current_unbeaten"] = 0
                    margin = opp_s - my_s
                    if margin > st["max_loss_margin"]:
                        st["max_loss_margin"] = margin
                    if margin >= 5:
                        st["lost_by_5"] = True

                if st["current_wins"] > st["max_wins"]:
                    st["max_wins"] = st["current_wins"]
                if st["current_unbeaten"] > st["max_unbeaten"]:
                    st["max_unbeaten"] = st["current_unbeaten"]

                if "Paderborn" in opp_name:
                    if my_s < opp_s:
                        st["lost_to_paderborn"] = True
                        st["paderborn_match_info"] = f"Verloren ({my_s}:{opp_s}, ST {md_num})"
                    else:
                        st["paderborn_match_info"] = f"{my_s}:{opp_s} (ST {md_num})"

                cb, cb_str = did_comeback_two_goals(m, is_t1)
                if cb:
                    st["comeback_2"] = True
                    st["comeback_info"].append(cb_str)

    return stats


def find_player_stat(alias_key: str, cache: dict, mappings: dict) -> dict:
    """Aggregate all available stats for a named player from Kickbased + Ligainsider + OpenLigaDB."""
    p_map = mappings.get("player_aliases", {}).get(alias_key, {})
    full_name = p_map.get("name", alias_key)
    kb_slug = p_map.get("kickbased_slug", "")
    li_slug = p_map.get("ligainsider_slug", "")
    team = p_map.get("team", "")

    # 1. Kickbase season points
    kb_points = 0
    kb_avg = 0.0
    for p in cache.get("kickbased_season", []):
        if (kb_slug and p.get("slug") == kb_slug) or p.get("name", "").lower() == full_name.lower():
            kb_points = p.get("points", 0)
            kb_avg = p.get("average", 0.0)
            break

    # 2. Kickbase per-matchday points
    kb_md_pts = cache.get("kickbased_players", {}).get(kb_slug, {}).get("matchday_points", {})

    # 3. Goals, Assists, Scorer from Ligainsider (or fallback to cards table)
    goals = 0
    assists = 0
    scorer = 0
    found_scorer = False
    for s in cache.get("ligainsider_scorers", []):
        if (li_slug and s.get("slug") == li_slug) or s.get("name", "").lower() == full_name.lower():
            goals = s.get("goals", 0)
            assists = s.get("assists", 0)
            scorer = s.get("scorer", goals + assists)
            found_scorer = True
            break

    # 4. Yellow & Red cards from Ligainsider team kader pages
    cards_dict = cache.get("ligainsider_cards", {})
    c_entry = cards_dict.get(li_slug) or cards_dict.get(full_name.lower()) or {}
    if not found_scorer and c_entry:
        goals = c_entry.get("goals", 0)
        assists = c_entry.get("assists", 0)
        scorer = goals + assists

    yellow_cards = c_entry.get("yellow_cards", 0)
    yellow_red_cards = c_entry.get("yellow_red_cards", 0)
    red_cards = c_entry.get("red_cards", 0)

    # 5. Clean sheets
    clean_sheets = 0
    for k in cache.get("ligainsider_clean_sheets", []):
        if (li_slug and k.get("slug") == li_slug) or k.get("name", "").lower() == full_name.lower() or alias_key.lower() in k.get("name", "").lower():
            clean_sheets = k.get("clean_sheets", 0)
            break

    # Fallback fuzzy search if alias wasn't in mappings.json
    if not p_map:
        q = alias_key.lower().strip()
        for p in cache.get("kickbased_season", []):
            if q in p.get("name_lower", ""):
                full_name = p["name"]
                kb_points = p.get("points", 0)
                kb_avg = p.get("average", 0.0)
                break
        for k, v in cards_dict.items():
            if q in k:
                goals = v.get("goals", 0)
                assists = v.get("assists", 0)
                scorer = goals + assists
                yellow_cards = v.get("yellow_cards", 0)
                yellow_red_cards = v.get("yellow_red_cards", 0)
                red_cards = v.get("red_cards", 0)
                break

    return {
        "alias": alias_key,
        "name": full_name,
        "team": team,
        "kb_points": kb_points,
        "kb_avg": kb_avg,
        "kb_matchday_points": kb_md_pts,
        "goals": goals,
        "assists": assists,
        "scorer": scorer,
        "yellow_cards": yellow_cards,
        "yellow_red_cards": yellow_red_cards,
        "red_cards": red_cards,
        "clean_sheets": clean_sheets
    }


def detect_hattricks(cache: dict, start_md: int = 4) -> dict[str, list[str]]:
    """Scan OpenLigaDB match goals to see if any player scored >= 3 goals in a single match."""
    hattricks = {}
    matches_by_md = cache.get("openligadb_matches", {})
    for md_str, m_list in matches_by_md.items():
        md_num = int(md_str)
        if md_num < start_md:
            continue
        for m in m_list:
            counts = {}
            for g in m.get("goals", []):
                if g.get("isOwnGoal"):
                    continue
                scorer_name = (g.get("goalGetterName") or "").strip()
                if scorer_name:
                    counts[scorer_name] = counts.get(scorer_name, 0) + 1
            for scorer_name, cnt in counts.items():
                if cnt >= 3:
                    hattricks.setdefault(scorer_name, []).append(f"{cnt} Tore (ST {md_num})")
    return hattricks


def evaluate_all(cache: dict, start_md: int = 4) -> dict:
    """
    Evaluate all 16 bingo categories, player progress, top non-Bayern leaders, and 4x4 grids.
    """
    mappings = json.loads(MAPPINGS_FILE.read_text(encoding="utf-8"))
    rows = load_bingo_csv()
    manual = load_manual_events()
    team_stats = compute_team_stats(cache, mappings, start_md=start_md)
    hattricks = detect_hattricks(cache, start_md=start_md)

    # Top non-Bayern leaders
    non_bayern_scorers = [
        s for s in cache.get("ligainsider_scorers", [])
        if not is_bayern(s.get("team_key", ""))
    ]
    non_bayern_scorers_by_scorer = sorted(non_bayern_scorers, key=lambda x: (x["scorer"], x["goals"]), reverse=True)
    non_bayern_scorers_by_goals = sorted(non_bayern_scorers, key=lambda x: (x["goals"], x["scorer"]), reverse=True)

    top_scorer_no_fcb = non_bayern_scorers_by_scorer[0] if non_bayern_scorers_by_scorer else {"name": "-", "team_key": "", "scorer": 0, "goals": 0, "assists": 0}
    top_goalgetter_no_fcb = non_bayern_scorers_by_goals[0] if non_bayern_scorers_by_goals else {"name": "-", "team_key": "", "goals": 0}

    non_bayern_kb = [
        p for p in cache.get("kickbased_season", [])
        if not is_bayern(p.get("team_lower", "")) and not is_bayern(p.get("team", ""))
    ]
    non_bayern_kb.sort(key=lambda x: x["points"], reverse=True)
    top_kb_no_fcb = non_bayern_kb[0] if non_bayern_kb else {"name": "-", "team": "-", "points": 0}

    abbr_map = mappings.get("team_abbreviations", {})
    top_scorer_abbr = abbr_map.get(top_scorer_no_fcb.get("team_key", ""), "")
    top_scorer_display = f"{top_scorer_no_fcb['name']} ({top_scorer_abbr})" if top_scorer_abbr else top_scorer_no_fcb["name"]

    top_goalgetter_abbr = abbr_map.get(top_goalgetter_no_fcb.get("team_key", ""), "")
    top_goalgetter_display = f"{top_goalgetter_no_fcb['name']} ({top_goalgetter_abbr})" if top_goalgetter_abbr else top_goalgetter_no_fcb["name"]

    top_kb_abbr = abbr_map.get(top_kb_no_fcb.get("team", ""), top_kb_no_fcb.get("team", ""))
    top_kb_display = f"{top_kb_no_fcb['name']} ({top_kb_abbr})" if top_kb_abbr else top_kb_no_fcb["name"]

    category_summaries = []
    player_cards = {p: {} for p in PLAYERS}

    for row in rows:
        cat = row["Kategorie"]
        cat_detail = {
            "category": cat,
            "leader_info": None,
            "entries": {}
        }

        if cat == "Spieler XYZ erzielt die meisten Scorer":
            cat_detail["leader_info"] = (
                f"Top-Scorer (ohne Bayern): {top_scorer_display} – "
                f"{top_scorer_no_fcb['scorer']} Scorer ({top_scorer_no_fcb['goals']} Tore, {top_scorer_no_fcb['assists']} Vorlagen)"
            )
        elif cat == "Spieler XYZ hat am Ende der Saison die meisten Punkte in Kickbase":
            cat_detail["leader_info"] = (
                f"Top-Punktesammler (ohne Bayern): {top_kb_display} – "
                f"{top_kb_no_fcb['points']} Pkt."
            )
        elif cat == "Spieler XYZ schießt mind. 15 Tore":
            cat_detail["leader_info"] = (
                f"Top-Torjäger (ohne Bayern): {top_goalgetter_display} – "
                f"{top_goalgetter_no_fcb['goals']} Tore"
            )

        for p_name in PLAYERS:
            ans = row[p_name]
            pos = row[f"{p_name}_Pos"]
            completed = False
            status_text = ""
            sub_text = ""

            # 1. Verein XYZ bleibt fünf Spiele in Folge ungeschlagen
            if cat == "Verein XYZ bleibt fünf Spiele in Folge ungeschlagen":
                t_full = mappings["team_aliases"].get(ans, ans)
                st = team_stats.get(t_full, {})
                cur_u = st.get("current_unbeaten", 0)
                max_u = st.get("max_unbeaten", 0)
                completed = max_u >= 5
                status_text = f"Aktuell: {cur_u}/5 (Max: {max_u})"
                sub_text = f"Ungeschlagen-Serie: {cur_u}"

            # 2. Verein XYZ verliert gegen Paderborn
            elif cat == "Verein XYZ verliert gegen Paderborn":
                t_full = mappings["team_aliases"].get(ans, ans)
                st = team_stats.get(t_full, {})
                completed = st.get("lost_to_paderborn", False)
                status_text = st.get("paderborn_match_info", "Offen")
                sub_text = status_text

            # 3. Spieler XYZ erzielt die meisten Scorer (ohne Bayern)
            elif cat == "Spieler XYZ erzielt die meisten Scorer":
                ps = find_player_stat(ans, cache, mappings)
                top_val = top_scorer_no_fcb["scorer"]
                completed = top_val > 0 and ps["scorer"] >= top_val
                status_text = f"{ps['scorer']} Scorer ({ps['goals']}T/{ps['assists']}V)"
                sub_text = f"Top (o. FCB): {top_scorer_display} ({top_val})"

            # 4. Spieler XYZ kassiert eine Gelbsperre (5 Gelbe Karten)
            elif cat == "Spieler XYZ kassiert eine Gelbsperre":
                ps = find_player_stat(ans, cache, mappings)
                yc = ps["yellow_cards"]
                completed = yc >= 5
                status_text = f"{yc} / 5 Gelbe Karten"
                sub_text = status_text

            # 5. Spieler XYZ macht über 300 Punkte in einem Spiel
            elif cat == "Spieler XYZ macht über 300 Punkte in einem Spiel":
                ps = find_player_stat(ans, cache, mappings)
                md_pts = {int(k): v for k, v in ps["kb_matchday_points"].items() if int(k) >= start_md}
                max_pts = max(md_pts.values()) if md_pts else 0
                best_md = max(md_pts, key=md_pts.get) if md_pts else "-"
                completed = max_pts > 300
                status_text = f"Bestwert: {max_pts} Pkt. (ST {best_md})" if md_pts else "Bestwert: 0 Pkt."
                sub_text = f"Max (ab ST {start_md}): {max_pts}/300"

            # 6. Trainer XYZ muss auf die Tribüne
            elif cat == "Trainer XYZ muss auf die Tribüne":
                completed = bool(manual.get(cat, {}).get(ans, False))
                status_text = "Erfüllt (Manuell)" if completed else "Offen"
                sub_text = status_text

            # 7. Keeper XYZ behält achtmal eine weiße Weste
            elif cat == "Keeper XYZ behält achtmal eine weiße Weste":
                ps = find_player_stat(ans, cache, mappings)
                cs = ps["clean_sheets"]
                completed = cs >= 8
                status_text = f"{cs} / 8 Weiße Westen"
                sub_text = status_text

            # 8. Spieler XYZ hat am Ende der Saison die meisten Punkte in Kickbase (ohne Bayern)
            elif cat == "Spieler XYZ hat am Ende der Saison die meisten Punkte in Kickbase":
                ps = find_player_stat(ans, cache, mappings)
                top_val = top_kb_no_fcb["points"]
                completed = top_val > 0 and ps["kb_points"] >= top_val
                status_text = f"{ps['kb_points']} Pkt. (Ø {ps['kb_avg']})"
                sub_text = f"Top (o. FCB): {top_kb_display} ({top_val})"

            # 9. Spieler XYZ schießt einen Dreierpack
            elif cat == "Spieler XYZ schießt einen Dreierpack":
                ps = find_player_stat(ans, cache, mappings)
                last_n = ps["name"].split()[-1].lower()
                matched_ht = []
                for ht_scorer, ht_info in hattricks.items():
                    if last_n in ht_scorer.lower():
                        matched_ht.extend(ht_info)
                completed = len(matched_ht) > 0
                status_text = ", ".join(matched_ht) if completed else f"Noch kein Dreierpack ({ps['goals']} Saisontore)"
                sub_text = status_text

            # 10. Spieler XYZ schießt mind. 15 Tore
            elif cat == "Spieler XYZ schießt mind. 15 Tore":
                ps = find_player_stat(ans, cache, mappings)
                g = ps["goals"]
                completed = g >= 15
                status_text = f"{g} / 15 Tore"
                sub_text = f"Top (o. FCB): {top_goalgetter_display} ({top_goalgetter_no_fcb['goals']})"

            # 11. Verein XYZ kassiert mind. 60 Gegentore
            elif "kassiert mind. 60 Gegentore" in cat:
                t_full = mappings["team_aliases"].get(ans, ans)
                st = team_stats.get(t_full, {})
                ga = st.get("goals_conceded_season", 0)
                completed = ga >= 60
                status_text = f"{ga} / 60 Gegentore"
                sub_text = status_text

            # 12. Spieler XYZ kassiert einen Platzverweis
            elif cat == "Spieler XYZ kassiert einen Platzverweis":
                ps = find_player_stat(ans, cache, mappings)
                sent_off = ps["yellow_red_cards"] + ps["red_cards"]
                completed = sent_off > 0
                status_text = f"{sent_off} Platzverweis(e) ({ps['yellow_red_cards']} GR, {ps['red_cards']} R)"
                sub_text = f"Platzverweise: {sent_off}"

            # 13. Verein XYZ verliert mit fünf Toren unterschied
            elif cat == "Verein XYZ verliert mit fünf Toren unterschied":
                t_full = mappings["team_aliases"].get(ans, ans)
                st = team_stats.get(t_full, {})
                completed = st.get("lost_by_5", False)
                max_m = st.get("max_loss_margin", 0)
                status_text = f"Max. Niederlage: {max_m} Tore Differenz"
                sub_text = f"Max Diff: {max_m}/5 Tore"

            # 14. Verein XYZ gewinnt vier Spiele in Folge
            elif cat == "Verein XYZ gewinnt vier Spiele in Folge":
                t_full = mappings["team_aliases"].get(ans, ans)
                st = team_stats.get(t_full, {})
                cur_w = st.get("current_wins", 0)
                max_w = st.get("max_wins", 0)
                completed = max_w >= 4
                status_text = f"Aktuell: {cur_w}/4 Siege (Max: {max_w})"
                sub_text = f"Siegesserie: {cur_w}/4"

            # 15. Verein XYZ holt einen Zwei-Tore-Rückstand auf
            elif cat == "Verein XYZ holt einen Zwei-Tore-Rückstand auf":
                t_full = mappings["team_aliases"].get(ans, ans)
                st = team_stats.get(t_full, {})
                completed = st.get("comeback_2", False)
                cb_list = st.get("comeback_info", [])
                status_text = ", ".join(cb_list) if cb_list else "Noch kein 2-Tore-Comeback"
                sub_text = status_text

            # 16. Trainer XYZ wird entlassen
            elif cat == "Trainer XYZ wird entlassen":
                completed = bool(manual.get(cat, {}).get(ans, False))
                status_text = "Entlassen (Manuell)" if completed else "Im Amt"
                sub_text = status_text

            # Check manual override if user toggled any cell manually
            override_key = f"{p_name}::{cat}"
            if override_key in manual.get("custom_overrides", {}):
                completed = bool(manual["custom_overrides"][override_key])

            cell_data = {
                "category": cat,
                "answer": ans,
                "pos": pos,
                "completed": completed,
                "status_text": status_text,
                "sub_text": sub_text
            }
            player_cards[p_name][pos] = cell_data
            cat_detail["entries"][p_name] = cell_data

        category_summaries.append(cat_detail)

    # Calculate Bingo lines (rows, cols, diagonals) for each player
    bingo_results = {}
    for p_name in PLAYERS:
        grid = player_cards[p_name]
        lines = []
        for r in range(1, 5):
            if all(grid.get(f"R{r}C{c}", {}).get("completed", False) for c in range(1, 5)):
                lines.append(f"Reihe {r}")
        for c in range(1, 5):
            if all(grid.get(f"R{r}C{c}", {}).get("completed", False) for r in range(1, 5)):
                lines.append(f"Spalte {c}")
        if all(grid.get(f"R{i}C{i}", {}).get("completed", False) for i in range(1, 5)):
            lines.append("Diagonale ↘")
        if all(grid.get(f"R{i}C{5-i}", {}).get("completed", False) for i in range(1, 5)):
            lines.append("Diagonale ↙")

        completed_count = sum(1 for cell in grid.values() if cell.get("completed", False))
        bingo_results[p_name] = {
            "completed_count": completed_count,
            "bingo_lines": lines,
            "has_bingo": len(lines) > 0
        }

    return {
        "category_summaries": category_summaries,
        "player_cards": player_cards,
        "bingo_results": bingo_results,
        "top_scorer_no_fcb": top_scorer_no_fcb,
        "top_goalgetter_no_fcb": top_goalgetter_no_fcb,
        "top_kb_no_fcb": top_kb_no_fcb,
        "team_stats": team_stats
    }
