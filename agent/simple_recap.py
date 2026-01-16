#!/usr/bin/env python3
"""Simple recap - dead simple activity summary.

Zero-config project discovery. Auto-detects projects from folder paths.
Only needs overrides.json for custom names and exclusions.
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.claude import get_session_summary
from collectors.git import collect_activities as collect_git
from collectors.filesystem import collect_activities as collect_fs


# Cache for overrides config
_overrides_cache = None


def load_overrides() -> dict:
    """Load overrides config (names, teams, exclusions)."""
    global _overrides_cache
    if _overrides_cache is not None:
        return _overrides_cache

    config_path = Path(__file__).parent.parent / "config" / "overrides.json"
    if config_path.exists():
        with open(config_path) as f:
            _overrides_cache = json.load(f)
    else:
        _overrides_cache = {"names": {}, "teams": {}, "exclude": []}

    return _overrides_cache


def is_excluded(path_or_name: str) -> bool:
    """Check if a path or name should be excluded."""
    overrides = load_overrides()
    excludes = overrides.get("exclude", [])
    check = path_or_name.lower()
    return any(exc.lower() in check for exc in excludes)


def auto_name_from_encoded(encoded_name: str) -> str:
    """Auto-generate a project name from Claude's encoded folder name.

    Works with the encoded name directly to avoid hyphen ambiguity.
    E.g., '-Users-justinpaquette-Documents-sales-eng-projects-v2-client-agnostic-ambient-demos'
    """
    overrides = load_overrides()
    name_overrides = overrides.get("names", {})

    encoded_lower = encoded_name.lower()

    # Check overrides first - match any segment in the path
    # Split by common path segments and check each
    for key, val in name_overrides.items():
        key_encoded = key.lower().replace(" ", "-").replace("/", "-")
        if key_encoded in encoded_lower or key.lower() in encoded_lower:
            return val

    # Pattern: Client-Folder-ClientName-ProjectName
    if "-client-folder-" in encoded_lower:
        # Extract what comes after client-folder
        idx = encoded_lower.find("-client-folder-") + len("-client-folder-")
        rest = encoded_name[idx:]
        # Take first segment (client name)
        parts = rest.split("-")
        if parts:
            # Try to get client and maybe project
            client = parts[0]
            # Look for next meaningful segment
            project = ""
            if len(parts) > 1:
                # Skip common suffixes and get the project
                for i, p in enumerate(parts[1:], 1):
                    if p.lower() not in ["the", "and", "of", "for"]:
                        project = "-".join(parts[1:min(i+2, len(parts))])
                        break
            name = f"{client} {project}".strip().replace("-", " ").title()
            if name and len(name) > 2:
                return name

    # Pattern: client-agnostic-project-name
    if "-client-agnostic-" in encoded_lower:
        idx = encoded_lower.find("-client-agnostic-") + len("-client-agnostic-")
        rest = encoded_name[idx:]
        # Get the project name (everything until end or next major marker)
        # Common project names in your structure
        known_projects = ["ambient-demos", "tts-generator", "mock-ehrs", "rcm-835"]
        for proj in known_projects:
            if proj in rest.lower():
                return proj.replace("-", " ").title()
        # Otherwise take first segment
        first_seg = rest.split("-")[0] if rest else ""
        if first_seg and len(first_seg) > 2:
            return first_seg.replace("-", " ").title()

    # Pattern: productivity-project-name
    if "-productivity-" in encoded_lower:
        idx = encoded_lower.find("-productivity-") + len("-productivity-")
        rest = encoded_name[idx:]
        # Get the project name
        if "commure-task-tracker" in rest.lower():
            return name_overrides.get("commure-task-tracker", "Task Tracker")
        first_seg = rest.split("-")[0] if rest else ""
        if first_seg and len(first_seg) > 2:
            return first_seg.replace("-", " ").title()

    # Pattern: mock-ehrs
    if "-mock-ehrs" in encoded_lower:
        return "Mock EHRs"

    # Fallback: try to extract last meaningful segment
    parts = encoded_name.strip("-").split("-")
    # Filter out common path components
    ignore = ["users", "justinpaquette", "documents", "sales", "eng", "projects", "v2",
              "client", "folder", "agnostic", "productivity"]
    meaningful = [p for p in parts if p.lower() not in ignore and len(p) > 2]
    if meaningful:
        # Take last few meaningful parts as the name
        name = " ".join(meaningful[-2:]).title()
        return name

    return "Misc"


def auto_team_from_encoded(encoded_name: str, project_name: str) -> str:
    """Auto-detect team from encoded path patterns.

    Rules:
    - Client Folder/* -> Sales Engineering (client work)
    - client-agnostic/* -> Sales Engineering (demo/tool work)
    - productivity/* -> Product Management (internal tools)
    - Check overrides for specific project names
    """
    overrides = load_overrides()
    team_overrides = overrides.get("teams", {})

    # Check if project name has a team override
    if project_name in team_overrides:
        return team_overrides[project_name]

    encoded_lower = encoded_name.lower()

    # Sales Engineering patterns (in encoded form, hyphens are path separators)
    se_patterns = [
        "-client-folder-",
        "-client-agnostic-",
        "-mock-ehrs"
    ]
    for pattern in se_patterns:
        if pattern in encoded_lower:
            return "Sales Engineering"

    # Product Management patterns
    pm_patterns = ["-productivity-", "-task-tracker", "-commure-task-tracker"]
    for pattern in pm_patterns:
        if pattern in encoded_lower:
            return "Product Management"

    return "Other"


def decode_claude_path(encoded_name: str) -> str:
    """Decode Claude's encoded folder name to a path.

    Claude encodes paths like:
    -Users-justinpaquette-Documents-sales-eng-projects-v2-...

    Returns decoded path (best effort - hyphens in folder names are ambiguous).
    """
    if not encoded_name:
        return ""

    if encoded_name.startswith("-"):
        # Standard encoded path
        return "/" + encoded_name[1:].replace("-", "/")
    else:
        # Short name or already decoded
        return encoded_name


def discover_project(encoded_or_path: str) -> dict:
    """Auto-discover project info from an encoded Claude path or file path.

    Returns:
        {"name": str, "team": str} or None if excluded
    """
    if not encoded_or_path:
        return {"name": "Misc", "team": "Other"}

    # Check exclusions first
    if is_excluded(encoded_or_path):
        return None

    encoded_lower = encoded_or_path.lower()

    # Filter generic/meaningless paths
    generic = ["-project", "-folder", "-test", "-tmp", "-temp", "-untitled", "-wins", "-task", "private-tmp"]
    for g in generic:
        if encoded_lower.endswith(g):
            return {"name": "Misc", "team": "Other"}

    # Auto-generate name and team from encoded path
    name = auto_name_from_encoded(encoded_or_path)
    team = auto_team_from_encoded(encoded_or_path, name)

    return {"name": name, "team": team}


# Keep this function name for backward compatibility with collectors/claude.py
def map_claude_project_name(encoded_name: str, projects: list = None) -> str:
    """Map Claude's encoded folder name to a project name.

    This is the main entry point used by collectors/claude.py.
    The projects parameter is ignored - we use auto-discovery now.
    """
    result = discover_project(encoded_name)
    if result is None:
        return None  # Excluded
    return result["name"]


def get_project_team(project_name: str, encoded_path: str = "") -> str:
    """Get team for a project name."""
    overrides = load_overrides()
    team_overrides = overrides.get("teams", {})

    if project_name in team_overrides:
        return team_overrides[project_name]

    if encoded_path:
        return auto_team_from_encoded(encoded_path, project_name)

    # Try to infer team from project name patterns
    name_lower = project_name.lower()
    if any(p in name_lower for p in ["task tracker", "productivity"]):
        return "Product Management"
    if any(p in name_lower for p in ["demo", "ehr", "automation", "client"]):
        return "Sales Engineering"

    return "Other"


# Import summary generator (lazy to avoid circular imports)
def get_day_summary(date_str: str) -> str:
    try:
        from cli.daily import generate_day_summary
        return generate_day_summary(date_str)
    except:
        return ""


def generate_range_summary(hours: int, projects: list) -> str:
    """Generate a summary based on the time range and projects worked on."""
    if not projects:
        return ""

    # Determine time label
    if hours <= 24:
        time_label = "Today"
    elif hours <= 168:
        time_label = "This week"
    else:
        time_label = "This month"

    # Count unique projects (excluding Misc)
    unique_projects = [p["name"] for p in projects if p["name"] != "Misc"]

    if not unique_projects:
        return f"{time_label}, worked on various tasks."

    # Build natural summary
    if len(unique_projects) == 1:
        return f"{time_label}, focused on {unique_projects[0]}."
    elif len(unique_projects) == 2:
        return f"{time_label}, worked on {unique_projects[0]} and {unique_projects[1]}."
    else:
        main_projects = unique_projects[:2]
        others = len(unique_projects) - 2
        return f"{time_label}, worked on {main_projects[0]}, {main_projects[1]}, and {others} other project{'s' if others > 1 else ''}."


def get_project_details(hours: int = 24) -> dict:
    """Get detailed activity breakdown by project."""
    import os

    details = {}
    claude_projects_dir = Path.home() / ".claude" / "projects"
    cutoff = datetime.now() - timedelta(hours=hours)

    if not claude_projects_dir.exists():
        return details

    for jsonl in claude_projects_dir.glob("*/*.jsonl"):
        if "subagent" in str(jsonl) or "agent-" in jsonl.name:
            continue
        try:
            session_info = parse_session_for_details(jsonl, cutoff)

            if not session_info.get("has_recent_activity") and not session_info.get("first_message"):
                mtime = datetime.fromtimestamp(jsonl.stat().st_mtime)
                if mtime < cutoff:
                    continue

            if session_info.get("latest_time"):
                mtime = session_info["latest_time"]
                if mtime.tzinfo:
                    mtime = mtime.replace(tzinfo=None)
            else:
                mtime = datetime.fromtimestamp(jsonl.stat().st_mtime)

            # Use auto-discovery for project naming
            proj_folder = jsonl.parent.name
            project = discover_project(proj_folder)
            if project is None:  # Excluded
                continue

            clean_name = project["name"]

            if not session_info.get("first_message"):
                continue

            if clean_name not in details:
                details[clean_name] = {"sessions": [], "files": set(), "commits": []}

            details[clean_name]["sessions"].append({
                "task": session_info.get("first_message", ""),
                "files": session_info.get("files_edited", []),
                "time": mtime.strftime("%H:%M")
            })
            details[clean_name]["files"].update(session_info.get("files_edited", []))

        except Exception:
            continue

    for proj in details:
        details[proj]["files"] = list(details[proj]["files"])

    return details


def parse_session_for_details(jsonl_path, cutoff: datetime = None) -> dict:
    """Parse Claude session for task and files, optionally filtering by time."""
    import os
    from dateutil import parser as date_parser

    info = {"first_message": None, "files_edited": [], "has_recent_activity": False, "latest_time": None}

    try:
        with open(jsonl_path, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                timestamp = entry.get("timestamp")
                if timestamp and cutoff:
                    try:
                        msg_time = date_parser.parse(timestamp)
                        if msg_time.tzinfo and cutoff.tzinfo is None:
                            from datetime import timezone
                            cutoff = cutoff.replace(tzinfo=timezone.utc)
                        if msg_time >= cutoff:
                            info["has_recent_activity"] = True
                            if not info["latest_time"] or msg_time > info["latest_time"]:
                                info["latest_time"] = msg_time
                    except:
                        pass

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

                msg = entry.get("message", {})
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_name = block.get("name", "")
                            tool_input = block.get("input", {})

                            if tool_name in ["Edit", "Write"]:
                                file_path = tool_input.get("file_path", "")
                                if file_path:
                                    basename = os.path.basename(file_path)
                                    if basename not in info["files_edited"]:
                                        info["files_edited"].append(basename)
    except Exception:
        pass

    return info


def load_daily_entry(date: str = None) -> dict:
    """Load daily form entry."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    daily_file = Path(__file__).parent.parent / "data" / "daily.json"
    if not daily_file.exists():
        return {}

    with open(daily_file) as f:
        data = json.load(f)

    for entry in data.get("entries", []):
        if entry["date"] == date:
            return entry
    return {}


def load_wins_for_range(hours: int = 24) -> list:
    """Load all wins within the time range."""
    daily_file = Path(__file__).parent.parent / "data" / "daily.json"
    if not daily_file.exists():
        return []

    with open(daily_file) as f:
        data = json.load(f)

    cutoff = datetime.now() - timedelta(hours=hours)
    all_wins = []

    for entry in data.get("entries", []):
        try:
            entry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
            if entry_date >= cutoff:
                for win in entry.get("wins", []):
                    all_wins.append({
                        "date": entry["date"],
                        "text": win
                    })
        except:
            continue

    return all_wins


def load_blockers_for_range(hours: int = 24) -> list:
    """Load all blockers within the time range."""
    daily_file = Path(__file__).parent.parent / "data" / "daily.json"
    if not daily_file.exists():
        return []

    with open(daily_file) as f:
        data = json.load(f)

    cutoff = datetime.now() - timedelta(hours=hours)
    all_blockers = []

    for entry in data.get("entries", []):
        try:
            entry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
            if entry_date >= cutoff:
                for blocker in entry.get("blockers", []):
                    all_blockers.append({
                        "date": entry["date"],
                        "text": blocker
                    })
        except:
            continue

    return all_blockers


def match_path_to_project(filepath: str) -> str:
    """Match a file path to a project name.

    Works with actual file paths (not Claude encoded paths).
    """
    if not filepath:
        return "Other"

    overrides = load_overrides()
    name_overrides = overrides.get("names", {})

    # Check exclusions
    if is_excluded(filepath):
        return "Other"

    filepath_lower = filepath.lower()

    # Check overrides first
    for key, val in name_overrides.items():
        if key.lower() in filepath_lower:
            return val

    # Pattern: Client Folder/ClientName/...
    if "/client folder/" in filepath_lower:
        match = re.search(r'/client folder/([^/]+)/?([^/]*)', filepath_lower)
        if match:
            client = match.group(1)
            project = match.group(2) if match.group(2) else ""
            name = f"{client} {project}".strip().replace("-", " ").replace("_", " ").title()
            if name:
                return name

    # Pattern: client-agnostic/project-name
    if "/client-agnostic/" in filepath_lower:
        match = re.search(r'/client-agnostic/([^/]+)', filepath_lower)
        if match:
            proj = match.group(1)
            if proj in name_overrides:
                return name_overrides[proj]
            return proj.replace("-", " ").replace("_", " ").title()

    # Pattern: productivity/project-name
    if "/productivity/" in filepath_lower:
        match = re.search(r'/productivity/([^/]+)', filepath_lower)
        if match:
            proj = match.group(1)
            if proj in name_overrides:
                return name_overrides[proj]
            return proj.replace("-", " ").replace("_", " ").title()

    # Pattern: mock-ehrs
    if "/mock-ehrs" in filepath_lower:
        return "Mock EHRs"

    # Fallback: extract meaningful folder from path
    parts = filepath.split("/")
    ignore = ["users", "justinpaquette", "documents", "sales eng projects v2"]
    for part in reversed(parts):
        if part and len(part) > 2 and part.lower() not in ignore:
            return part.replace("-", " ").replace("_", " ").title()

    return "Other"


def calculate_team_distribution(by_project: dict) -> dict:
    """Calculate team distribution from project activities."""
    team_counts = {}

    for proj_name, data in by_project.items():
        # Get team for this project (uses auto-detection + overrides)
        team = get_project_team(proj_name)
        team_counts[team] = team_counts.get(team, 0) + data["count"]

    total = sum(team_counts.values()) or 1
    return {team: round(count / total * 100) for team, count in team_counts.items()}


def collect_all(hours: int = 24) -> list:
    """Collect all activities (git + filesystem).

    Note: Claude sessions come from get_session_summary() to avoid double-counting.
    """
    activities = []

    try:
        activities.extend(collect_git(hours))
    except Exception:
        pass

    try:
        activities.extend(collect_fs(hours))
    except Exception:
        pass

    return activities


def generate_recap(hours: int = 24) -> dict:
    """Generate simple recap data with auto-discovered projects."""
    activities = collect_all(hours)
    daily = load_daily_entry()

    # Load wins and blockers for the time range
    wins_data = load_wins_for_range(hours)
    blockers_data = load_blockers_for_range(hours)

    # Get Claude session summary
    claude_summary = {}
    try:
        claude_summary = get_session_summary(hours)
    except Exception:
        pass

    # Group by project - track last activity time
    by_project = defaultdict(lambda: {"count": 0, "files": set(), "messages": 0, "last_active": None})

    # Process Claude sessions
    sessions_by_project = claude_summary.get("sessions_by_project", {})
    for encoded_name, stats in sessions_by_project.items():
        project = discover_project(encoded_name)
        if project is None:  # Excluded
            continue
        proj_name = project["name"]
        by_project[proj_name]["count"] += 1
        by_project[proj_name]["messages"] += stats.get("messages", 0)
        files = stats.get("files_edited", [])
        if isinstance(files, list):
            by_project[proj_name]["files"].update(files)
        # Claude sessions are recent by definition (within hours range)
        if by_project[proj_name]["last_active"] is None:
            by_project[proj_name]["last_active"] = datetime.now()

    # Process git/filesystem activities
    for a in activities:
        project_name = None

        # Always use match_path_to_project for consistent naming
        if hasattr(a, 'project_path') and a.project_path:
            project_name = match_path_to_project(a.project_path)

        if not project_name or project_name == "Other":
            project_name = "Misc"

        files = []
        if hasattr(a, 'raw_data'):
            files_changed = a.raw_data.get('files_changed', [])
            files_list = a.raw_data.get('files', [])
            repo_path = a.raw_data.get('repo_path', '')
            directory = a.raw_data.get('directory', '')

            if repo_path and files_changed:
                files = [f"{repo_path}/{f}" for f in files_changed]
            elif directory and files_list:
                files = [f"{directory}/{f}" for f in files_list]
            else:
                files = files_changed + files_list

        by_project[project_name]["count"] += 1
        by_project[project_name]["files"].update(files)

        # Track last activity time
        if hasattr(a, 'timestamp') and a.timestamp:
            current_last = by_project[project_name]["last_active"]
            if current_last is None or a.timestamp > current_last:
                by_project[project_name]["last_active"] = a.timestamp

    # Convert to serializable
    project_summary = []
    for name, data in sorted(by_project.items(), key=lambda x: -x[1]["count"]):
        if data["count"] > 0:
            last_active = data.get("last_active")
            last_active_str = None
            if last_active:
                if isinstance(last_active, datetime):
                    last_active_str = last_active.strftime("%b %d")
                else:
                    last_active_str = str(last_active)[:10]

            project_summary.append({
                "name": name if name != "Other" else "Misc",
                "activities": data["count"],
                "files": len(data["files"]),
                "messages": data.get("messages", 0),
                "last_active": last_active_str
            })

    # Calculate team distribution
    team_dist = calculate_team_distribution(by_project)

    # Generate summary and project details
    today = datetime.now().strftime("%Y-%m-%d")
    project_details = get_project_details(hours)

    # Generate range-appropriate summary
    range_summary = generate_range_summary(hours, project_summary)

    # Calculate total activities
    claude_session_count = len(sessions_by_project)
    total_activities = len(activities) + claude_session_count

    # Extract win/blocker text for the output
    wins_list = [w["text"] for w in wins_data]
    blockers_list = [b["text"] for b in blockers_data]

    return {
        "date": today,
        "generated_at": datetime.now().isoformat(),
        "summary": range_summary,
        "project_details": project_details,
        "total_activities": total_activities,
        "total_files": sum(len(data["files"]) for data in by_project.values()),
        "projects": project_summary,
        "claude": {
            "sessions": claude_summary.get("total_sessions", 0),
            "messages": claude_summary.get("total_messages", 0),
            "files_edited": claude_summary.get("total_files_edited", 0),
            "tools": sum(claude_summary.get("tools_breakdown", {}).values()),
        },
        "team": team_dist,
        "daily": {
            "intent": daily.get("intent", ""),
            "wins": wins_list,
            "blockers": blockers_list
        }
    }


def print_recap(data: dict):
    """Print recap to terminal."""
    print(f"\n{'='*50}")
    print(f"  RECAP: {data['date']}")
    print(f"{'='*50}\n")

    if data["daily"]["intent"]:
        print(f"  Intent: {data['daily']['intent']}\n")

    print(f"  {data['total_activities']} activities | {data['total_files']} files\n")

    print("  By Project:")
    for p in data["projects"][:8]:
        print(f"    {p['name']}: {p['activities']} activities, {p['files']} files")

    if data["daily"]["wins"]:
        print(f"\n  Wins:")
        for w in data["daily"]["wins"]:
            print(f"    + {w}")

    if data["daily"]["blockers"]:
        print(f"\n  Blockers:")
        for b in data["daily"]["blockers"]:
            print(f"    ! {b}")

    print(f"\n{'='*50}\n")


def save_recap(data: dict):
    """Save recap to file."""
    output_dir = Path(__file__).parent.parent / "data" / "recaps"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"{data['date']}.json"
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)

    return output_file


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Simple daily recap")
    parser.add_argument("--hours", type=int, default=24, help="Hours to look back")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    parser.add_argument("--save", action="store_true", help="Save to file")

    args = parser.parse_args()

    data = generate_recap(args.hours)

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print_recap(data)

    if args.save:
        path = save_recap(data)
        print(f"Saved: {path}")


if __name__ == "__main__":
    main()
