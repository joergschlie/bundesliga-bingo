from datetime import datetime
import pandas as pd
import streamlit as st
from src.scraper import load_cache, load_mappings, update_all_data
from src.evaluator import (
    PLAYERS,
    evaluate_all,
    load_manual_events,
    save_manual_events,
)

st.set_page_config(
    page_title="Bundesliga & Kickbase Bingo 2026/27",
    page_icon="⚽",
    layout="wide",
)

# --- Password Gate (Option 1) ---
def check_password() -> bool:
    """Returns True if user enters the correct password."""
    if st.session_state.get("authenticated", False):
        return True

    expected_password = st.secrets.get("APP_PASSWORD", "")
    # If no password configured in secrets, allow access (e.g. local dev fallback)
    if not expected_password:
        return True

    st.subheader("🔒 Bundesliga & Kickbase Bingo")
    pwd = st.text_input("Passwort eingeben:", type="password", key="password_input")
    if st.button("Einloggen", width="content"):
        if pwd == expected_password:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Ungültiges Passwort. Bitte erneut versuchen.")
    return False

if not check_password():
    st.stop()


st.markdown(
    """
    <style>
    .bingo-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 10px;
        margin-bottom: 24px;
    }
    .bingo-cell {
        border-radius: 10px;
        padding: 12px;
        min-height: 135px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        border: 2px solid #334155;
        background-color: #1e293b;
        color: #f8fafc;
        box-shadow: 0 2px 6px rgba(0,0,0,0.25);
    }
    .bingo-cell.completed {
        border-color: #22c55e;
        background: linear-gradient(145deg, #14532d, #166534);
        color: #f0fdf4;
    }
    .bingo-cat {
        font-size: 0.75rem;
        opacity: 0.85;
        line-height: 1.2;
        margin-bottom: 6px;
    }
    .bingo-ans {
        font-size: 1.05rem;
        font-weight: 700;
        margin-bottom: 6px;
        color: #38bdf8;
    }
    .bingo-cell.completed .bingo-ans {
        color: #86efac;
    }
    .bingo-stat {
        font-size: 0.8rem;
        font-weight: 600;
        padding-top: 6px;
        border-top: 1px solid rgba(255,255,255,0.15);
    }
    .leader-badge {
        background-color: #0f172a;
        border-left: 4px solid #f59e0b;
        padding: 8px 12px;
        border-radius: 4px;
        margin-bottom: 8px;
        font-size: 0.9rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("⚽ Bundesliga & Kickbase Bingo-Tracker (Saison 2026/27)")
st.caption("1. Bundesliga · Serien & Einzel-Events ab 4. Spieltag · Langzeit-Stats über gesamte Saison · FC Bayern München ausgeschlossen")

# Sidebar controls
with st.sidebar:
    st.header("🔄 Daten & Einstellungen")
    cache = load_cache()
    last_upd = cache.get("last_updated")
    if last_upd:
        try:
            dt_local = datetime.fromisoformat(last_upd).astimezone()
            st.info(f"**Letztes Scraping:**\n{dt_local.strftime('%d.%m.%Y um %H:%M:%S Uhr')}\n\n**Aktueller Spieltag:** {cache.get('current_matchday', '?')}")
        except Exception:
            st.info(f"Letztes Scraping: {last_upd}")
    else:
        st.warning("Noch keine Daten im Cache.")

    min_interval = st.number_input(
        "Mindestintervall für Auto-Update (Minuten)",
        min_value=1,
        max_value=1440,
        value=30,
        step=5,
        help="Verhindert unnötiges erneutes Scrapen, wenn der Zeitstempel noch frisch ist."
    )

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔄 Update prüfen", width="stretch"):
            with st.spinner("Prüfe Zeitstempel & aktualisiere Daten..."):
                cache, msg = update_all_data(force=False, min_interval_minutes=int(min_interval))
                st.success(msg)
                st.rerun()
    with col_btn2:
        if st.button("⚡ Erzwingen", width="stretch"):
            with st.spinner("Scrape OpenLigaDB, KBStats & Ligainsider..."):
                cache, msg = update_all_data(force=True)
                st.success(msg)
                st.rerun()

    st.divider()
    start_md = st.slider(
        "Serien & Einzel-Events zählen ab Spieltag:",
        min_value=1,
        max_value=10,
        value=4,
        help="Serien (5 ungeschlagen, 4 Siege in Folge) und Einzel-Events (>300 Pkt., Dreierpack, 2-Tore-Comeback, 5-Tore-Niederlage, Paderborn-Niederlage) zählen ab Spieltag 4. Langzeit-Statistiken zählen über die gesamte Saison."
    )

# Auto-initialize cache if empty
if not cache.get("last_updated"):
    with st.spinner("Initialisiere Daten beim ersten Start..."):
        cache, _ = update_all_data(force=True)

eval_data = evaluate_all(cache, start_md=start_md)

# Top summary metrics per player
cols = st.columns(4)
for idx, p_name in enumerate(PLAYERS):
    b_res = eval_data["bingo_results"][p_name]
    with cols[idx]:
        bingo_str = f"🎉 BINGO ({', '.join(b_res['bingo_lines'])})" if b_res["has_bingo"] else "Noch kein Bingo"
        st.metric(
            label=f"👤 {p_name}",
            value=f"{b_res['completed_count']} / 16 Felder",
            delta=bingo_str,
            delta_color="normal" if b_res["has_bingo"] else "off",
        )

tab_cards, tab_rules, tab_leaders, tab_manual = st.tabs([
    "🎯 Bingo-Scheine (4×4)",
    "📊 Alle 16 Regeln & Fortschritt",
    "🏆 Bundesliga & Kickbase Rankings (ohne Bayern)",
    "⚙️ Manuelle Events (Trainer / Overrides)"
])

with tab_cards:
    st.subheader("4×4 Bingo-Scheine nach Spieler")
    card_cols = st.columns(2)
    for idx, p_name in enumerate(PLAYERS):
        with card_cols[idx % 2]:
            b_res = eval_data["bingo_results"][p_name]
            badge = f" — 🏆 **{', '.join(b_res['bingo_lines'])}**" if b_res["has_bingo"] else ""
            st.markdown(f"### {p_name} ({b_res['completed_count']}/16){badge}")

            grid = eval_data["player_cards"][p_name]
            cells_html = ['<div class="bingo-grid">']
            for r in range(1, 5):
                for c in range(1, 5):
                    pos_key = f"R{r}C{c}"
                    cell = grid.get(pos_key, {})
                    done_cls = "completed" if cell.get("completed") else ""
                    icon = "✅" if cell.get("completed") else "⏳"
                    cat_txt = cell.get("category", "")
                    ans_txt = cell.get("answer", "")
                    stat_txt = cell.get("status_text", "")
                    cells_html.append(
                        f'<div class="bingo-cell {done_cls}">'
                        f'  <div>'
                        f'    <div class="bingo-cat">{pos_key} · {cat_txt}</div>'
                        f'    <div class="bingo-ans">{icon} {ans_txt}</div>'
                        f'  </div>'
                        f'  <div class="bingo-stat">{stat_txt}</div>'
                        f'</div>'
                    )
            cells_html.append("</div>")
            st.markdown("".join(cells_html), unsafe_allow_html=True)

with tab_rules:
    st.subheader("Detaillierte Auswertung aller 16 Kategorien")
    for cs in eval_data["category_summaries"]:
        cat_name = cs["category"]
        with st.expander(f"**{cat_name}**", expanded=True):
            if cs["leader_info"]:
                st.markdown(f'<div class="leader-badge">🥇 <strong>{cs["leader_info"]}</strong></div>', unsafe_allow_html=True)
            r_cols = st.columns(4)
            for idx, p_name in enumerate(PLAYERS):
                entry = cs["entries"][p_name]
                icon = "✅" if entry["completed"] else "❌"
                with r_cols[idx]:
                    st.markdown(f"**{p_name}** (`{entry['pos']}`)")
                    st.markdown(f"{icon} **{entry['answer']}**")
                    st.caption(entry["status_text"])

with tab_leaders:
    st.subheader("Top-Listen der 1. Bundesliga 2026/27 (FC Bayern München ausgeschlossen)")
    st.caption("🔹 Hellblau hinterlegte Zeilen markieren die 4 Spieler, die in der jeweiligen Kategorie auf den Bingo-Scheinen getippt wurden.")
    mappings_cfg = load_mappings()
    abbr_map = mappings_cfg.get("team_abbreviations", {})
    alias_map = mappings_cfg.get("team_aliases", {})

    # Category-specific 4 picked players
    kb_picked = {"Antonio Nusa (RBL)", "David Raum (RBL)", "Aleix García (B04)", "Fabian Rieder (FCA)"}
    scorer_picked = {"Serhou Guirassy (BVB)", "Christopher Nkunku (RBL)", "Can Uzun (SGE)", "Antonio Nusa (RBL)"}

    def highlight_kb_picks(row: pd.Series) -> list[str]:
        if row.get("Spieler") in kb_picked:
            return ["background-color: #dbeafe; color: #0f172a"] * len(row)
        return [""] * len(row)

    def highlight_scorer_picks(row: pd.Series) -> list[str]:
        if row.get("Spieler") in scorer_picked:
            return ["background-color: #dbeafe; color: #0f172a"] * len(row)
        return [""] * len(row)

    col_l1, col_l2 = st.columns(2)

    with col_l1:
        st.markdown("#### 🎯 Top Kickbase-Punkte (ohne Bayern)")
        kb_rows = []
        kb_seen = set()
        all_kb_no_bayern = [p for p in cache.get("kickbased_season", []) if "bayern" not in p.get("team_lower", "")]
        for rank_idx, p in enumerate(all_kb_no_bayern, start=1):
            t_raw = p.get("team", "")
            abbr = abbr_map.get(t_raw, t_raw)
            full_t = alias_map.get(t_raw, t_raw)
            sp_name = f"{p['name']} ({abbr})" if abbr else p["name"]
            if rank_idx <= 25 or sp_name in kb_picked:
                kb_rows.append({
                    "Rang": rank_idx,
                    "Spieler": sp_name,
                    "Verein": full_t,
                    "Kickbase-Punkte": p["points"],
                    "Ø Punkte": p["average"]
                })
                kb_seen.add(sp_name)
        df_kb = pd.DataFrame(kb_rows)
        st.dataframe(df_kb.style.apply(highlight_kb_picks, axis=1), width="stretch", hide_index=True)

    with col_l2:
        st.markdown("#### ⚽ Top Scorer & Torjäger (ohne Bayern)")
        sc_rows = []
        all_sc_no_bayern = [s for s in cache.get("ligainsider_scorers", []) if "bayern" not in s.get("team_key", "")]
        all_sc_no_bayern.sort(key=lambda x: (x.get("scorer", 0), x.get("goals", 0), -x.get("appearances", 0)), reverse=True)
        for rank_idx, s in enumerate(all_sc_no_bayern, start=1):
            t_key = s.get("team_key", "")
            abbr = abbr_map.get(t_key, "")
            sp_name = f"{s['name']} ({abbr})" if abbr else s["name"]
            if rank_idx <= 25 or sp_name in scorer_picked:
                sc_rows.append({
                    "Rang": rank_idx,
                    "Spieler": sp_name,
                    "Scorerpunkte": s["scorer"],
                    "Tore": s["goals"],
                    "Vorlagen": s["assists"],
                    "Einsätze": s["appearances"]
                })
        df_sc = pd.DataFrame(sc_rows)
        st.dataframe(df_sc.style.apply(highlight_scorer_picks, axis=1), width="stretch", hide_index=True)

with tab_manual:
    st.subheader("Manuelle Events (Trainer-Kategorien & Overrides)")
    st.caption("Trainer-Entlassungen und Tribünen-Verweise für Trainer können hier direkt abgehakt werden.")
    manual = load_manual_events()

    col_m1, col_m2 = st.columns(2)
    cat_trib = "Trainer XYZ muss auf die Tribüne"
    cat_sack = "Trainer XYZ wird entlassen"
    manual.setdefault(cat_trib, {})
    manual.setdefault(cat_sack, {})

    with col_m1:
        st.markdown(f"#### 🏟️ {cat_trib}")
        for ans_key in [
            "Miron Muslić (S04)",
            "Carles Martínez (B04)",
            "Alexander Blessin (BMG)",
            "Vincent Wagner (SVE)",
        ]:
            cur_val = bool(manual[cat_trib].get(ans_key, False))
            new_val = st.checkbox(f"{ans_key}", value=cur_val, key=f"trib_{ans_key}")
            manual[cat_trib][ans_key] = new_val

    with col_m2:
        st.markdown(f"#### 📋 {cat_sack}")
        for ans_key in [
            "Martín Demichelis (RBL)",
            "Mauro Lustrinelli (FCU)",
            "Merlin Polzin (HSV)",
            "Christian Ilzer (TSG)",
        ]:
            cur_val = bool(manual[cat_sack].get(ans_key, False))
            new_val = st.checkbox(f"{ans_key}", value=cur_val, key=f"sack_{ans_key}")
            manual[cat_sack][ans_key] = new_val

    if st.button("💾 Manuelle Einstellungen speichern"):
        save_manual_events(manual)
        st.success("Gespeichert!")
        st.rerun()
