#!/usr/bin/env python3
"""Auto-theme detection and status management.

Automatically:
1. Detects new themes from recurring activity patterns
2. Updates theme status based on activity signals
"""

import json
import re
import sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Activity, ActivitySource, Roadmap, Theme, ThemeStatus, Project


# Keywords that signal completion
COMPLETION_KEYWORDS = [
    'ship', 'shipped', 'launch', 'launched', 'deploy', 'deployed',
    'complete', 'completed', 'finish', 'finished', 'done', 'released',
    'live', 'published', 'delivered'
]

# Keywords that signal blocking
BLOCKED_KEYWORDS = [
    'blocked', 'waiting', 'stuck', 'paused', 'on hold', 'pending review'
]

# Minimum activities to auto-create a theme
MIN_ACTIVITIES_FOR_THEME = 3

# Days without activity before marking potentially stale
STALE_THRESHOLD_DAYS = 7


def load_roadmap() -> Roadmap:
    """Load current roadmap."""
    roadmap_path = Path(__file__).parent.parent / "data" / "roadmap.json"
    return Roadmap.load(str(roadmap_path))


def save_roadmap(roadmap: Roadmap):
    """Save roadmap."""
    roadmap_path = Path(__file__).parent.parent / "data" / "roadmap.json"
    roadmap.save(str(roadmap_path))


def extract_theme_name(activities: List[Activity]) -> str:
    """Extract a theme name from activity descriptions."""
    # Collect all descriptions and task names
    texts = []
    for a in activities:
        texts.append(a.description)
        texts.extend(a.raw_data.get('task_descriptions', []))

    # Find common significant words
    word_counts = Counter()
    stopwords = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
        'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
        'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it',
        'we', 'they', 'what', 'which', 'who', 'when', 'where', 'why', 'how',
        'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other',
        'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so',
        'than', 'too', 'very', 'just', 'claude', 'modified', 'files', 'file',
        'add', 'added', 'update', 'updated', 'fix', 'fixed', 'create', 'created'
    }

    for text in texts:
        # Clean and tokenize
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        for word in words:
            if word not in stopwords:
                word_counts[word] += 1

    # Get top words
    top_words = [word for word, count in word_counts.most_common(3) if count >= 2]

    if top_words:
        # Capitalize and join
        return ' '.join(word.capitalize() for word in top_words)

    # Fallback: use first activity's key terms
    if texts:
        first = texts[0]
        # Remove common prefixes
        first = re.sub(r'^\[.*?\]\s*', '', first)
        first = re.sub(r'^Modified \d+ files in ', '', first)
        # Take first few words
        words = first.split()[:4]
        return ' '.join(words).strip('.,;:')

    return "Development Work"


def detect_new_themes(
    activities: List[Activity],
    roadmap: Roadmap,
    min_activities: int = MIN_ACTIVITIES_FOR_THEME
) -> List[Dict[str, Any]]:
    """
    Detect potential new themes from activity patterns.

    Groups uncategorized activities by project and semantic similarity,
    then suggests themes for groups that meet the threshold.
    """
    new_themes = []

    # Get existing theme IDs
    existing_theme_ids = set()
    for project in roadmap.projects:
        for theme in project.themes:
            existing_theme_ids.add(theme.id)

    # Group activities by project
    by_project = defaultdict(list)
    for activity in activities:
        project_name = activity.raw_data.get('project', 'Unknown')
        # Skip if already matched to a theme
        if activity.raw_data.get('theme_id') in existing_theme_ids:
            continue
        by_project[project_name].append(activity)

    # Analyze each project's uncategorized activities
    for project_name, project_activities in by_project.items():
        if len(project_activities) < min_activities:
            continue

        # Skip generic project names
        if project_name in ('Unknown', 'Slack', 'git'):
            continue

        # Find the roadmap project
        roadmap_project = None
        for p in roadmap.projects:
            if p.name == project_name:
                roadmap_project = p
                break

        if not roadmap_project:
            continue

        # Extract a theme name from the activities
        theme_name = extract_theme_name(project_activities)

        # Generate theme ID
        theme_id = re.sub(r'[^a-z0-9]+', '-', theme_name.lower()).strip('-')

        # Check if similar theme already exists
        existing_names = [t.name.lower() for t in roadmap_project.themes]
        if theme_name.lower() in existing_names:
            continue

        new_themes.append({
            'project_name': project_name,
            'theme': {
                'id': theme_id,
                'name': theme_name,
                'status': 'active',  # Auto-detected themes start as active
                'notes': f'Auto-detected from {len(project_activities)} activities',
            },
            'activity_count': len(project_activities),
            'sample_descriptions': [a.description for a in project_activities[:3]],
        })

    return new_themes


def check_completion_signals(activities: List[Activity]) -> Tuple[bool, str]:
    """Check if activities contain completion signals."""
    for activity in activities:
        text = activity.description.lower()
        for task in activity.raw_data.get('task_descriptions', []):
            text += ' ' + task.lower()

        for keyword in COMPLETION_KEYWORDS:
            if keyword in text:
                return True, keyword

    return False, ''


def check_blocked_signals(activities: List[Activity]) -> Tuple[bool, str]:
    """Check if activities contain blocked signals."""
    for activity in activities:
        text = activity.description.lower()
        for task in activity.raw_data.get('task_descriptions', []):
            text += ' ' + task.lower()

        for keyword in BLOCKED_KEYWORDS:
            if keyword in text:
                return True, keyword

    return False, ''


def update_theme_statuses(
    activities: List[Activity],
    roadmap: Roadmap,
    stale_days: int = STALE_THRESHOLD_DAYS
) -> List[Dict[str, Any]]:
    """
    Update theme statuses based on activity signals.

    Returns list of status changes made.
    """
    changes = []
    now = datetime.now()

    # Group activities by theme
    by_theme = defaultdict(list)
    for activity in activities:
        theme_id = activity.raw_data.get('theme_id')
        if theme_id:
            by_theme[theme_id].append(activity)

    for project in roadmap.projects:
        for theme in project.themes:
            theme_activities = by_theme.get(theme.id, [])
            old_status = theme.status

            # Check for status transitions
            if theme.status == ThemeStatus.PLANNED:
                # Planned -> Active: Any activity detected
                if theme_activities:
                    theme.status = ThemeStatus.ACTIVE
                    theme.last_touched = now
                    changes.append({
                        'theme_id': theme.id,
                        'theme_name': theme.name,
                        'project': project.name,
                        'old_status': old_status.value,
                        'new_status': 'active',
                        'reason': f'Detected {len(theme_activities)} activities',
                    })

            elif theme.status == ThemeStatus.ACTIVE:
                # Active -> Complete: Completion keywords detected
                is_complete, keyword = check_completion_signals(theme_activities)
                if is_complete:
                    theme.status = ThemeStatus.COMPLETE
                    theme.last_touched = now
                    changes.append({
                        'theme_id': theme.id,
                        'theme_name': theme.name,
                        'project': project.name,
                        'old_status': old_status.value,
                        'new_status': 'complete',
                        'reason': f'Completion signal: "{keyword}"',
                    })
                    continue

                # Active -> Blocked: Blocked keywords detected
                is_blocked, keyword = check_blocked_signals(theme_activities)
                if is_blocked:
                    theme.status = ThemeStatus.BLOCKED
                    theme.last_touched = now
                    changes.append({
                        'theme_id': theme.id,
                        'theme_name': theme.name,
                        'project': project.name,
                        'old_status': old_status.value,
                        'new_status': 'blocked',
                        'reason': f'Blocked signal: "{keyword}"',
                    })
                    continue

                # Update last_touched if there's activity
                if theme_activities:
                    theme.last_touched = now

            elif theme.status == ThemeStatus.BLOCKED:
                # Blocked -> Active: New activity detected
                if theme_activities:
                    theme.status = ThemeStatus.ACTIVE
                    theme.last_touched = now
                    changes.append({
                        'theme_id': theme.id,
                        'theme_name': theme.name,
                        'project': project.name,
                        'old_status': old_status.value,
                        'new_status': 'active',
                        'reason': 'Activity resumed',
                    })

    return changes


def add_theme_to_project(roadmap: Roadmap, project_name: str, theme_data: dict) -> bool:
    """Add a new theme to a project in the roadmap."""
    for project in roadmap.projects:
        if project.name == project_name:
            # Check for duplicates
            if any(t.id == theme_data['id'] for t in project.themes):
                return False

            new_theme = Theme(
                id=theme_data['id'],
                name=theme_data['name'],
                status=ThemeStatus(theme_data.get('status', 'active')),
                notes=theme_data.get('notes', ''),
                last_touched=datetime.now()
            )
            project.themes.append(new_theme)
            return True

    return False


def run_auto_themes(
    activities: List[Activity],
    auto_add: bool = True,
    auto_status: bool = True,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Run automatic theme detection and status updates.

    Args:
        activities: List of activities to analyze
        auto_add: Automatically add detected themes (vs just return suggestions)
        auto_status: Automatically update theme statuses
        verbose: Print progress

    Returns:
        Summary of changes made
    """
    roadmap = load_roadmap()
    results = {
        'new_themes': [],
        'status_changes': [],
        'themes_added': 0,
        'statuses_updated': 0,
    }

    # Detect new themes
    if verbose:
        print("Detecting new themes from activity patterns...")

    new_themes = detect_new_themes(activities, roadmap)
    results['new_themes'] = new_themes

    if verbose and new_themes:
        print(f"  Found {len(new_themes)} potential new theme(s)")
        for t in new_themes:
            print(f"    - {t['theme']['name']} ({t['project_name']})")

    # Add themes if auto_add is enabled
    if auto_add and new_themes:
        for theme_info in new_themes:
            if add_theme_to_project(roadmap, theme_info['project_name'], theme_info['theme']):
                results['themes_added'] += 1
                if verbose:
                    print(f"  Added theme: {theme_info['theme']['name']}")

    # Update theme statuses
    if auto_status:
        if verbose:
            print("\nUpdating theme statuses...")

        status_changes = update_theme_statuses(activities, roadmap)
        results['status_changes'] = status_changes
        results['statuses_updated'] = len(status_changes)

        if verbose and status_changes:
            for change in status_changes:
                print(f"  {change['theme_name']}: {change['old_status']} -> {change['new_status']}")
                print(f"    Reason: {change['reason']}")

    # Save if changes were made
    if results['themes_added'] > 0 or results['statuses_updated'] > 0:
        roadmap.last_updated = datetime.now()
        save_roadmap(roadmap)
        if verbose:
            print(f"\nSaved roadmap with {results['themes_added']} new themes and {results['statuses_updated']} status updates")

    return results


def main():
    import argparse
    from agent.nightly import collect_all_activities

    parser = argparse.ArgumentParser(description="Auto-detect themes and update statuses")
    parser.add_argument("--hours", type=int, default=168, help="Hours to look back (default: 7 days)")
    parser.add_argument("--no-add", action="store_true", help="Don't auto-add new themes")
    parser.add_argument("--no-status", action="store_true", help="Don't auto-update statuses")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without saving")

    args = parser.parse_args()

    print(f"Analyzing activities from the past {args.hours} hours...")
    activities = collect_all_activities(args.hours, verbose=args.verbose)

    if not activities:
        print("No activities found.")
        return

    print(f"Found {len(activities)} activities\n")

    # In dry-run mode, don't actually add/update
    auto_add = not args.no_add and not args.dry_run
    auto_status = not args.no_status and not args.dry_run

    results = run_auto_themes(
        activities,
        auto_add=auto_add,
        auto_status=auto_status,
        verbose=True
    )

    if args.dry_run:
        print("\n[Dry run - no changes saved]")
    else:
        print(f"\nSummary:")
        print(f"  New themes added: {results['themes_added']}")
        print(f"  Status updates: {results['statuses_updated']}")


if __name__ == "__main__":
    main()
