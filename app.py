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
        ["Meta Overview", "Card Stats", "Archetype Deep Dive"],
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

elif page == "Card Stats":
    st.header("Card Stats")

    # Filters
    f1, f2, f3 = st.columns(3)
    with f1:
        sort_by = st.selectbox("Sort by", ["Weighted Score", "Appearance %", "Decks", "Avg Copies"])
    with f2:
        top_n = st.slider("Show top N cards", 10, 50, 20)
    with f3:
        event_types = sorted({d["event_type"] for d in raw if d["event_type"]})
        selected_events = st.multiselect("Filter by event type", event_types, default=event_types)

    # Re-compute if event filter is active
    if set(selected_events) != set(event_types):
        filtered_raw = [d for d in raw if d["event_type"] in selected_events]
        total_filtered = len(filtered_raw)
        card_counts: dict[str, dict] = {}
        for deck in filtered_raw:
            clean = deck.get("placing_clean") or deck["placing"]
            for card in deck["cards"]:
                cid = card["card_id"]
                if cid not in card_counts:
                    card_counts[cid] = {"deck_count": 0, "total_copies": 0, "score": 0}
                card_counts[cid]["deck_count"] += 1
                card_counts[cid]["total_copies"] += card["quantity"]
                pts = {"1st": 7, "2nd": 6, "3rd": 5, "Top 4": 4, "Top 8": 3, "Top 16": 2, "Top 32": 1}
                card_counts[cid]["score"] += pts.get(clean, 0)
        rows = [
            {
                "Card ID": cid,
                "Decks": v["deck_count"],
                "Appearance %": round(v["deck_count"] / total_filtered * 100, 1),
                "Weighted Score": v["score"],
                "Avg Copies": round(v["total_copies"] / v["deck_count"], 2),
                "Top Archetypes": "",
            }
            for cid, v in card_counts.items()
        ]
        df = pd.DataFrame(rows).sort_values("Weighted Score", ascending=False).reset_index(drop=True)
    else:
        df = cards_df()

    df_display = df.sort_values(sort_by, ascending=False).head(top_n).reset_index(drop=True)
    df_display["Label"] = df_display["Card ID"].apply(lambda cid: short_name(cid, card_names))
    dup_mask = df_display["Label"].duplicated(keep=False)
    df_display.loc[dup_mask, "Label"] = (
        df_display.loc[dup_mask, "Label"] + " (" + df_display.loc[dup_mask, "Card ID"] + ")"
    )
    df_display.index += 1

    col_chart, col_table = st.columns([1.4, 1])

    with col_chart:
        st.subheader(f"Top {top_n} Cards by {sort_by}")
        fig = px.bar(
            df_display,
            x="Label",
            y=sort_by,
            color=sort_by,
            color_continuous_scale="Blues",
            text=sort_by,
        )
        fig.update_traces(textposition="outside", texttemplate="%{text}")
        fig.update_layout(
            xaxis_tickangle=-45,
            coloraxis_showscale=False,
            margin=dict(t=20, b=120),
            yaxis_title=sort_by,
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_table:
        st.subheader("Card Table")
        table_df = df_display[["Card ID", "Decks", "Appearance %", "Weighted Score", "Avg Copies"]].copy()
        table_df.insert(1, "Name",   table_df["Card ID"].apply(lambda cid: card_names.get(cid, {}).get("name", "—")))
        table_df.insert(2, "Color",  table_df["Card ID"].apply(lambda cid: card_names.get(cid, {}).get("color", "—")))
        table_df.insert(3, "Type",   table_df["Card ID"].apply(lambda cid: card_names.get(cid, {}).get("cardType", "—")))
        st.dataframe(table_df, use_container_width=True)

    # Placement heatmap for top 20 cards
    st.divider()
    st.subheader("Placement Breakdown — Top 20 Cards")
    placements = ["1st", "2nd", "3rd", "Top 4", "Top 8", "Top 16", "Top 32"]
    top20_ids = df.head(20)["Card ID"].tolist()

    heatmap_rows = []
    seen_hm_labels: dict[str, int] = {}
    for cid in top20_ids:
        if cid not in cards_data:
            continue
        base = short_name(cid, card_names)
        if base in seen_hm_labels:
            label = f"{base} ({cid})"
        else:
            label = base
        seen_hm_labels[base] = seen_hm_labels.get(base, 0) + 1
        bp = cards_data[cid]["by_placement"]
        row = {"Label": label}
        for p in placements:
            row[p] = bp.get(p, {}).get("decks", 0)
        heatmap_rows.append(row)

    hm_df = pd.DataFrame(heatmap_rows).set_index("Label")
    hm_df = hm_df[[p for p in placements if p in hm_df.columns]]

    fig_hm = px.imshow(
        hm_df,
        color_continuous_scale="Blues",
        aspect="auto",
        labels=dict(color="Decks"),
        text_auto=True,
    )
    fig_hm.update_layout(margin=dict(t=10, b=10))
    st.plotly_chart(fig_hm, use_container_width=True)

    # Card Image Grid
    st.divider()
    st.subheader("Card Image Grid")

    gc1, _ = st.columns([1, 4])
    with gc1:
        page_size = st.selectbox("Cards per page", [10, 20, 30, 50], index=1, key="grid_page_size")

    grid_df = df.sort_values(sort_by, ascending=False).reset_index(drop=True)
    total_cards = len(grid_df)
    total_pages = max(1, (total_cards + page_size - 1) // page_size)

    state_key = f"{sort_by}|{page_size}|{total_cards}"
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
            f"<p style='text-align:center;margin:0.5rem 0'>"
            f"Page {current_page} of {total_pages} &nbsp;·&nbsp; {total_cards} cards"
            f"</p>",
            unsafe_allow_html=True,
        )
    with pn3:
        if st.button("Next ▶", disabled=current_page >= total_pages, key="grid_next"):
            st.session_state["card_grid_page"] = current_page + 1
            st.rerun()

    start = (current_page - 1) * page_size
    end = min(start + page_size, total_cards)
    page_df = grid_df.iloc[start:end]

    COLS = 5
    for row_start in range(0, len(page_df), COLS):
        row_slice = page_df.iloc[row_start:row_start + COLS]
        cols = st.columns(COLS)
        for col_idx, (_, card_row) in enumerate(row_slice.iterrows()):
            with cols[col_idx]:
                cid = card_row["Card ID"]
                name_info = card_names.get(cid, {})
                name = name_info.get("name") or cid
                st.image(card_image(cid), use_container_width=True)
                st.markdown(f"**{name}**  \n`{cid}`")
                st.markdown(
                    f"Play: **{card_row['Appearance %']}%**  \n"
                    f"Avg: **{card_row['Avg Copies']}** &nbsp; Score: **{card_row['Weighted Score']}**"
                )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — ARCHETYPE DEEP DIVE
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Archetype Deep Dive":
    st.header("Archetype Deep Dive")

    # Event selector — Large Official Events sorted by date
    all_major_events = sorted(
        {(d["event"], d["date"]) for d in raw if d.get("event_type") == "Large Official Event"},
        key=lambda x: x[1],
    )
    event_labels = {f"{date} — {event}": event for event, date in all_major_events}
    selected_event_labels = st.multiselect(
        "Filter by event",
        options=list(event_labels.keys()),
        default=list(event_labels.keys()),
    )
    selected_events = {event_labels[l] for l in selected_event_labels}

    # Build color combo map for every raw deck
    deck_combos = [(deck, deck_color_combo(deck, card_names)) for deck in raw]
    combo_deck_counts = {}
    for _, combo in deck_combos:
        combo_deck_counts[combo] = combo_deck_counts.get(combo, 0) + 1
    color_combos = sorted(combo_deck_counts, key=lambda c: -combo_deck_counts[c])

    selected_combo = st.selectbox("Select color combination", color_combos)

    arch_decks = [deck for deck, combo in deck_combos if combo == selected_combo]
    total_decks = len(arch_decks)

    PLACEMENT_POINTS = {"1st": 7, "2nd": 6, "3rd": 5, "Top 4": 4, "Top 8": 3, "Top 16": 2, "Top 32": 1}
    top3 = sum(1 for d in arch_decks if (d.get("placing_clean") or d.get("placing", "")) in ("1st", "2nd", "3rd"))
    meta_share = total_decks / meta["total_decks"] * 100 if meta["total_decks"] else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Decks", total_decks)
    m2.metric("Meta Share", f"{meta_share:.1f}%")
    m3.metric("Top-3 Finishes", top3)
    conv = top3 / total_decks * 100 if total_decks else 0
    m4.metric("Top-3 Rate", f"{conv:.1f}%")

    st.divider()
    col_l, col_r = st.columns(2)

    # Placement distribution (Large Official Events only)
    def placement_bucket(p: str) -> str | None:
        if p in ("1st",):
            return "1st"
        if p in ("2nd", "3rd", "4th", "Top 4"):
            return "Top 4"
        if p in ("5th", "6th", "7th", "8th", "Top 8"):
            return "Top 8"
        if p in ("9th", "10th", "11th", "12th", "13th", "14th", "15th", "16th", "Top 16"):
            return "Top 16"
        return None

    BUCKET_ORDER = ["1st", "Top 4", "Top 8", "Top 16"]

    with col_l:
        st.subheader("Placement Distribution")
        st.caption("Large Official Events only")
        major_decks = [
            d for d in arch_decks
            if d.get("event_type") == "Large Official Event"
            and (not selected_events or d.get("event") in selected_events)
        ]
        place_counts: dict[str, int] = {b: 0 for b in BUCKET_ORDER}
        for deck in major_decks:
            p = deck.get("placing_clean") or deck.get("placing", "")
            bucket = placement_bucket(p)
            if bucket:
                place_counts[bucket] += 1
        place_df = pd.DataFrame(
            [{"Placement": b, "Count": place_counts[b]} for b in BUCKET_ORDER]
        )
        fig = px.bar(
            place_df, x="Placement", y="Count",
            color="Count", color_continuous_scale="Teal",
            text="Count",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(coloraxis_showscale=False, margin=dict(t=10, b=60))
        st.plotly_chart(fig, use_container_width=True)

    # Card frequency within this archetype
    with col_r:
        st.subheader("Most-Played Cards in Color Combo")
        card_counter: dict[str, dict] = {}
        for deck in arch_decks:
            for card in deck["cards"]:
                cid = card["card_id"]
                if cid not in card_counter:
                    card_counter[cid] = {"count": 0, "total": 0}
                card_counter[cid]["count"] += 1
                card_counter[cid]["total"] += card["quantity"]

        total_arch_decks = len(arch_decks) or 1
        arch_card_df = pd.DataFrame([
            {
                "Card ID": cid,
                "Label": short_name(cid, card_names),
                "Name": card_names.get(cid, {}).get("name", "—"),
                "Color": card_names.get(cid, {}).get("color", "—"),
                "Decks": v["count"],
                "Inclusion %": round(v["count"] / total_arch_decks * 100, 1),
                "Avg Copies": round(v["total"] / v["count"], 2),
            }
            for cid, v in card_counter.items()
        ]).sort_values("Decks", ascending=False).head(20).reset_index(drop=True)

        # Deduplicate labels: append card ID when two cards share the same truncated name
        dup_labels = arch_card_df["Label"].duplicated(keep=False)
        arch_card_df.loc[dup_labels, "Label"] = (
            arch_card_df.loc[dup_labels, "Label"] + " ("
            + arch_card_df.loc[dup_labels, "Card ID"] + ")"
        )
        arch_card_df.index += 1

        fig2 = px.bar(
            arch_card_df.head(15), x="Label", y="Inclusion %",
            color="Avg Copies", color_continuous_scale="Oranges",
            text="Inclusion %",
        )
        fig2.update_traces(textposition="outside", texttemplate="%{text}%")
        fig2.update_layout(xaxis_tickangle=-45, margin=dict(t=10, b=100))
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Card Detail Table")
    st.dataframe(arch_card_df, use_container_width=True)

    # Sample deck lists
    st.divider()
    st.subheader("Sample Deck Lists")
    sample = sorted(arch_decks, key=lambda d: d.get("placing_rank", 99))[:5]
    for deck in sample:
        label = f"{deck['placing']} — {deck['player']} | {deck['event']} | {deck['date']}"
        with st.expander(label):
            if deck["cards"]:
                if deck["deck_url"]:
                    st.markdown(f"[View on Deckbuilder]({deck['deck_url']})")
                # Display cards as image grid
                cols = st.columns(8)
                for idx, card in enumerate(deck["cards"]):
                    with cols[idx % 8]:
                        name = card_names.get(card["card_id"], {}).get("name", card["card_id"])
                        st.image(
                            card_image(card["card_id"]),
                            caption=f"{name} x{card['quantity']}",
                            use_container_width=True,
                        )
            else:
                st.write("No card data available.")
