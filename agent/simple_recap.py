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

from collectors.claude import collect_activities as collect_claude, get_session_summary
from collectors.git import collect_activities as collect_git
from collectors.filesystem import collect_activities as collect_fs


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


def map_claude_project_name(short_name: str, projects: list) -> str:
    """Map Claude's short project names to full project names.

    Claude stores projects as encoded folder names like 'tracker', 'pk', 'generator'.
    We match these to projects.json by checking if the short name appears in the folder path.
    """
    if not short_name:
        return "Other"

    short_lower = short_name.lower()

    for project in projects:
        folder = project.get("folder_path", "").lower()
        name_lower = project.get("name", "").lower()

        # Check if short name matches end of folder path
        if folder.endswith(short_lower) or f"/{short_lower}/" in folder or f"-{short_lower}" in folder:
            return project["name"]

        # Check if short name is in project name
        if short_lower in name_lower.replace(" ", "").lower():
            return project["name"]

        # Check aliases
        for alias in project.get("aliases", []):
            if short_lower == alias.lower() or short_lower in alias.lower():
                return project["name"]

    return short_name  # Return original if no match


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
    """Collect all activities. Simple."""
    activities = []

    # Claude sessions
    try:
        activities.extend(collect_claude(hours))
    except Exception as e:
        print(f"  (claude collector: {e})")

    # Git commits
    try:
        activities.extend(collect_git(hours))
    except Exception as e:
        print(f"  (git collector: {e})")

    # File changes
    try:
        activities.extend(collect_fs(hours))
    except Exception as e:
        print(f"  (filesystem collector: {e})")

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
    except Exception as e:
        print(f"  (claude summary: {e})")

    # Group by project
    by_project = defaultdict(lambda: {"count": 0, "files": set(), "messages": 0})

    # First, use Claude's sessions_by_project (more accurate)
    sessions_by_project = claude_summary.get("sessions_by_project", {})
    for short_name, stats in sessions_by_project.items():
        # Map short Claude project name to full project name
        proj_name = map_claude_project_name(short_name, projects)
        by_project[proj_name]["count"] += 1
        by_project[proj_name]["messages"] += stats.get("messages", 0)
        by_project[proj_name]["files"].update(stats.get("files_edited", []) if isinstance(stats.get("files_edited"), list) else [])

    # Then add git/filesystem activities - use pre-determined project names
    for a in activities:
        # Skip claude activities (already counted above)
        if hasattr(a, 'source') and a.source.value == 'claude':
            continue

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

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().isoformat(),
        "total_activities": len(activities),
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

    print("Collecting activities...")
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
