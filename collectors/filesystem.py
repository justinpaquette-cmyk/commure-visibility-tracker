"""File system activity collector.

Scans designated project folders for recently modified files.
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator, Optional, List, Dict, Tuple
import fnmatch
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


def should_exclude(path: str, excluded_patterns: list[str]) -> bool:
    """Check if a path should be excluded based on patterns."""
    path_parts = Path(path).parts
    for pattern in excluded_patterns:
        if pattern in path_parts:
            return True
        if fnmatch.fnmatch(path, f"*{pattern}*"):
            return True
    return False


def is_in_excluded_folder(path: str, excluded_folders: list[str]) -> bool:
    """Check if path is within an excluded folder."""
    path = os.path.abspath(path)
    for excluded in excluded_folders:
        excluded = os.path.abspath(excluded)
        if path.startswith(excluded):
            return True
    return False


def find_project_for_path(path: str, projects: List[dict]) -> Optional[dict]:
    """Find which project a file path belongs to."""
    path = os.path.abspath(path)
    for project in projects:
        project_path = os.path.abspath(project["folder_path"])
        if path.startswith(project_path):
            return project
    return None


def scan_directory(
    root_path: str,
    settings: dict,
    excluded_folders: list[str],
    since: datetime
) -> Generator[tuple[str, datetime], None, None]:
    """
    Scan a directory for recently modified files.

    Yields (file_path, modified_time) tuples.
    """
    root = Path(root_path)
    if not root.exists():
        return

    extensions = set(settings.get("file_extensions", []))
    excluded_patterns = settings.get("excluded_patterns", [])

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip excluded directories
        dirnames[:] = [
            d for d in dirnames
            if not should_exclude(os.path.join(dirpath, d), excluded_patterns)
            and not is_in_excluded_folder(os.path.join(dirpath, d), excluded_folders)
        ]

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)

            # Skip if in excluded folder
            if is_in_excluded_folder(filepath, excluded_folders):
                continue

            # Check extension
            ext = os.path.splitext(filename)[1]
            if extensions and ext not in extensions:
                continue

            # Check modification time
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                if mtime >= since:
                    yield filepath, mtime
            except OSError:
                continue


def collect_activities(
    lookback_hours: Optional[int] = None,
    verbose: bool = False
) -> List[Activity]:
    """
    Collect file system activities from the past N hours.

    Args:
        lookback_hours: Hours to look back (defaults to config value)
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
        print(f"Scanning {scan_root} for changes since {since}")
        print(f"Excluded folders: {excluded_folders}")

    activities = []
    files_by_project: dict[str, list[tuple[str, datetime]]] = {}
    untracked_files: list[tuple[str, datetime]] = []

    for filepath, mtime in scan_directory(scan_root, settings, excluded_folders, since):
        project = find_project_for_path(filepath, projects)
        if project:
            project_name = project["name"]
            if project_name not in files_by_project:
                files_by_project[project_name] = []
            files_by_project[project_name].append((filepath, mtime))
        else:
            untracked_files.append((filepath, mtime))

    # Create activities grouped by project
    for project_name, files in files_by_project.items():
        # Sort by modification time
        files.sort(key=lambda x: x[1], reverse=True)

        # Group similar files (same directory)
        dirs_modified: dict[str, list[str]] = {}
        for filepath, mtime in files:
            dir_path = os.path.dirname(filepath)
            if dir_path not in dirs_modified:
                dirs_modified[dir_path] = []
            dirs_modified[dir_path].append(os.path.basename(filepath))

        # Create an activity per directory with changes
        for dir_path, filenames in dirs_modified.items():
            rel_dir = os.path.relpath(dir_path, scan_root)
            latest_mtime = max(
                datetime.fromtimestamp(os.path.getmtime(os.path.join(dir_path, f)))
                for f in filenames if os.path.exists(os.path.join(dir_path, f))
            )

            if len(filenames) == 1:
                desc = f"Modified {filenames[0]} in {rel_dir}"
            else:
                desc = f"Modified {len(filenames)} files in {rel_dir}"

            activity = Activity(
                source=ActivitySource.FILESYSTEM,
                timestamp=latest_mtime,
                description=desc,
                confidence=0.7,  # File system alone is medium confidence
                raw_data={
                    "files": filenames,
                    "directory": dir_path,
                    "project": project_name,
                },
                project_path=dir_path,
            )
            activities.append(activity)

    # Handle untracked files (potential new projects)
    if untracked_files and verbose:
        print(f"\nFound {len(untracked_files)} files in untracked locations")
        # Group by top-level directory
        untracked_dirs: dict[str, int] = {}
        for filepath, _ in untracked_files:
            rel_path = os.path.relpath(filepath, scan_root)
            top_dir = rel_path.split(os.sep)[0]
            untracked_dirs[top_dir] = untracked_dirs.get(top_dir, 0) + 1

        for dir_name, count in sorted(untracked_dirs.items(), key=lambda x: -x[1])[:5]:
            print(f"  {dir_name}: {count} files")

    # Sort all activities by timestamp
    activities.sort(key=lambda a: a.timestamp, reverse=True)

    if verbose:
        print(f"\nCollected {len(activities)} activities from {len(files_by_project)} projects")

    return activities


def save_activities(activities: List[Activity], date: Optional[datetime] = None) -> str:
    """Save activities to the daily log file."""
    if date is None:
        date = datetime.now()

    data_dir = Path(__file__).parent.parent / "data" / "activities"
    data_dir.mkdir(parents=True, exist_ok=True)

    filename = date.strftime("%Y-%m-%d") + ".json"
    filepath = data_dir / filename

    # Load existing activities for today if any
    existing = []
    if filepath.exists():
        with open(filepath) as f:
            data = json.load(f)
            existing = [Activity.from_dict(a) for a in data.get("activities", [])]

    # Merge (avoid duplicates based on description + timestamp)
    seen = {(a.description, a.timestamp.isoformat()) for a in existing}
    for activity in activities:
        key = (activity.description, activity.timestamp.isoformat())
        if key not in seen:
            existing.append(activity)
            seen.add(key)

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

    parser = argparse.ArgumentParser(description="Scan filesystem for recent activity")
    parser.add_argument("--hours", type=int, help="Hours to look back")
    parser.add_argument("--save", action="store_true", help="Save to daily log")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    activities = collect_activities(
        lookback_hours=args.hours,
        verbose=args.verbose
    )

    if args.verbose:
        print("\n--- Activities ---")
        for a in activities[:20]:
            print(f"[{a.timestamp.strftime('%H:%M')}] {a.description}")
        if len(activities) > 20:
            print(f"... and {len(activities) - 20} more")

    if args.save:
        path = save_activities(activities)
        print(f"\nSaved to {path}")
