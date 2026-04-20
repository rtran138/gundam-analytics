import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

URL = "https://egmanevents.com/gd03-tournament-deck-lists"
OUTPUT = Path("data/raw.json")

PLACEMENT_ORDER = ["1st", "2nd", "3rd", "Top 4", "Top 8", "Top 16", "Top 32"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Column positions (1-based, matching table-cell-N class names):
# 1=color, 2=deck image link, 3=archetype+deck link, 4=player,
# 5=placing, 6=format, 7=event_type, 8=event, 9=date
COL = {
    "color":      0,
    "deck_link":  2,   # archetype text link (cell 3)
    "player":     3,
    "placing":    4,
    "format":     5,
    "event_type": 6,
    "event":      7,
    "date":       8,
}


def placement_rank(placing: str) -> int:
    p = placing.strip()
    try:
        return PLACEMENT_ORDER.index(p)
    except ValueError:
        return len(PLACEMENT_ORDER)


def parse_deck_url(href: str) -> list[dict]:
    parsed = urlparse(href)
    params = parse_qs(parsed.query)
    deck_str = params.get("deck", [""])[0]
    if not deck_str:
        return []
    # Some URLs use | instead of , as separator
    deck_str = deck_str.replace("|", ",")
    cards = []
    for entry in deck_str.split(","):
        entry = entry.strip()
        if ":" in entry:
            card_id, qty = entry.rsplit(":", 1)
            try:
                cards.append({"card_id": card_id.strip(), "quantity": int(qty)})
            except ValueError:
                pass
    return cards


def scrape() -> list[dict]:
    print(f"Fetching {URL} ...")
    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # Find the table that contains deckbuilder links
    table = None
    for t in soup.find_all("table"):
        if t.find("a", href=lambda h: h and "deckbuilder" in h):
            table = t
            break

    if table is None:
        raise RuntimeError("Could not find the deck list table.")

    rows = table.find_all("tr")
    print(f"Found {len(rows)} rows in table.")

    results = []
    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) < 9:
            continue

        def cell_text(col_idx: int) -> str:
            return cells[col_idx].get_text(separator=" ", strip=True)

        # Deck URL + archetype from cell index 2 (the text link cell)
        deck_cell = cells[COL["deck_link"]]
        a = deck_cell.find("a", href=lambda h: h and "deckbuilder" in h)
        deck_href = a["href"] if a else ""
        archetype = deck_cell.get_text(strip=True) if deck_href else ""
        deck_cards = parse_deck_url(deck_href)

        placing = cell_text(COL["placing"])
        results.append({
            "color":        cell_text(COL["color"]),
            "archetype":    archetype,
            "deck_url":     deck_href,
            "cards":        deck_cards,
            "player":       cell_text(COL["player"]),
            "placing":      placing.strip(),
            "placing_rank": placement_rank(placing),
            "format":       cell_text(COL["format"]),
            "event_type":   cell_text(COL["event_type"]),
            "event":        cell_text(COL["event"]),
            "date":         cell_text(COL["date"]),
        })

    return results


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    decks = scrape()
    OUTPUT.write_text(json.dumps(decks, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {len(decks)} entries -> {OUTPUT}")
    with_cards = sum(1 for d in decks if d["cards"])
    print(f"Entries with parsed card lists: {with_cards}/{len(decks)}")
    if decks:
        d = decks[0]
        print(f"\nFirst entry: {d['player']} | {d['archetype']} | {d['placing']} | {d['event']}")
        print(f"Cards: {len(d['cards'])} unique card entries")


if __name__ == "__main__":
    main()
