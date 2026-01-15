#!/usr/bin/env python3
"""Daily form - the 10x productivity feature.

2 minutes in the morning. That's it.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

DATA_FILE = Path(__file__).parent.parent / "data" / "daily.json"


def load_daily_data() -> dict:
    """Load all daily entries."""
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"entries": []}


def save_daily_data(data: dict):
    """Save daily entries."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def get_today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def get_entry(date: str = None) -> dict:
    """Get entry for a specific date."""
    if date is None:
        date = get_today()
    data = load_daily_data()
    for entry in data["entries"]:
        if entry["date"] == date:
            return entry
    return None


def form():
    """Interactive daily form. 2 minutes."""
    today = get_today()
    data = load_daily_data()

    # Check if already filled today
    existing = get_entry(today)
    if existing:
        print(f"\n Already filled for {today}:")
        print(f"  Intent: {existing.get('intent', '-')}")
        print(f"  Wins: {', '.join(existing.get('wins', [])) or '-'}")
        print(f"  Blockers: {', '.join(existing.get('blockers', [])) or '-'}")

        update = input("\nUpdate? [y/N]: ").strip().lower()
        if update != 'y':
            return

    print(f"\n=== Daily Form: {today} ===\n")

    # Intent
    intent = input("What are you shipping today? (1 line)\n> ").strip()

    # Wins
    print("\nWhat did you complete? (comma-separated, or blank)")
    wins_input = input("> ").strip()
    wins = [w.strip() for w in wins_input.split(",") if w.strip()] if wins_input else []

    # Blockers
    print("\nWhat's blocking you? (comma-separated, or blank)")
    blockers_input = input("> ").strip()
    blockers = [b.strip() for b in blockers_input.split(",") if b.strip()] if blockers_input else []

    # Save
    entry = {
        "date": today,
        "intent": intent,
        "wins": wins,
        "blockers": blockers,
        "updated_at": datetime.now().isoformat()
    }

    # Update or append
    found = False
    for i, e in enumerate(data["entries"]):
        if e["date"] == today:
            data["entries"][i] = entry
            found = True
            break
    if not found:
        data["entries"].append(entry)

    # Keep last 30 days only
    data["entries"] = sorted(data["entries"], key=lambda x: x["date"], reverse=True)[:30]

    save_daily_data(data)
    print(f"\n Saved. Go ship it.\n")


def show(date: str = None):
    """Show entry for a date."""
    entry = get_entry(date)
    if not entry:
        print(f"No entry for {date or get_today()}")
        return

    print(f"\n=== {entry['date']} ===")
    print(f"Intent: {entry.get('intent', '-')}")
    print(f"Wins: {', '.join(entry.get('wins', [])) or '-'}")
    print(f"Blockers: {', '.join(entry.get('blockers', [])) or '-'}")
    print()


def quick_win(win: str):
    """Add a quick win without full form."""
    today = get_today()
    data = load_daily_data()

    # Find or create today's entry
    entry = None
    for e in data["entries"]:
        if e["date"] == today:
            entry = e
            break

    if not entry:
        entry = {"date": today, "intent": "", "wins": [], "blockers": []}
        data["entries"].append(entry)

    entry["wins"].append(win)
    entry["updated_at"] = datetime.now().isoformat()

    save_daily_data(data)
    print(f" Added win: {win}")


def quick_blocker(blocker: str):
    """Add a quick blocker without full form."""
    today = get_today()
    data = load_daily_data()

    entry = None
    for e in data["entries"]:
        if e["date"] == today:
            entry = e
            break

    if not entry:
        entry = {"date": today, "intent": "", "wins": [], "blockers": []}
        data["entries"].append(entry)

    entry["blockers"].append(blocker)
    entry["updated_at"] = datetime.now().isoformat()

    save_daily_data(data)
    print(f" Added blocker: {blocker}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Daily productivity form")
    subparsers = parser.add_subparsers(dest="command")

    # Form command
    subparsers.add_parser("form", help="Fill out daily form (2 min)")

    # Show command
    show_parser = subparsers.add_parser("show", help="Show entry")
    show_parser.add_argument("date", nargs="?", help="Date (YYYY-MM-DD)")

    # Quick win
    win_parser = subparsers.add_parser("win", help="Add a quick win")
    win_parser.add_argument("text", nargs="+", help="Win description")

    # Quick blocker
    block_parser = subparsers.add_parser("block", help="Add a blocker")
    block_parser.add_argument("text", nargs="+", help="Blocker description")

    args = parser.parse_args()

    if args.command == "form" or args.command is None:
        form()
    elif args.command == "show":
        show(args.date)
    elif args.command == "win":
        quick_win(" ".join(args.text))
    elif args.command == "block":
        quick_blocker(" ".join(args.text))


if __name__ == "__main__":
    main()
