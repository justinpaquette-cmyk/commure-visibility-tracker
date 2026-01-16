#!/usr/bin/env python3
"""Daily form - the 10x productivity feature.

2 minutes in the morning. That's it.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_FILE = Path(__file__).parent.parent / "data" / "daily.json"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def parse_claude_session(jsonl_path: Path) -> dict:
    """Parse a Claude session file to extract key info."""
    info = {
        "first_message": None,
        "files_edited": [],
        "commands": []
    }

    try:
        with open(jsonl_path, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Get first user message
                if entry.get("type") == "user" and not info["first_message"]:
                    msg = entry.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        info["first_message"] = content.strip()
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                info["first_message"] = c.get("text", "").strip()
                                break

                # Look for tool uses in assistant messages
                msg = entry.get("message", {})
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_name = block.get("name", "")
                            tool_input = block.get("input", {})

                            # Track file edits
                            if tool_name in ["Edit", "Write"]:
                                file_path = tool_input.get("file_path", "")
                                if file_path:
                                    basename = os.path.basename(file_path)
                                    if basename not in info["files_edited"]:
                                        info["files_edited"].append(basename)

                            # Track bash commands
                            elif tool_name == "Bash":
                                cmd = tool_input.get("command", "")
                                if cmd and len(cmd) < 100:
                                    # Skip common noise
                                    if not any(skip in cmd for skip in ["cat ", "head ", "echo ", "ls "]):
                                        if cmd not in info["commands"]:
                                            info["commands"].append(cmd)

    except Exception:
        pass

    return info


def generate_day_summary(date_str: str) -> str:
    """Generate a template-based summary of the day's work."""
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return ""

    lines = []
    projects_worked = []
    total_files = 0

    # Gather Claude session data
    if CLAUDE_PROJECTS_DIR.exists():
        for jsonl in CLAUDE_PROJECTS_DIR.glob("*/*.jsonl"):
            if "subagent" in str(jsonl):
                continue
            try:
                mtime = datetime.fromtimestamp(jsonl.stat().st_mtime)
                if target_date.date() == mtime.date():
                    proj_folder = jsonl.parent.name
                    clean_name = proj_folder.replace("-Users-justinpaquette-Documents-sales-eng-projects-v2-", "")
                    clean_name = clean_name.replace("-", " ").strip()

                    # Simplify common patterns
                    clean_name = clean_name.replace("Client Folder ", "")
                    clean_name = clean_name.replace("client agnostic ", "")
                    clean_name = clean_name.replace("productivity ", "")
                    clean_name = clean_name.replace("BAK entsaleseng projects oldmac BAK normandy ", "")
                    clean_name = clean_name.replace("Users justinpaquette Downloads ", "")
                    clean_name = clean_name.replace("Users justinpaquette", "Home")
                    clean_name = clean_name.replace("mock ehrs ", "Mock EHRs ")
                    clean_name = clean_name.strip()
                    if not clean_name:
                        clean_name = "Misc"

                    info = parse_claude_session(jsonl)

                    if info.get("first_message") or info.get("files_edited"):
                        task_summary = ""
                        if info.get("first_message"):
                            # Extract key action from first message
                            msg = info["first_message"][:100]
                            # Common task patterns
                            if "build" in msg.lower():
                                task_summary = "building"
                            elif "create" in msg.lower():
                                task_summary = "creating"
                            elif "fix" in msg.lower():
                                task_summary = "fixing"
                            elif "update" in msg.lower():
                                task_summary = "updating"
                            elif "document" in msg.lower() or "wins" in msg.lower():
                                task_summary = "documenting"
                            elif "study" in msg.lower() or "review" in msg.lower():
                                task_summary = "reviewing"
                            elif "help" in msg.lower():
                                task_summary = "working on"
                            else:
                                task_summary = "working on"

                        file_count = len(info.get("files_edited", []))
                        total_files += file_count

                        proj_entry = {"name": clean_name, "action": task_summary, "files": file_count}
                        projects_worked.append(proj_entry)
            except:
                continue

    # Build summary
    if not projects_worked:
        return "No Claude sessions recorded."

    # Group by action type
    by_action = {}
    for p in projects_worked:
        action = p["action"]
        if action not in by_action:
            by_action[action] = []
        by_action[action].append(p)

    # Generate narrative
    parts = []
    for action, projs in by_action.items():
        proj_names = [p["name"] for p in projs]
        file_sum = sum(p["files"] for p in projs)

        if len(proj_names) == 1:
            if file_sum > 0:
                parts.append(f"{action.capitalize()} {proj_names[0]} ({file_sum} files)")
            else:
                parts.append(f"{action.capitalize()} {proj_names[0]}")
        else:
            # Combine similar projects
            if file_sum > 0:
                parts.append(f"{action.capitalize()} {', '.join(proj_names[:3])} ({file_sum} files)")
            else:
                parts.append(f"{action.capitalize()} {', '.join(proj_names[:3])}")

    return ". ".join(parts) + "."


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

    # Keep last 180 days only
    data["entries"] = sorted(data["entries"], key=lambda x: x["date"], reverse=True)[:180]

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


def history(date_str: str):
    """Show what happened on a specific date."""
    # Parse date
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        print(f"Invalid date format: {date_str} (use YYYY-MM-DD)")
        return

    next_date = target_date + timedelta(days=1)
    day_name = target_date.strftime("%A")

    print(f"\n{'='*50}")
    print(f"  {day_name}, {date_str}")
    print(f"{'='*50}\n")

    # 1. Check saved recap
    recap_file = Path(__file__).parent.parent / "data" / "recaps" / f"{date_str}.json"
    if recap_file.exists():
        with open(recap_file) as f:
            recap = json.load(f)
        print("  SAVED RECAP:")
        print(f"    {recap.get('total_activities', 0)} activities, {recap.get('total_files', 0)} files")
        for p in recap.get("projects", [])[:5]:
            print(f"      {p['name']}: {p['activities']} activities")
        print()

    # 2. Check daily entry
    entry = get_entry(date_str)
    if entry:
        print("  DAILY ENTRY:")
        if entry.get("intent"):
            print(f"    Intent: {entry['intent']}")
        if entry.get("wins"):
            print(f"    Wins: {', '.join(entry['wins'])}")
        if entry.get("blockers"):
            print(f"    Blockers: {', '.join(entry['blockers'])}")
        print()

    # 3. Find Claude sessions from that date
    print("  CLAUDE SESSIONS:")
    claude_sessions = []
    if CLAUDE_PROJECTS_DIR.exists():
        for jsonl in CLAUDE_PROJECTS_DIR.glob("*/*.jsonl"):
            # Skip subagent files
            if "subagent" in str(jsonl):
                continue
            try:
                mtime = datetime.fromtimestamp(jsonl.stat().st_mtime)
                if target_date.date() == mtime.date():
                    # Extract project name from path
                    proj_folder = jsonl.parent.name
                    clean_name = proj_folder.replace("-Users-justinpaquette-Documents-sales-eng-projects-v2-", "")
                    clean_name = clean_name.replace("-", " ").replace("  ", " - ")
                    # Simplify common patterns
                    clean_name = clean_name.replace("Client Folder ", "")
                    clean_name = clean_name.replace("client agnostic ", "")
                    clean_name = clean_name.replace("productivity ", "")
                    clean_name = clean_name.replace("mock ehrs ", "Mock EHRs ")
                    clean_name = clean_name.strip()

                    # Parse session for details
                    session_info = parse_claude_session(jsonl)
                    claude_sessions.append({
                        "name": clean_name,
                        "file": jsonl,
                        "info": session_info
                    })
            except (OSError, ValueError):
                continue

    if claude_sessions:
        for s in claude_sessions[:8]:
            print(f"\n    [{s['name']}]")
            info = s['info']
            if info.get('first_message'):
                # Truncate first message
                msg = info['first_message'][:80]
                if len(info['first_message']) > 80:
                    msg += "..."
                print(f"      Task: {msg}")
            if info.get('files_edited'):
                files = info['files_edited'][:5]
                print(f"      Files: {', '.join(files)}")
                if len(info['files_edited']) > 5:
                    print(f"             ... and {len(info['files_edited']) - 5} more")
            if info.get('commands'):
                cmds = info['commands'][:3]
                for cmd in cmds:
                    print(f"      Ran: {cmd[:60]}")
    else:
        print("    (none found)")
    print()

    # 4. Find git commits from that date
    print("  GIT COMMITS:")
    config_path = Path(__file__).parent.parent / "config" / "settings.json"
    try:
        with open(config_path) as f:
            settings = json.load(f)
        scan_root = settings.get("scan_root", str(Path.home() / "Documents"))
    except:
        scan_root = str(Path.home() / "Documents")

    commits_found = []

    # Walk directory tree to find .git folders
    for root, dirs, files in os.walk(scan_root):
        # Skip common non-project directories
        dirs[:] = [d for d in dirs if d not in ['node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build']]

        if '.git' in dirs:
            repo_path = root
            dirs.remove('.git')  # Don't descend into .git
            try:
                result = subprocess.run(
                    ["git", "-C", repo_path, "log",
                     f"--since={date_str} 00:00",
                     f"--until={next_date.strftime('%Y-%m-%d')} 00:00",
                     "--format=%s", "--no-merges"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    repo_name = os.path.basename(repo_path)
                    for line in result.stdout.strip().split("\n"):
                        if line:
                            commits_found.append(f"[{repo_name}] {line[:50]}")
            except:
                continue

    if commits_found:
        for c in commits_found[:10]:
            print(f"    {c}")
        if len(commits_found) > 10:
            print(f"    ... and {len(commits_found) - 10} more")
    else:
        print("    (none found)")

    print(f"\n{'='*50}\n")

    # Show generated summary
    summary = generate_day_summary(date_str)
    if summary:
        print(f"  SUMMARY: {summary}\n")


def weekly_wins():
    """Show all wins for the past 2 weeks."""
    data = load_daily_data()
    today = datetime.now()

    # Go back 2 weeks (14 days)
    start_date = today - timedelta(days=13)

    print(f"\n{'='*50}")
    print(f"  WINS: {start_date.strftime('%b %d')} - {today.strftime('%b %d, %Y')}")
    print(f"{'='*50}\n")

    all_wins = []
    current = start_date

    while current <= today:
        date_str = current.strftime("%Y-%m-%d")
        entry = get_entry(date_str)

        if entry and entry.get("wins"):
            day_name = current.strftime("%A")
            week_label = "This Week" if (today - current).days < 7 else "Last Week"
            for win in entry["wins"]:
                all_wins.append({
                    "date": date_str,
                    "day": day_name,
                    "week": week_label,
                    "win": win
                })

        current += timedelta(days=1)

    if all_wins:
        # Group by week then day for display
        current_week = None
        current_date = None
        for item in all_wins:
            if item["week"] != current_week:
                current_week = item["week"]
                print(f"\n  --- {current_week} ---")
                current_date = None

            if item["date"] != current_date:
                current_date = item["date"]
                print(f"\n  {item['day']} ({item['date']}):")

            print(f"    - {item['win']}")

        print(f"\n  Total: {len(all_wins)} wins over 2 weeks")

        # Generate a summary for copying
        print(f"\n{'='*50}")
        print("  COPY-PASTE SUMMARY:")
        print(f"{'='*50}")
        print(f"\nWins ({start_date.strftime('%b %d')} - {today.strftime('%b %d')}):\n")
        for item in all_wins:
            print(f"- {item['win']}")
    else:
        print("  No wins logged in the past 2 weeks.")
        print("  Add wins with: daily.py win \"Your accomplishment\"")

    print()


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

    # History
    history_parser = subparsers.add_parser("history", help="Show activity for a past date")
    history_parser.add_argument("date", help="Date (YYYY-MM-DD)")

    # Weekly wins
    subparsers.add_parser("wins", help="Show all wins for the current week")

    args = parser.parse_args()

    if args.command == "form" or args.command is None:
        form()
    elif args.command == "show":
        show(args.date)
    elif args.command == "win":
        quick_win(" ".join(args.text))
    elif args.command == "block":
        quick_blocker(" ".join(args.text))
    elif args.command == "history":
        history(args.date)
    elif args.command == "wins":
        weekly_wins()


if __name__ == "__main__":
    main()
