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


LR_CARDS_FILE = Path("assets/lr_cards.json")

@st.cache_data
def load_card_names() -> dict:
    if CARD_NAMES_FILE.exists():
        return json.loads(CARD_NAMES_FILE.read_text(encoding="utf-8"))
    return {}


@st.cache_data
def load_lr_cards() -> dict:
    if LR_CARDS_FILE.exists():
        return json.loads(LR_CARDS_FILE.read_text(encoding="utf-8"))
    return {}


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
    with st.spinner("Scraping latest deck lists..."):
        subprocess.run([sys.executable, "scraper.py"], check=True)
    with st.spinner("Analyzing data..."):
        subprocess.run([sys.executable, "analyzer.py"], check=True)
    st.cache_data.clear()
    st.rerun()


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
meta = analyzed["meta"]
cards_data = analyzed["cards"]
arch_data = analyzed["archetypes"]
raw_df = pd.DataFrame(raw)

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
            "Top Archetypes": ", ".join(c["top_archetypes"][:3]),
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
    c3.metric("Unique Archetypes", meta["archetypes_tracked"])
    c4.metric("Cards Tracked", meta["cards_tracked"])

    st.divider()

    # Archetype meta share
    arch_df = (
        pd.DataFrame(arch_data.values())
        .sort_values("deck_count", ascending=False)
        .reset_index(drop=True)
    )
    arch_df["Meta %"] = (arch_df["meta_share"] * 100).round(1)

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("Archetype Meta Share")
        top_n = arch_df.head(10).copy()
        other_count = arch_df.iloc[10:]["deck_count"].sum()
        if other_count:
            other_row = pd.DataFrame([{
                "archetype": "Other",
                "deck_count": other_count,
                "Meta %": round(other_count / meta["total_decks"] * 100, 1),
            }])
            top_n = pd.concat([top_n, other_row], ignore_index=True)

        fig = px.pie(
            top_n,
            names="archetype",
            values="deck_count",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Bold,
        )
        fig.update_traces(textposition="inside", textinfo="percent+label")
        fig.update_layout(showlegend=False, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
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

    # ── Most Common LR Cards ──────────────────────────────────────────────────
    st.divider()
    st.subheader("Most Common LR Cards")

    lr_rows = []
    for cid, c in cards_data.items():
        info = card_names.get(cid, {})
        if info.get("rarity", "") == "LR":
            lr_rows.append({
                "Card ID":        cid,
                "Name":           info.get("name", cid),
                "Appearance %":   round(c["appearance_rate"] * 100, 1),
                "Decks":          c["deck_count"],
                "Weighted Score": c["weighted_score"],
            })

    if not lr_rows:
        st.info("No LR rarity data found — re-run **build_card_names.py** to populate rarity.")
    else:
        lr_df = (
            pd.DataFrame(lr_rows)
            .sort_values("Appearance %", ascending=False)
            .head(12)
            .reset_index(drop=True)
        )

        lr_left, lr_right = st.columns(2)

        with lr_left:
            fig_lr = px.pie(
                lr_df,
                names="Name",
                values="Appearance %",
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Bold,
            )
            fig_lr.update_traces(
                textposition="inside",
                textinfo="percent+label",
                textfont=dict(size=18, color="white"),
                insidetextorientation="radial",
            )
            fig_lr.update_layout(showlegend=False, margin=dict(t=10, b=10))
            st.plotly_chart(fig_lr, use_container_width=True)

        with lr_right:
            st.dataframe(
                lr_df[["Name", "Card ID", "Decks", "Appearance %", "Weighted Score"]],
                use_container_width=True,
                hide_index=True,
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
    for cid in top20_ids:
        if cid not in cards_data:
            continue
        row = {"Label": short_name(cid, card_names)}
        bp = cards_data[cid]["by_placement"]
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

    arch_names = sorted(arch_data.keys(), key=lambda a: -arch_data[a]["deck_count"])
    selected_arch = st.selectbox("Select archetype", arch_names)

    arch = arch_data[selected_arch]
    arch_decks = [d for d in raw if d["archetype"] == selected_arch]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Decks", arch["deck_count"])
    m2.metric("Meta Share", f"{arch['meta_share']*100:.1f}%")
    m3.metric("Top-3 Finishes", arch["top_finishes"])
    conv = arch["top_finishes"] / arch["deck_count"] * 100 if arch["deck_count"] else 0
    m4.metric("Top-3 Rate", f"{conv:.1f}%")

    st.divider()
    col_l, col_r = st.columns(2)

    # Placement distribution
    with col_l:
        st.subheader("Placement Distribution")
        place_df = (
            pd.DataFrame(list(arch["placements"].items()), columns=["Placement", "Count"])
            .sort_values("Count", ascending=False)
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
        st.subheader("Most-Played Cards in Archetype")
        card_counter: dict[str, dict] = {}
        for deck in arch_decks:
            for card in deck["cards"]:
                cid = card["card_id"]
                if cid not in card_counter:
                    card_counter[cid] = {"count": 0, "total": 0}
                card_counter[cid]["count"] += 1
                card_counter[cid]["total"] += card["quantity"]

        arch_card_df = pd.DataFrame([
            {
                "Card ID": cid,
                "Label": short_name(cid, card_names),
                "Name": card_names.get(cid, {}).get("name", "—"),
                "Color": card_names.get(cid, {}).get("color", "—"),
                "Rarity": card_names.get(cid, {}).get("rarity", "—"),
                "Decks": v["count"],
                "Inclusion %": round(v["count"] / arch["deck_count"] * 100, 1),
                "Avg Copies": round(v["total"] / v["count"], 2),
            }
            for cid, v in card_counter.items()
        ]).sort_values("Decks", ascending=False).head(20).reset_index(drop=True)
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
