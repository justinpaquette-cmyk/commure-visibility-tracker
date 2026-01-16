#!/usr/bin/env python3
"""Simple recap - dead simple activity summary.

No auto-themes. No wins detection. No AI. Just facts.
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.claude import get_session_summary
from collectors.git import collect_activities as collect_git
from collectors.filesystem import collect_activities as collect_fs

# Import summary generator (lazy to avoid circular imports)
def get_day_summary(date_str: str) -> str:
    try:
        from cli.daily import generate_day_summary
        return generate_day_summary(date_str)
    except:
        return ""


def get_project_details(hours: int = 24) -> dict:
    """Get detailed activity breakdown by project.

    Uses the same project naming logic as the main recap for consistency.
    """
    from pathlib import Path
    import os

    details = {}
    claude_projects_dir = Path.home() / ".claude" / "projects"
    cutoff = datetime.now() - timedelta(hours=hours)
    projects_config = load_projects()

    if not claude_projects_dir.exists():
        return details

    for jsonl in claude_projects_dir.glob("*/*.jsonl"):
        if "subagent" in str(jsonl) or "agent-" in jsonl.name:
            continue
        try:
            # Parse session to check for recent activity
            session_info = parse_session_for_details(jsonl, cutoff)

            # Skip if no recent activity in this session
            if not session_info.get("has_recent_activity") and not session_info.get("first_message"):
                # Fallback: check file modification time
                mtime = datetime.fromtimestamp(jsonl.stat().st_mtime)
                if mtime < cutoff:
                    continue

            # Use latest message time or file mtime
            if session_info.get("latest_time"):
                mtime = session_info["latest_time"]
                if mtime.tzinfo:
                    mtime = mtime.replace(tzinfo=None)
            else:
                mtime = datetime.fromtimestamp(jsonl.stat().st_mtime)

            # Extract folder name for matching - use same logic as main recap
            proj_folder = jsonl.parent.name
            folder_lower = proj_folder.lower()

            # Exclude specific projects first
            excluded_keywords = ["book-ai-covenant", "ai-covenant", "covenant"]
            if any(kw in folder_lower for kw in excluded_keywords):
                continue

            # Use map_claude_project_name for consistent naming with main recap
            clean_name = map_claude_project_name(proj_folder, projects_config)
            if clean_name is None:  # Excluded project
                continue

            # Skip if no first message
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

    # Convert sets to lists for JSON
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

                # Check timestamp if filtering by time
                timestamp = entry.get("timestamp")
                if timestamp and cutoff:
                    try:
                        msg_time = date_parser.parse(timestamp)
                        # Make cutoff timezone-aware if msg_time is
                        if msg_time.tzinfo and cutoff.tzinfo is None:
                            from datetime import timezone
                            cutoff = cutoff.replace(tzinfo=timezone.utc)
                        if msg_time >= cutoff:
                            info["has_recent_activity"] = True
                            if not info["latest_time"] or msg_time > info["latest_time"]:
                                info["latest_time"] = msg_time
                    except:
                        pass

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

                # Look for file edits
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


def load_projects() -> list:
    """Load projects from config."""
    config_path = Path(__file__).parent.parent / "config" / "projects.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f).get("projects", [])
    return []


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


def match_path_to_project(filepath: str, projects: list) -> str:
    """Simple path matching. No fancy scoring."""
    if not filepath:
        return "Other"

    filepath_lower = filepath.lower()

    for project in projects:
        folder = project.get("folder_path", "")
        if folder and folder.lower() in filepath_lower:
            return project["name"]

        # Also check aliases
        for alias in project.get("aliases", []):
            if alias.lower() in filepath_lower:
                return project["name"]

    # No match - extract a meaningful folder name
    return extract_folder_group(filepath)


def extract_folder_group(filepath: str) -> str:
    """Extract a meaningful folder name when no project matches.

    Bubbles up folder names to create logical groupings.
    """
    if not filepath:
        return "Other"

    # Key parent folders to look for
    markers = [
        "client folder/",
        "client-agnostic/",
        "mock-ehrs/",
        "productivity/",
        ".claude/",
    ]

    filepath_lower = filepath.lower()

    for marker in markers:
        if marker in filepath_lower:
            # Get the folder after the marker
            idx = filepath_lower.find(marker) + len(marker)
            rest = filepath[idx:]
            # Get first meaningful folder name
            parts = rest.split("/")
            for part in parts:
                if part and not part.startswith(".") and len(part) > 2:
                    # Clean up the name
                    name = part.replace("-", " ").replace("_", " ").title()
                    return name

    # Fall back to parent folder of the file
    parts = filepath.split("/")
    if len(parts) >= 2:
        parent = parts[-2]
        if parent and not parent.startswith(".") and len(parent) > 2:
            return parent.replace("-", " ").replace("_", " ").title()

    return "Other"


def map_claude_project_name(encoded_name: str, projects: list) -> str:
    """Map Claude's encoded folder names to full project names.

    Claude stores projects as encoded folder names like:
    - '-Users-justinpaquette-Documents-sales-eng-projects-v2-client-folder-Tenet-...'
    - 'tracker' (short name from sessions_by_project)

    We decode these and match against projects.json folder paths.
    """
    if not encoded_name:
        return "Misc"

    encoded_lower = encoded_name.lower()

    # Exclude specific projects
    excluded_projects = ["book-ai-covenant", "ai-covenant", "covenant"]
    if any(exc in encoded_lower for exc in excluded_projects):
        return None  # Will be filtered out

    # Filter out generic/meaningless names
    generic_names = ["project", "folder", "test", "tmp", "temp", "untitled", "wins", "private-tmp", "task"]
    if encoded_lower.strip("-") in generic_names:
        return "Misc"

    # Also check if the path ends with a generic name
    path_parts = encoded_lower.strip("-").split("-")
    if path_parts and path_parts[-1] in generic_names:
        return "Misc"

    # Decode the path: Claude encodes paths by replacing / with -
    # E.g., "-Users-justinpaquette-Documents-..." -> "/Users/justinpaquette/Documents/..."
    if encoded_name.startswith("-"):
        decoded_path = "/" + encoded_name[1:].replace("-", "/")
    else:
        decoded_path = encoded_name.replace("-", "/")

    decoded_lower = decoded_path.lower()

    # Try to match against project folder paths
    best_match = None
    best_score = 0

    for project in projects:
        folder = project.get("folder_path", "")
        folder_lower = folder.lower()

        # Direct match - decoded path starts with or contains project folder
        if folder_lower and (
            decoded_lower.startswith(folder_lower) or
            folder_lower in decoded_lower
        ):
            score = len(folder_lower)
            if score > best_score:
                best_score = score
                best_match = project["name"]

        # Check aliases
        for alias in project.get("aliases", []):
            alias_lower = alias.lower()
            if alias_lower in decoded_lower or alias_lower in encoded_lower:
                score = len(alias_lower) + 100  # Boost alias matches
                if score > best_score:
                    best_score = score
                    best_match = project["name"]

    if best_match:
        return best_match

    # No match - extract a meaningful name from the path
    # Look for recognizable folder markers
    markers = ["client-folder/", "client-agnostic/", "productivity/"]
    for marker in markers:
        if marker in decoded_lower:
            idx = decoded_lower.find(marker) + len(marker)
            rest = decoded_path[idx:]
            # Get first folder after marker
            parts = rest.split("/")
            for part in parts:
                if part and len(part) > 2:
                    return part.replace("-", " ").title()

    # Last resort: use last meaningful folder from path
    parts = decoded_path.rstrip("/").split("/")
    for part in reversed(parts):
        if part and len(part) > 3 and part.lower() not in ["users", "documents", "justinpaquette"]:
            return part.replace("-", " ").title()

    return "Misc"


def calculate_team_distribution(by_project: dict, projects: list) -> dict:
    """Calculate team distribution from project activities."""
    team_counts = {}
    project_to_team = {p["name"]: p.get("team", "Other") for p in projects}

    for proj_name, data in by_project.items():
        team = project_to_team.get(proj_name, "Other")
        team_counts[team] = team_counts.get(team, 0) + data["count"]

    total = sum(team_counts.values()) or 1
    return {team: round(count / total * 100) for team, count in team_counts.items()}


def collect_all(hours: int = 24) -> list:
    """Collect all activities. Simple.

    Note: Claude sessions are NOT collected here - they come from
    get_session_summary() to avoid double-counting.
    """
    activities = []

    # Git commits
    try:
        activities.extend(collect_git(hours))
    except Exception:
        pass

    # File changes
    try:
        activities.extend(collect_fs(hours))
    except Exception:
        pass

    return activities


def generate_recap(hours: int = 24) -> dict:
    """Generate simple recap data."""
    projects = load_projects()
    activities = collect_all(hours)
    daily = load_daily_entry()

    # Get Claude session summary (rich data already collected)
    claude_summary = {}
    try:
        claude_summary = get_session_summary(hours)
    except Exception:
        pass

    # Group by project
    by_project = defaultdict(lambda: {"count": 0, "files": set(), "messages": 0})

    # First, use Claude's sessions_by_project (more accurate)
    sessions_by_project = claude_summary.get("sessions_by_project", {})
    for short_name, stats in sessions_by_project.items():
        # Map short Claude project name to full project name
        proj_name = map_claude_project_name(short_name, projects)
        if proj_name is None:  # Excluded project
            continue
        by_project[proj_name]["count"] += 1
        by_project[proj_name]["messages"] += stats.get("messages", 0)
        by_project[proj_name]["files"].update(stats.get("files_edited", []) if isinstance(stats.get("files_edited"), list) else [])

    # Then add git/filesystem activities - use pre-determined project names
    # (Claude activities are not in this list - they come from sessions_by_project above)
    for a in activities:
        # Use the project name already determined by the collector
        project_name = None
        if hasattr(a, 'raw_data'):
            project_name = a.raw_data.get('project')

        # If no project from collector, try matching via project_path
        if not project_name and hasattr(a, 'project_path') and a.project_path:
            project_name = match_path_to_project(a.project_path, projects)

        # Fallback to "Other"
        if not project_name or project_name == "Other":
            project_name = "Other"

        # Get files for the count
        files = []
        if hasattr(a, 'raw_data'):
            # Git activities have files_changed, filesystem has files
            files_changed = a.raw_data.get('files_changed', [])
            files_list = a.raw_data.get('files', [])
            repo_path = a.raw_data.get('repo_path', '')
            directory = a.raw_data.get('directory', '')

            # Prepend full path if we have it
            if repo_path and files_changed:
                files = [f"{repo_path}/{f}" for f in files_changed]
            elif directory and files_list:
                files = [f"{directory}/{f}" for f in files_list]
            else:
                files = files_changed + files_list

        by_project[project_name]["count"] += 1
        by_project[project_name]["files"].update(files)

    # Convert to serializable
    project_summary = []
    for name, data in sorted(by_project.items(), key=lambda x: -x[1]["count"]):
        if data["count"] > 0:
            project_summary.append({
                "name": name if name != "Other" else "Misc",
                "activities": data["count"],
                "files": len(data["files"]),
                "messages": data.get("messages", 0)
            })

    # Calculate team distribution
    team_dist = calculate_team_distribution(by_project, projects)

    # Generate day summary and project details
    today = datetime.now().strftime("%Y-%m-%d")
    day_summary = get_day_summary(today)
    project_details = get_project_details(hours)

    # Calculate total activities (git+fs + claude sessions)
    claude_session_count = len(sessions_by_project)
    total_activities = len(activities) + claude_session_count

    return {
        "date": today,
        "generated_at": datetime.now().isoformat(),
        "summary": day_summary,
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
            "wins": daily.get("wins", []),
            "blockers": daily.get("blockers", [])
        }
    }


def print_recap(data: dict):
    """Print recap to terminal."""
    print(f"\n{'='*50}")
    print(f"  RECAP: {data['date']}")
    print(f"{'='*50}\n")

    # Daily intent
    if data["daily"]["intent"]:
        print(f"  Intent: {data['daily']['intent']}\n")

    # Activity summary
    print(f"  {data['total_activities']} activities | {data['total_files']} files\n")

    print("  By Project:")
    for p in data["projects"][:8]:
        print(f"    {p['name']}: {p['activities']} activities, {p['files']} files")

    # Wins
    if data["daily"]["wins"]:
        print(f"\n  Wins:")
        for w in data["daily"]["wins"]:
            print(f"    + {w}")

    # Blockers
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
