#!/usr/bin/env python3
"""Manual activity entry CLI.

Allows adding activities that aren't automatically detected
(meetings, research, discussions, etc.)
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Activity, ActivitySource, Roadmap, Theme, ThemeStatus, Task, TaskStatus


def load_projects() -> dict:
    """Load project configuration."""
    config_path = Path(__file__).parent.parent / "config" / "projects.json"
    with open(config_path) as f:
        return json.load(f)


def load_roadmap() -> Roadmap:
    """Load current roadmap."""
    roadmap_path = Path(__file__).parent.parent / "data" / "roadmap.json"
    return Roadmap.load(str(roadmap_path))


def save_roadmap(roadmap: Roadmap) -> None:
    """Save roadmap."""
    roadmap_path = Path(__file__).parent.parent / "data" / "roadmap.json"
    roadmap.save(str(roadmap_path))


def save_activity(activity: Activity) -> str:
    """Save a manual activity to today's log."""
    data_dir = Path(__file__).parent.parent / "data" / "activities"
    data_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    filepath = data_dir / f"{today}.json"

    existing_activities = []
    if filepath.exists():
        with open(filepath) as f:
            data = json.load(f)
            existing_activities = [Activity.from_dict(a) for a in data.get("activities", [])]

    existing_activities.append(activity)

    with open(filepath, "w") as f:
        json.dump({
            "date": today,
            "collected_at": datetime.now().isoformat(),
            "activities": [a.to_dict() for a in existing_activities],
        }, f, indent=2)

    return str(filepath)


def cmd_log(args):
    """Log a manual activity."""
    import argparse
    parser = argparse.ArgumentParser(description="Log a manual activity")
    parser.add_argument("description", nargs="+", help="Activity description")
    parser.add_argument("-p", "--project", help="Project name (optional)")
    parser.add_argument("-t", "--theme", help="Theme name (optional)")

    parsed = parser.parse_args(args)
    description = " ".join(parsed.description)

    activity = Activity(
        source=ActivitySource.MANUAL,
        timestamp=datetime.now(),
        description=description,
        confidence=1.0,
        raw_data={
            "project": parsed.project,
            "theme": parsed.theme,
        },
    )

    path = save_activity(activity)
    print(f"Logged: {description}")
    print(f"Saved to: {path}")


def cmd_theme_add(args):
    """Add a new theme to the roadmap."""
    import argparse
    parser = argparse.ArgumentParser(description="Add a new theme")
    parser.add_argument("name", help="Theme name")
    parser.add_argument("-s", "--status", default="planned",
                        choices=["planned", "active", "blocked", "complete"])
    parser.add_argument("-n", "--notes", default="", help="Optional notes")

    parsed = parser.parse_args(args)

    roadmap = load_roadmap()

    # Find or create default project
    if not roadmap.projects:
        print("No projects configured. Please add projects to config/projects.json first.")
        return

    # Use first project for now (can enhance later)
    project = roadmap.projects[0]

    theme = Theme(
        id=str(uuid4())[:8],
        name=parsed.name,
        status=ThemeStatus(parsed.status),
        notes=parsed.notes,
    )

    project.themes.append(theme)
    roadmap.last_updated = datetime.now()
    save_roadmap(roadmap)

    print(f"Added theme: {theme.name} [{theme.status.value}]")


def cmd_theme_list(args):
    """List all themes."""
    roadmap = load_roadmap()

    if not roadmap.projects:
        print("No projects configured.")
        return

    for project in roadmap.projects:
        print(f"\n{project.name} ({project.team})")
        print("-" * 40)

        if not project.themes:
            print("  No themes yet")
            continue

        for theme in project.themes:
            status_icon = {
                ThemeStatus.PLANNED: " ",
                ThemeStatus.ACTIVE: "●",
                ThemeStatus.BLOCKED: "!",
                ThemeStatus.COMPLETE: "✓",
            }.get(theme.status, " ")

            print(f"  [{status_icon}] {theme.name}")
            if theme.notes:
                print(f"      {theme.notes}")


def cmd_task_add(args):
    """Add a task to a theme."""
    import argparse
    parser = argparse.ArgumentParser(description="Add a task to a theme")
    parser.add_argument("theme_id", help="Theme ID")
    parser.add_argument("description", nargs="+", help="Task description")

    parsed = parser.parse_args(args)
    description = " ".join(parsed.description)

    roadmap = load_roadmap()

    # Find theme
    theme_found = None
    for project in roadmap.projects:
        for theme in project.themes:
            if theme.id == parsed.theme_id or theme.name.lower().startswith(parsed.theme_id.lower()):
                theme_found = theme
                break

    if not theme_found:
        print(f"Theme not found: {parsed.theme_id}")
        return

    task = Task(
        id=str(uuid4())[:8],
        description=description,
        status=TaskStatus.TODO,
    )

    theme_found.tasks.append(task)
    roadmap.last_updated = datetime.now()
    save_roadmap(roadmap)

    print(f"Added task to {theme_found.name}: {description}")


def cmd_status(args):
    """Show current status summary."""
    roadmap = load_roadmap()
    projects_config = load_projects()

    print("\n" + "=" * 50)
    print("CURRENT STATUS")
    print("=" * 50)

    if roadmap.last_updated:
        print(f"Last updated: {roadmap.last_updated.strftime('%Y-%m-%d %H:%M')}")

    # Active themes
    active_themes = []
    blocked_themes = []

    for project in roadmap.projects:
        for theme in project.themes:
            if theme.status == ThemeStatus.ACTIVE:
                active_themes.append((project.team, theme))
            elif theme.status == ThemeStatus.BLOCKED:
                blocked_themes.append((project.team, theme))

    if active_themes:
        print("\n## Currently Active")
        for team, theme in active_themes:
            print(f"  [{team}] {theme.name}")
            for task in theme.tasks:
                if task.status == TaskStatus.IN_PROGRESS:
                    print(f"    → {task.description}")

    if blocked_themes:
        print("\n## Blocked")
        for team, theme in blocked_themes:
            print(f"  [{team}] {theme.name}")
            if theme.notes:
                print(f"    Reason: {theme.notes}")

    # Pending changes
    if roadmap.pending_changes:
        pending = [c for c in roadmap.pending_changes if c.approved is None]
        if pending:
            print(f"\n## Pending Review ({len(pending)} changes)")

    print()


def cmd_help(args):
    """Show help."""
    print("""
Task Tracker CLI

Commands:
  log <description>      Log a manual activity (meeting, research, etc.)
  theme add <name>       Add a new theme to the roadmap
  theme list             List all themes
  task add <theme> <desc> Add a task to a theme
  status                 Show current status summary

Options for 'log':
  -p, --project NAME     Associate with a project
  -t, --theme NAME       Associate with a theme

Options for 'theme add':
  -s, --status STATUS    Set initial status (planned, active, blocked, complete)
  -n, --notes TEXT       Add notes

Examples:
  ./manual.py log "Team standup meeting"
  ./manual.py log -p "Auth System" "Research OAuth providers"
  ./manual.py theme add "API Performance" -s active
  ./manual.py task add api "Profile slow endpoints"
  ./manual.py status
""")


def main():
    if len(sys.argv) < 2:
        cmd_help([])
        return

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "log": cmd_log,
        "theme": lambda a: (
            cmd_theme_add(a[1:]) if a and a[0] == "add"
            else cmd_theme_list(a[1:]) if a and a[0] == "list"
            else print("Usage: theme [add|list] ...")
        ),
        "task": lambda a: (
            cmd_task_add(a[1:]) if a and a[0] == "add"
            else print("Usage: task add <theme_id> <description>")
        ),
        "status": cmd_status,
        "help": cmd_help,
        "-h": cmd_help,
        "--help": cmd_help,
    }

    if command in commands:
        commands[command](args)
    else:
        print(f"Unknown command: {command}")
        cmd_help([])


if __name__ == "__main__":
    main()
