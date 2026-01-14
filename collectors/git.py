"""Git commit activity collector.

Scans git repositories for recent commits.
"""

import os
import subprocess
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator, Optional, List, Dict, Tuple
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Activity, ActivitySource


def load_config() -> tuple[dict, dict]:
    """Load project and settings configuration."""
    config_dir = Path(__file__).parent.parent / "config"

    with open(config_dir / "settings.json") as f:
        settings = json.load(f)

    with open(config_dir / "projects.json") as f:
        projects = json.load(f)

    return settings, projects


def find_git_repos(root_path: str, excluded_folders: list[str]) -> Generator[str, None, None]:
    """Find all git repositories under root_path."""
    for dirpath, dirnames, _ in os.walk(root_path):
        # Skip excluded folders
        dirnames[:] = [
            d for d in dirnames
            if not any(
                os.path.abspath(os.path.join(dirpath, d)).startswith(os.path.abspath(ex))
                for ex in excluded_folders
            )
        ]

        if ".git" in dirnames:
            yield dirpath
            # Don't descend into git repo subdirectories
            dirnames.clear()


def get_commits(
    repo_path: str,
    since: datetime,
    author_email: Optional[str] = None
) -> List[dict]:
    """Get commits from a git repository since a given time."""
    cmd = [
        "git", "-C", repo_path, "log",
        f"--since={since.isoformat()}",
        "--format=%H|%an|%ae|%ai|%s",
        "--no-merges",
    ]

    if author_email:
        cmd.extend(["--author", author_email])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return []

        commits = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            parts = line.split("|", 4)
            if len(parts) != 5:
                continue

            commit_hash, author_name, author_email, date_str, subject = parts

            # Parse git date format (e.g., "2026-01-14 08:30:00 -0500")
            # Remove timezone and parse the date portion
            date_part = date_str.rsplit(" ", 1)[0]  # Remove timezone
            date = datetime.strptime(date_part, "%Y-%m-%d %H:%M:%S")

            commits.append({
                "hash": commit_hash,
                "author_name": author_name,
                "author_email": author_email,
                "date": date,
                "subject": subject,
                "repo_path": repo_path,
            })

        return commits

    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return []


def get_changed_files(repo_path: str, commit_hash: str) -> List[str]:
    """Get list of files changed in a commit."""
    cmd = [
        "git", "-C", repo_path, "diff-tree",
        "--no-commit-id", "--name-only", "-r", commit_hash
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return []

        return [f for f in result.stdout.strip().split("\n") if f]

    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return []


def find_project_for_path(path: str, projects: List[dict]) -> Optional[dict]:
    """Find which project a file path belongs to."""
    path = os.path.abspath(path)
    for project in projects:
        project_path = os.path.abspath(project["folder_path"])
        if path.startswith(project_path):
            return project
    return None


def collect_activities(
    lookback_hours: Optional[int] = None,
    author_email: Optional[str] = None,
    verbose: bool = False
) -> List[Activity]:
    """
    Collect git commit activities from the past N hours.

    Args:
        lookback_hours: Hours to look back (defaults to config value)
        author_email: Filter commits by author email
        verbose: Print progress information

    Returns:
        List of Activity objects
    """
    settings, projects_config = load_config()

    if lookback_hours is None:
        lookback_hours = settings.get("lookback_hours", 24)

    since = datetime.now() - timedelta(hours=lookback_hours)
    scan_root = settings.get("scan_root", os.path.expanduser("~"))
    excluded_folders = projects_config.get("excluded_folders", [])
    projects = projects_config.get("projects", [])

    if verbose:
        print(f"Scanning for git repos in {scan_root}")
        print(f"Looking for commits since {since}")

    activities = []

    for repo_path in find_git_repos(scan_root, excluded_folders):
        if verbose:
            print(f"  Checking {repo_path}")

        commits = get_commits(repo_path, since, author_email)

        if not commits:
            continue

        project = find_project_for_path(repo_path, projects)
        project_name = project["name"] if project else os.path.basename(repo_path)

        for commit in commits:
            files_changed = get_changed_files(repo_path, commit["hash"])

            activity = Activity(
                source=ActivitySource.GIT,
                timestamp=commit["date"],
                description=f"[{project_name}] {commit['subject']}",
                confidence=0.95,  # Git commits are high confidence
                raw_data={
                    "hash": commit["hash"],
                    "author": commit["author_name"],
                    "email": commit["author_email"],
                    "subject": commit["subject"],
                    "files_changed": files_changed,
                    "repo_path": repo_path,
                    "project": project_name,
                },
                project_path=repo_path,
            )
            activities.append(activity)

    # Sort by timestamp
    activities.sort(key=lambda a: a.timestamp, reverse=True)

    if verbose:
        print(f"\nCollected {len(activities)} git commit activities")

    return activities


def save_activities(activities: List[Activity], date: Optional[datetime] = None) -> str:
    """Save activities to the daily log file (appends to existing)."""
    if date is None:
        date = datetime.now()

    data_dir = Path(__file__).parent.parent / "data" / "activities"
    data_dir.mkdir(parents=True, exist_ok=True)

    filename = date.strftime("%Y-%m-%d") + ".json"
    filepath = data_dir / filename

    # Load existing activities
    existing = []
    if filepath.exists():
        with open(filepath) as f:
            data = json.load(f)
            existing = [Activity.from_dict(a) for a in data.get("activities", [])]

    # Merge (avoid duplicates based on git hash for git activities)
    existing_hashes = {
        a.raw_data.get("hash")
        for a in existing
        if a.source == ActivitySource.GIT and a.raw_data.get("hash")
    }

    for activity in activities:
        if activity.raw_data.get("hash") not in existing_hashes:
            existing.append(activity)

    # Save
    with open(filepath, "w") as f:
        json.dump({
            "date": date.strftime("%Y-%m-%d"),
            "collected_at": datetime.now().isoformat(),
            "activities": [a.to_dict() for a in existing],
        }, f, indent=2)

    return str(filepath)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scan git repos for recent commits")
    parser.add_argument("--hours", type=int, help="Hours to look back")
    parser.add_argument("--author", help="Filter by author email")
    parser.add_argument("--save", action="store_true", help="Save to daily log")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    activities = collect_activities(
        lookback_hours=args.hours,
        author_email=args.author,
        verbose=args.verbose
    )

    if args.verbose:
        print("\n--- Git Activities ---")
        for a in activities[:20]:
            print(f"[{a.timestamp.strftime('%Y-%m-%d %H:%M')}] {a.description}")
        if len(activities) > 20:
            print(f"... and {len(activities) - 20} more")

    if args.save:
        path = save_activities(activities)
        print(f"\nSaved to {path}")
