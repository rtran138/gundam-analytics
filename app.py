import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

RAW = Path("data/raw.json")
ANALYZED = Path("data/analyzed.json")
IMG_DIR = Path("assets/card_images")
CARD_NAMES_FILE = Path("assets/card_names.json")
CDN_URL = "https://deckbuilder.egmanevents.com/card_images/gundam/{card_id}.webp"


def card_image(card_id: str) -> str | Path:
    local = IMG_DIR / f"{card_id}.webp"
    if local.exists():
        return local
    return CDN_URL.format(card_id=card_id)


ARCH_LR_FILE     = Path("assets/archetype_lr_cards.json")
ARCH_GROUPS_FILE = Path("assets/archetype_groups.json")

@st.cache_data
def load_card_names() -> dict:
    if CARD_NAMES_FILE.exists():
        return json.loads(CARD_NAMES_FILE.read_text(encoding="utf-8"))
    return {}


@st.cache_data
def load_arch_lr_cards() -> dict:
    if ARCH_LR_FILE.exists():
        return {k: v for k, v in json.loads(ARCH_LR_FILE.read_text(encoding="utf-8")).items() if v}
    return {}


@st.cache_data
def load_arch_groups() -> dict:
    if ARCH_GROUPS_FILE.exists():
        return json.loads(ARCH_GROUPS_FILE.read_text(encoding="utf-8"))
    return {}


def apply_arch_groups(arch_data: dict, groups: dict) -> dict:
    """Merge grouped archetypes into a single entry, return updated dict."""
    # Build reverse map: member → group name
    member_to_group = {m: g for g, members in groups.items() for m in members}
    merged: dict[str, dict] = {}
    for arch, data in arch_data.items():
        target = member_to_group.get(arch, arch)
        if target not in merged:
            merged[target] = {
                "archetype":    target,
                "deck_count":   0,
                "meta_share":   0.0,
                "placements":   {},
                "top_finishes": 0,
            }
        m = merged[target]
        m["deck_count"]   += data["deck_count"]
        m["meta_share"]   += data["meta_share"]
        m["top_finishes"] += data["top_finishes"]
        for placement, count in data["placements"].items():
            m["placements"][placement] = m["placements"].get(placement, 0) + count
    return merged


def card_label(card_id: str, card_names: dict) -> str:
    info = card_names.get(card_id)
    if info and info.get("name"):
        return f"{info['name']} ({card_id})"
    return card_id


def short_name(card_id: str, card_names: dict, max_len: int = 15) -> str:
    name = card_names.get(card_id, {}).get("name", "")
    if not name:
        return card_id
    return name if len(name) <= max_len else name[:max_len - 1] + "…"



def deck_color_combo(deck: dict, card_names: dict) -> str:
    """Derive color combination from the cards in a deck."""
    color_counts: dict[str, int] = {}
    for card in deck["cards"]:
        c = card_names.get(card["card_id"], {}).get("color", "").strip()
        if c and c != "—":
            color_counts[c] = color_counts.get(c, 0) + 1
    if not color_counts:
        return deck.get("color", "Unknown").strip() or "Unknown"
    # Include any color represented by ≥2 unique card types to filter out 1-of splashes
    colors = sorted(c for c, n in color_counts.items() if n >= 2)
    if not colors:
        colors = sorted(color_counts)
    return "/".join(colors)

st.set_page_config(
    page_title="Gundam Card Analytics",
    page_icon="🤖",
    layout="wide",
)

# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data
def load_data():
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    analyzed = json.loads(ANALYZED.read_text(encoding="utf-8"))
    return raw, analyzed


def refresh_data():
    try:
        with st.spinner("Scraping latest deck lists..."):
            subprocess.run([sys.executable, "scraper.py"], check=True)
        with st.spinner("Analyzing data..."):
            subprocess.run([sys.executable, "analyzer.py"], check=True)
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Refresh not available in this environment: {e}")


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🤖 Gundam Analytics")
    st.caption("GD03 Format — egmanevents.com")

    if st.button("Refresh Data", use_container_width=True):
        refresh_data()

    if ANALYZED.exists():
        analyzed_raw = json.loads(ANALYZED.read_text(encoding="utf-8"))
        st.caption(f"Last updated: {analyzed_raw['meta']['last_updated']}")

    st.divider()
    page = st.radio(
        "View",
        ["Meta Overview", "Card Analysis"],
        label_visibility="collapsed",
    )

# ── Guard: check data exists ──────────────────────────────────────────────────

if not RAW.exists() or not ANALYZED.exists():
    st.warning("No data yet. Click **Refresh Data** in the sidebar to scrape.")
    st.stop()

raw, analyzed = load_data()
card_names = load_card_names()
arch_lr_cards = load_arch_lr_cards()
arch_groups = load_arch_groups()
meta = analyzed["meta"]
cards_data = analyzed["cards"]
arch_data = analyzed["archetypes"]
raw_df = pd.DataFrame(raw)

grouped_arch = apply_arch_groups(arch_data, arch_groups)
member_to_group = {m: g for g, members in arch_groups.items() for m in members}

# ── Helper: build cards DataFrame ─────────────────────────────────────────────

def cards_df() -> pd.DataFrame:
    rows = []
    for c in cards_data.values():
        info = card_names.get(c["card_id"], {})
        rows.append({
            "Card ID":        c["card_id"],
            "Name":           info.get("name", "—"),
            "Color":          info.get("color", "—"),
            "Type":           info.get("cardType", "—"),
            "Rarity":         info.get("rarity", "—"),
            "Decks":          c["deck_count"],
            "Appearance %":   round(c["appearance_rate"] * 100, 1),
            "Weighted Score": c["weighted_score"],
            "Avg Copies":     c["avg_copies_in_deck"],
            "Top Archetypes": ", ".join(dict.fromkeys(member_to_group.get(a, a) for a in c["top_archetypes"][:3])),
        })
    return pd.DataFrame(rows).sort_values("Weighted Score", ascending=False).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — META OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════

if page == "Meta Overview":
    st.header("Meta Overview")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Decks", meta["total_decks"])
    c2.metric("Events Tracked", meta["total_events"])
    c3.metric("Unique Archetypes", len(grouped_arch))
    c4.metric("Cards Tracked", meta["cards_tracked"])

    st.divider()

    # Archetype meta share (with groupings applied)
    arch_df = (
        pd.DataFrame(grouped_arch.values())
        .sort_values("deck_count", ascending=False)
        .reset_index(drop=True)
    )
    arch_df["Meta %"] = (arch_df["meta_share"] * 100).round(1)

    st.subheader("Top Archetypes — Win Rate Proxy")
    top15 = arch_df.head(15).copy()
    top15["Top Finishes"] = top15["top_finishes"]
    top15["Conv %"] = (top15["top_finishes"] / top15["deck_count"] * 100).round(1)

    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        x=top15["archetype"],
        y=top15["deck_count"],
        name="Total Decks",
        marker_color="steelblue",
        opacity=0.6,
    ))
    fig2.add_trace(go.Bar(
        x=top15["archetype"],
        y=top15["Top Finishes"],
        name="Top-3 Finishes",
        marker_color="gold",
    ))
    fig2.update_layout(
        barmode="overlay",
        xaxis_tickangle=-40,
        legend=dict(orientation="h", y=1.1),
        margin=dict(t=10, b=120),
        yaxis_title="Decks",
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.subheader("Archetype Table")
    display_arch = arch_df[["archetype", "deck_count", "Meta %", "top_finishes"]].rename(
        columns={"archetype": "Archetype", "deck_count": "Decks", "top_finishes": "Top-3 Finishes"}
    )
    st.dataframe(display_arch, use_container_width=True, hide_index=True)

    # ── Archetype Signature Cards ─────────────────────────────────────────────
    if arch_lr_cards:
        st.divider()
        st.subheader("Archetype Signature Cards")

        # Build display rows using grouped archetypes
        # For each grouped archetype, find a card ID from any of its members
        sig_items = []
        seen = set()
        for a in grouped_arch.values():
            arch_name = a["archetype"]
            if arch_name in seen:
                continue
            # Find card ID: check direct match, then check if it's a group and use first member's card
            card_id = arch_lr_cards.get(arch_name)
            if not card_id:
                members = arch_groups.get(arch_name, [])
                for m in members:
                    card_id = arch_lr_cards.get(m)
                    if card_id:
                        break
            if not card_id:
                continue
            seen.add(arch_name)
            sig_items.append({
                "archetype": arch_name,
                "card_id":   card_id,
                "pct":       round(a["meta_share"] * 100, 1),
                "decks":     a["deck_count"],
            })
        sig_items.sort(key=lambda x: -x["pct"])

        # Render as a flex grid of cards with overlaid white text
        cards_html = ""
        for item in sig_items:
            img_url = CDN_URL.format(card_id=item["card_id"])
            cards_html += f"""
            <div style="position:relative;width:140px;flex-shrink:0;">
              <img src="{img_url}"
                   style="width:100%;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,0.5);display:block;">
              <div style="position:absolute;bottom:0;left:0;right:0;
                          background:linear-gradient(transparent,rgba(0,0,0,0.82));
                          border-radius:0 0 8px 8px;padding:18px 4px 6px;text-align:center;">
                <div style="color:white;font-size:22px;font-weight:700;line-height:1.1;">{item['pct']}%</div>
                <div style="color:#ddd;font-size:11px;margin-top:2px;">{item['archetype']}</div>
              </div>
            </div>"""

        st.markdown(
            f'<div style="display:flex;flex-wrap:wrap;gap:12px;justify-content:flex-start;">'
            f'{cards_html}</div>',
            unsafe_allow_html=True,
        )

    # ── Color Combination Breakdown ───────────────────────────────────────────
    st.divider()
    st.subheader("Color Combination Breakdown")

    combo_stats: dict[str, dict] = {}
    PLACEMENT_POINTS = {"1st": 7, "2nd": 6, "3rd": 5, "Top 4": 4, "Top 8": 3, "Top 16": 2, "Top 32": 1}
    for deck in raw:
        combo = deck_color_combo(deck, card_names)
        if combo not in combo_stats:
            combo_stats[combo] = {"decks": 0, "top_finishes": 0, "weighted_score": 0}
        combo_stats[combo]["decks"] += 1
        placing = deck.get("placing_clean") or deck.get("placing", "")
        if placing in ("1st", "2nd", "3rd"):
            combo_stats[combo]["top_finishes"] += 1
        combo_stats[combo]["weighted_score"] += PLACEMENT_POINTS.get(placing, 0)

    combo_df = (
        pd.DataFrame([
            {
                "Color Combo":    combo,
                "Decks":          v["decks"],
                "Meta %":         round(v["decks"] / meta["total_decks"] * 100, 1),
                "Top-3 Finishes": v["top_finishes"],
                "Weighted Score": v["weighted_score"],
            }
            for combo, v in combo_stats.items()
        ])
        .sort_values("Decks", ascending=False)
        .reset_index(drop=True)
    )

    cc_left, cc_right = st.columns(2)

    with cc_left:
        top_combos = combo_df.head(8).copy()
        other_decks = combo_df.iloc[8:]["Decks"].sum()
        if other_decks:
            top_combos = pd.concat([
                top_combos,
                pd.DataFrame([{"Color Combo": "Other", "Decks": other_decks,
                                "Meta %": round(other_decks / meta["total_decks"] * 100, 1)}])
            ], ignore_index=True)
        fig_cc = px.pie(
            top_combos, names="Color Combo", values="Decks",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig_cc.update_traces(textposition="inside", textinfo="percent+label")
        fig_cc.update_layout(showlegend=False, margin=dict(t=10, b=10))
        st.plotly_chart(fig_cc, use_container_width=True)

    with cc_right:
        fig_cc2 = go.Figure()
        fig_cc2.add_trace(go.Bar(
            x=combo_df["Color Combo"],
            y=combo_df["Decks"],
            name="Total Decks",
            marker_color="mediumpurple",
            opacity=0.6,
        ))
        fig_cc2.add_trace(go.Bar(
            x=combo_df["Color Combo"],
            y=combo_df["Top-3 Finishes"],
            name="Top-3 Finishes",
            marker_color="gold",
        ))
        fig_cc2.update_layout(
            barmode="overlay",
            xaxis_tickangle=-40,
            legend=dict(orientation="h", y=1.1),
            margin=dict(t=10, b=120),
            yaxis_title="Decks",
        )
        st.plotly_chart(fig_cc2, use_container_width=True)

    st.dataframe(combo_df, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — CARD STATS
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Card Analysis":
    st.header("Card Analysis")

    SIGNAL_COLORS = {"++": "#2ecc71", "+": "#a8d8a8", "-": "#f4a460", "--": "#e74c3c"}
    PTS_MAP = {"1st": 7, "2nd": 6, "3rd": 5, "Top 4": 4, "Top 8": 3, "Top 16": 2, "Top 32": 1}

    # ── Filters ───────────────────────────────────────────────────────────────
    deck_combos = [(deck, deck_color_combo(deck, card_names)) for deck in raw]
    combo_counts = {}
    for _, c in deck_combos:
        combo_counts[c] = combo_counts.get(c, 0) + 1
    color_combos = ["All"] + sorted(combo_counts, key=lambda c: -combo_counts[c])

    f1, f2, f3, f4 = st.columns(4)
    with f1:
        selected_combo = st.selectbox("Color combination", color_combos)
    with f2:
        event_types = sorted({d["event_type"] for d in raw if d["event_type"]})
        selected_event_types = st.multiselect("Event type", event_types, default=event_types)
    with f3:
        sort_by = st.selectbox("Sort by", ["Weighted Score", "Appearance %", "Decks", "Avg Copies"])
    with f4:
        top_n = st.slider("Top N cards", 10, 50, 20)

    hide_staples = st.toggle("Hide staples (avg ≥ 3.5 copies)", value=False)

    EXCLUSIONS_FILE = Path("assets/card_exclusions.json")
    if "excluded_card_ids" not in st.session_state:
        st.session_state["excluded_card_ids"] = (
            json.loads(EXCLUSIONS_FILE.read_text(encoding="utf-8"))
            if EXCLUSIONS_FILE.exists() else []
        )
    with st.expander("Exclude specific cards"):
        all_card_options = sorted(
            {cid: card_names.get(cid, {}).get("name", cid) for cid in cards_data}.items(),
            key=lambda x: x[1],
        )
        excluded = st.multiselect(
            "Cards to hide",
            options=[cid for cid, _ in all_card_options],
            format_func=lambda cid: f"{card_names.get(cid, {}).get('name', cid)} ({cid})",
            default=st.session_state["excluded_card_ids"],
            key="excluded_card_ids_widget",
        )
        cs1, cs2 = st.columns(2)
        with cs1:
            if st.button("Save exclusions", use_container_width=True):
                st.session_state["excluded_card_ids"] = excluded
                EXCLUSIONS_FILE.write_text(json.dumps(excluded, indent=2), encoding="utf-8")
                st.success("Saved.")
        with cs2:
            if st.button("Clear all", use_container_width=True):
                st.session_state["excluded_card_ids"] = []
                EXCLUSIONS_FILE.write_text("[]", encoding="utf-8")
                st.rerun()
    excluded_ids = set(st.session_state["excluded_card_ids"])

    # ── Scope decks to selected combo + event types ───────────────────────────
    if selected_combo == "All":
        scoped_decks = [d for d in raw if d["event_type"] in selected_event_types]
    else:
        scoped_decks = [
            deck for deck, combo in deck_combos
            if combo == selected_combo and deck["event_type"] in selected_event_types
        ]
    total_decks = len(scoped_decks)

    # ── Metrics (only when a combo is selected) ───────────────────────────────
    if selected_combo != "All":
        top3 = sum(1 for d in scoped_decks if (d.get("placing_clean") or d.get("placing", "")) in ("1st", "2nd", "3rd"))
        meta_share = total_decks / meta["total_decks"] * 100 if meta["total_decks"] else 0
        conv = top3 / total_decks * 100 if total_decks else 0
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Decks", total_decks)
        m2.metric("Meta Share", f"{meta_share:.1f}%")
        m3.metric("Top-3 Finishes", top3)
        m4.metric("Top-3 Rate", f"{conv:.1f}%")

    st.divider()

    # ── Build card stats from scoped decks ────────────────────────────────────
    card_counter: dict[str, dict] = {}
    for deck in scoped_decks:
        p = deck.get("placing_clean") or deck.get("placing", "")
        score = PTS_MAP.get(p, 0)
        for card in deck["cards"]:
            cid = card["card_id"]
            if cid not in card_counter:
                card_counter[cid] = {"count": 0, "total": 0, "score": 0}
            card_counter[cid]["count"] += 1
            card_counter[cid]["total"] += card["quantity"]
            card_counter[cid]["score"] += score

    denom = total_decks or 1
    scoped_df = pd.DataFrame([
        {
            "Card ID":        cid,
            "Decks":          v["count"],
            "Appearance %":   round(v["count"] / denom * 100, 1),
            "Weighted Score": v["score"],
            "Avg Copies":     round(v["total"] / v["count"], 2),
        }
        for cid, v in card_counter.items()
    ]).sort_values("Weighted Score", ascending=False).reset_index(drop=True)

    filtered_df = scoped_df[~scoped_df["Card ID"].isin(excluded_ids)]
    if hide_staples:
        filtered_df = filtered_df[filtered_df["Avg Copies"] < 3.5]
    df_display = filtered_df.sort_values(sort_by, ascending=False).head(top_n).reset_index(drop=True)

    # Placement signal
    df_display["Score/Deck"] = (df_display["Weighted Score"] / df_display["Decks"].clip(lower=1)).round(2)
    q25, median, q75 = (
        df_display["Score/Deck"].quantile(0.25),
        df_display["Score/Deck"].median(),
        df_display["Score/Deck"].quantile(0.75),
    )
    def placement_signal(spd: float) -> str:
        if spd >= q75:    return "++"
        if spd >= median: return "+"
        if spd >= q25:    return "-"
        return "--"
    df_display["Signal"] = df_display["Score/Deck"].apply(placement_signal)
    df_display["Label"] = df_display["Card ID"].apply(lambda cid: short_name(cid, card_names))
    dup_mask = df_display["Label"].duplicated(keep=False)
    df_display.loc[dup_mask, "Label"] = (
        df_display.loc[dup_mask, "Label"] + " (" + df_display.loc[dup_mask, "Card ID"] + ")"
    )

    # ── Charts ────────────────────────────────────────────────────────────────
    def placement_bucket(p: str) -> str | None:
        if p == "1st":                                                         return "1st"
        if p in ("2nd", "3rd", "4th", "Top 4"):                               return "Top 4"
        if p in ("5th", "6th", "7th", "8th", "Top 8"):                        return "Top 8"
        if p in ("9th","10th","11th","12th","13th","14th","15th","16th","Top 16"): return "Top 16"
        return None

    BUCKET_ORDER = ["1st", "Top 4", "Top 8", "Top 16"]

    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Placement Distribution")
        st.caption("Large Official Events only")
        all_major_events = sorted(
            {(d["event"], d["date"]) for d in raw if d.get("event_type") == "Large Official Event"},
            key=lambda x: x[1],
        )
        ev_labels = {f"{date} — {event}": event for event, date in all_major_events}
        sel_ev_labels = st.multiselect(
            "Events to include",
            options=list(ev_labels.keys()),
            default=list(ev_labels.keys()),
            key="placement_events",
        )
        sel_events = {ev_labels[l] for l in sel_ev_labels}
        major_decks = [
            d for d in scoped_decks
            if d.get("event_type") == "Large Official Event"
            and (not sel_events or d.get("event") in sel_events)
        ]
        place_counts = {b: 0 for b in BUCKET_ORDER}
        for deck in major_decks:
            bucket = placement_bucket(deck.get("placing_clean") or deck.get("placing", ""))
            if bucket:
                place_counts[bucket] += 1
        fig_place = px.bar(
            pd.DataFrame([{"Placement": b, "Count": place_counts[b]} for b in BUCKET_ORDER]),
            x="Placement", y="Count",
            color="Count", color_continuous_scale="Teal", text="Count",
        )
        fig_place.update_traces(textposition="outside")
        fig_place.update_layout(coloraxis_showscale=False, margin=dict(t=10, b=60))
        st.plotly_chart(fig_place, use_container_width=True)

    with col_r:
        st.subheader(f"Top {top_n} Cards by {sort_by}")
        fig_cards = px.bar(
            df_display, x="Label", y=sort_by,
            color="Signal", color_discrete_map=SIGNAL_COLORS,
            text=sort_by, category_orders={"Signal": ["++", "+", "-", "--"]},
        )
        fig_cards.update_traces(textposition="outside", texttemplate="%{text}")
        fig_cards.update_layout(
            xaxis_tickangle=-45, margin=dict(t=20, b=120),
            yaxis_title=sort_by, legend_title="Signal",
        )
        st.plotly_chart(fig_cards, use_container_width=True)

    # ── Card Table ────────────────────────────────────────────────────────────
    st.divider()
    table_df = df_display[["Card ID", "Signal", "Decks", "Appearance %", "Weighted Score", "Score/Deck", "Avg Copies"]].copy()
    table_df.insert(1, "Name",  table_df["Card ID"].apply(lambda cid: card_names.get(cid, {}).get("name", "—")))
    table_df.insert(2, "Color", table_df["Card ID"].apply(lambda cid: card_names.get(cid, {}).get("color", "—")))
    table_df.insert(3, "Type",  table_df["Card ID"].apply(lambda cid: card_names.get(cid, {}).get("cardType", "—")))
    st.dataframe(table_df, use_container_width=True, hide_index=True)

    # ── Card Image Grid ───────────────────────────────────────────────────────
    st.divider()
    st.subheader("Card Image Grid")
    gc1, _ = st.columns([1, 4])
    with gc1:
        page_size = st.selectbox("Cards per page", [10, 20, 30, 50], index=1, key="grid_page_size")

    grid_df = filtered_df.sort_values(sort_by, ascending=False).reset_index(drop=True)
    total_cards = len(grid_df)
    total_pages = max(1, (total_cards + page_size - 1) // page_size)

    state_key = f"{selected_combo}|{sort_by}|{page_size}|{total_cards}"
    if st.session_state.get("_grid_state_key") != state_key:
        st.session_state["_grid_state_key"] = state_key
        st.session_state["card_grid_page"] = 1
    current_page = max(1, min(st.session_state.get("card_grid_page", 1), total_pages))

    pn1, pn2, pn3 = st.columns([1, 2, 1])
    with pn1:
        if st.button("◀ Prev", disabled=current_page <= 1, key="grid_prev"):
            st.session_state["card_grid_page"] = current_page - 1
            st.rerun()
    with pn2:
        st.markdown(
            f"<p style='text-align:center;margin:0.5rem 0'>Page {current_page} of {total_pages} · {total_cards} cards</p>",
            unsafe_allow_html=True,
        )
    with pn3:
        if st.button("Next ▶", disabled=current_page >= total_pages, key="grid_next"):
            st.session_state["card_grid_page"] = current_page + 1
            st.rerun()

    page_df = grid_df.iloc[(current_page - 1) * page_size : current_page * page_size]
    COLS = 5
    for row_start in range(0, len(page_df), COLS):
        row_slice = page_df.iloc[row_start:row_start + COLS]
        img_cols = st.columns(COLS)
        for col_idx, (_, card_row) in enumerate(row_slice.iterrows()):
            with img_cols[col_idx]:
                cid = card_row["Card ID"]
                name = card_names.get(cid, {}).get("name") or cid
                st.image(card_image(cid), use_container_width=True)
                st.markdown(f"**{name}**  \n`{cid}`")
                st.markdown(
                    f"Play: **{card_row['Appearance %']}%**  \n"
                    f"Avg: **{card_row['Avg Copies']}** &nbsp; Score: **{card_row['Weighted Score']}**"
                )

    # ── Sample Deck Lists (only when a combo is selected) ─────────────────────
    if selected_combo != "All":
        st.divider()
        st.subheader("Sample Deck Lists")
        sample = sorted(scoped_decks, key=lambda d: d.get("placing_rank", 99))[:5]
        for deck in sample:
            label = f"{deck['placing']} — {deck['player']} | {deck['event']} | {deck['date']}"
            with st.expander(label):
                if deck["cards"]:
                    if deck["deck_url"]:
                        st.markdown(f"[View on Deckbuilder]({deck['deck_url']})")
                    deck_cols = st.columns(8)
                    for idx, card in enumerate(deck["cards"]):
                        with deck_cols[idx % 8]:
                            name = card_names.get(card["card_id"], {}).get("name", card["card_id"])
                            st.image(
                                card_image(card["card_id"]),
                                caption=f"{name} x{card['quantity']}",
                                use_container_width=True,
                            )
                else:
                    st.write("No card data available.")
