#!/usr/bin/env python3
"""Auto-discover new projects from folder structure.

Scans known base directories for project-like folders that aren't
yet in the projects.json config.

Uses tiered indicators with confidence scoring and integrates with
the approval workflow for new project additions.
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set, Dict, Any
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import ProposedChange


# Tiered indicators with confidence levels
PRIMARY_INDICATORS = {
    '.git': 0.95,
    'package.json': 0.95,
    'requirements.txt': 0.90,
    'pyproject.toml': 0.90,
    'Cargo.toml': 0.95,
    'go.mod': 0.95,
    'Makefile': 0.80,
    'pom.xml': 0.95,
    'build.gradle': 0.95,
    'CMakeLists.txt': 0.90,
}

SECONDARY_INDICATORS = {
    'README.md': 0.70,
    'README.rst': 0.70,
    'docker-compose.yml': 0.75,
    'Dockerfile': 0.70,
    '.env.example': 0.65,
    'tsconfig.json': 0.80,
    'setup.py': 0.80,
}

CONTENT_INDICATORS = {
    'index.html': 0.50,
    'slides/': 0.55,  # Directory
    'assets/': 0.45,  # Directory
    'presentation.html': 0.55,
    'demo.html': 0.50,
}

# Legacy flat list for backwards compatibility
PROJECT_INDICATORS = list(PRIMARY_INDICATORS.keys()) + list(SECONDARY_INDICATORS.keys())

# Folders to skip when scanning
SKIP_PATTERNS = [
    'node_modules',
    '__pycache__',
    '.git',
    'venv',
    '.venv',
    'dist',
    'build',
    '.next',
    'target',
]


def load_config():
    """Load current configuration."""
    config_dir = Path(__file__).parent.parent / "config"

    with open(config_dir / "projects.json") as f:
        projects = json.load(f)

    return projects


def save_config(projects: dict):
    """Save projects configuration."""
    config_dir = Path(__file__).parent.parent / "config"

    with open(config_dir / "projects.json", "w") as f:
        json.dump(projects, f, indent=2)


def is_project_folder(path: Path) -> bool:
    """Check if a folder looks like a project (legacy)."""
    confidence, _ = get_project_confidence(path)
    return confidence >= 0.5


def get_project_confidence(path: Path) -> tuple:
    """
    Check if a folder looks like a project and return confidence score.

    Returns:
        (confidence_score, indicators_found)
    """
    indicators_found = []
    max_confidence = 0.0

    # Check primary indicators (highest confidence)
    for indicator, confidence in PRIMARY_INDICATORS.items():
        if (path / indicator).exists():
            indicators_found.append(f"{indicator} (primary)")
            max_confidence = max(max_confidence, confidence)

    # Check secondary indicators
    for indicator, confidence in SECONDARY_INDICATORS.items():
        if (path / indicator).exists():
            indicators_found.append(f"{indicator} (secondary)")
            max_confidence = max(max_confidence, confidence)

    # Check content indicators (directories and files)
    for indicator, confidence in CONTENT_INDICATORS.items():
        if indicator.endswith('/'):
            # Directory indicator
            if (path / indicator.rstrip('/')).is_dir():
                indicators_found.append(f"{indicator} (content)")
                max_confidence = max(max_confidence, confidence)
        else:
            if (path / indicator).exists():
                indicators_found.append(f"{indicator} (content)")
                max_confidence = max(max_confidence, confidence)

    # Boost confidence if multiple indicators present
    if len(indicators_found) >= 3:
        max_confidence = min(max_confidence + 0.1, 1.0)
    elif len(indicators_found) >= 2:
        max_confidence = min(max_confidence + 0.05, 1.0)

    return (max_confidence, indicators_found)


def should_skip(folder_name: str) -> bool:
    """Check if folder should be skipped during scanning."""
    return folder_name in SKIP_PATTERNS or folder_name.startswith('.')


def get_known_paths(projects_config: dict) -> Set[str]:
    """Get set of already-configured project paths."""
    paths = set()
    for project in projects_config.get('projects', []):
        if project.get('folder_path'):
            paths.add(os.path.abspath(project['folder_path']))
    return paths


def infer_team(path: str, confidence: float = 0.0) -> str:
    """
    Infer team from folder path and project type.

    Uses configurable patterns for team inference.
    """
    path_lower = path.lower()

    # Sales Engineering patterns
    se_patterns = ['client folder', 'client-agnostic', 'demo', 'mock', 'sales']
    for pattern in se_patterns:
        if pattern in path_lower:
            return 'Sales Engineering'

    # Product Management patterns
    pm_patterns = ['productivity', 'internal', 'tools', 'admin']
    for pattern in pm_patterns:
        if pattern in path_lower:
            return 'Product Management'

    # Content-heavy projects (low confidence) tend to be PM
    if confidence < 0.6:
        return 'Product Management'

    # Default
    return 'Sales Engineering'


def generate_project_id(path: Path) -> str:
    """Generate a project ID from folder name."""
    name = path.name.lower()
    # Replace spaces and special chars with hyphens
    return ''.join(c if c.isalnum() else '-' for c in name).strip('-')


def discover_projects(
    base_paths: List[str],
    max_depth: int = 3,
    verbose: bool = False,
    min_confidence: float = 0.5
) -> List[dict]:
    """Discover new projects in base paths.

    Args:
        base_paths: List of base directories to scan
        max_depth: Maximum folder depth to search
        verbose: Print discovery progress
        min_confidence: Minimum confidence threshold

    Returns:
        List of discovered project configs with confidence scores
    """
    projects_config = load_config()
    known_paths = get_known_paths(projects_config)
    excluded_folders = set(projects_config.get('excluded_folders', []))

    discovered = []

    for base_path in base_paths:
        base = Path(base_path).expanduser()
        if not base.exists():
            if verbose:
                print(f"Skipping non-existent path: {base}")
            continue

        if verbose:
            print(f"\nScanning: {base}")

        # Walk the directory tree
        for root, dirs, files in os.walk(base):
            # Calculate current depth
            rel_path = Path(root).relative_to(base)
            depth = len(rel_path.parts)

            if depth > max_depth:
                dirs.clear()  # Don't descend further
                continue

            # Filter out skippable directories
            dirs[:] = [d for d in dirs if not should_skip(d)]

            root_path = Path(root)
            abs_path = os.path.abspath(root)

            # Skip excluded folders
            if any(abs_path.startswith(os.path.abspath(exc)) for exc in excluded_folders):
                dirs.clear()
                continue

            # Skip if already known
            if abs_path in known_paths:
                continue

            # Check if this is a project with confidence scoring
            confidence, indicators = get_project_confidence(root_path)

            if confidence >= min_confidence:
                # Check if any parent is already a project (avoid nested projects)
                is_nested = any(
                    abs_path.startswith(known + os.sep)
                    for known in known_paths
                )
                if is_nested:
                    continue

                project_id = generate_project_id(root_path)
                team = infer_team(abs_path, confidence)

                project = {
                    'id': project_id,
                    'name': root_path.name,
                    'team': team,
                    'folder_path': abs_path,
                    'privacy': 'public',
                    'themes': [],
                    'aliases': [],
                    'slack_channels': [],
                    '_discovery': {
                        'confidence': round(confidence, 2),
                        'indicators': indicators,
                    }
                }

                discovered.append(project)
                known_paths.add(abs_path)

                if verbose:
                    confidence_pct = int(confidence * 100)
                    print(f"  Found: {root_path.name} ({team}) [{confidence_pct}% confidence]")
                    for ind in indicators[:3]:
                        print(f"    - {ind}")

    # Sort by confidence (highest first)
    discovered.sort(key=lambda p: -p.get('_discovery', {}).get('confidence', 0))

    return discovered


def discover_as_proposed_changes(
    base_paths: List[str],
    max_depth: int = 3,
    verbose: bool = False,
    min_confidence: float = 0.5
) -> List[ProposedChange]:
    """
    Discover projects and return as ProposedChange entries for approval workflow.

    Returns:
        List of ProposedChange entries with change_type='new_project'
    """
    discovered = discover_projects(base_paths, max_depth, verbose, min_confidence)
    changes = []

    for project in discovered:
        discovery_info = project.pop('_discovery', {})
        confidence = discovery_info.get('confidence', 0)
        indicators = discovery_info.get('indicators', [])

        change = ProposedChange(
            id=str(uuid4())[:8],
            change_type='new_project',
            description=f"Add '{project['name']}' as new project ({int(confidence * 100)}% confidence)",
            details={
                'project': project,
                'confidence': confidence,
                'indicators': indicators,
            }
        )
        changes.append(change)

    return changes


def add_projects(new_projects: List[dict], dry_run: bool = False) -> int:
    """Add discovered projects to config.

    Args:
        new_projects: List of project configs to add
        dry_run: If True, don't actually save

    Returns:
        Number of projects added
    """
    if not new_projects:
        return 0

    projects_config = load_config()
    projects_config['projects'].extend(new_projects)

    if not dry_run:
        save_config(projects_config)

    return len(new_projects)


def save_proposed_changes(changes: List[ProposedChange]):
    """Save proposed changes to roadmap for review."""
    from models import Roadmap
    from datetime import datetime

    roadmap_path = Path(__file__).parent.parent / "data" / "roadmap.json"
    roadmap = Roadmap.load(str(roadmap_path))

    # Append to existing pending changes
    roadmap.pending_changes.extend(changes)
    roadmap.last_updated = datetime.now()
    roadmap.save(str(roadmap_path))

    return len(changes)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Discover and add new projects")
    parser.add_argument("--base", type=str, action="append",
                        help="Base directory to scan (can specify multiple)")
    parser.add_argument("--depth", type=int, default=3,
                        help="Max folder depth to scan")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be added without saving")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Verbose output")
    parser.add_argument("--auto", action="store_true",
                        help="Use default base paths from settings")
    parser.add_argument("--min-confidence", type=float, default=0.5,
                        help="Minimum confidence threshold (0.0-1.0)")
    parser.add_argument("--approve", action="store_true",
                        help="Queue for approval workflow instead of auto-adding")

    args = parser.parse_args()

    # Determine base paths
    if args.auto or not args.base:
        # Use the main project folder as base
        base_paths = [
            "/Users/justinpaquette/Documents/sales eng projects v2"
        ]
    else:
        base_paths = args.base

    print(f"Scanning for new projects (max depth: {args.depth}, min confidence: {int(args.min_confidence * 100)}%)...")

    if args.approve:
        # Use approval workflow
        changes = discover_as_proposed_changes(
            base_paths, args.depth, args.verbose, args.min_confidence
        )

        if not changes:
            print("\nNo new projects found.")
            return

        print(f"\nDiscovered {len(changes)} new project(s):")
        for change in changes:
            proj = change.details.get('project', {})
            confidence = change.details.get('confidence', 0)
            print(f"  - {proj.get('name', 'Unknown')} ({proj.get('team', 'Unknown')}) [{int(confidence * 100)}%]")
            print(f"    Path: {proj.get('folder_path', 'Unknown')}")

        if args.dry_run:
            print("\n[Dry run - no changes queued]")
        else:
            count = save_proposed_changes(changes)
            print(f"\nQueued {count} project(s) for approval.")
            print("Use 'python cli/review.py list' to view and approve.")
    else:
        # Direct add (legacy behavior)
        discovered = discover_projects(base_paths, args.depth, args.verbose, args.min_confidence)

        if not discovered:
            print("\nNo new projects found.")
            return

        print(f"\nDiscovered {len(discovered)} new project(s):")
        for proj in discovered:
            discovery = proj.get('_discovery', {})
            confidence = discovery.get('confidence', 0)
            print(f"  - {proj['name']} ({proj['team']}) [{int(confidence * 100)}%]")
            print(f"    Path: {proj['folder_path']}")

        if args.dry_run:
            print("\n[Dry run - no changes made]")
        else:
            # Remove discovery metadata before saving
            for proj in discovered:
                proj.pop('_discovery', None)
            count = add_projects(discovered)
            print(f"\nAdded {count} project(s) to config/projects.json")


if __name__ == "__main__":
    main()
