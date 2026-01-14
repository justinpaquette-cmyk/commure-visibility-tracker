#!/usr/bin/env python3
"""Weekly wins processor.

Runs every Friday at 9 AM to:
1. Collect all recap files from the past week
2. Analyze activities for potential wins
3. Generate a wins summary in the established format
4. Archive processed recaps
"""

import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Activity, ActivitySource


# Wins output directory (matches existing structure)
WINS_BASE = Path("/Users/justinpaquette/Documents/sales eng projects v2/Justin's_Wins/2026")


def get_current_quarter() -> str:
    """Get current quarter string like '2026-Q1'."""
    now = datetime.now()
    quarter = (now.month - 1) // 3 + 1
    return f"{now.year}-Q{quarter}"


def load_recap_files(days_back: int = 7) -> List[Dict[str, Any]]:
    """Load all recap files from the past N days."""
    recaps_dir = Path(__file__).parent.parent / "data" / "recaps"
    activities_dir = Path(__file__).parent.parent / "data" / "activities"

    since = datetime.now() - timedelta(days=days_back)
    recap_data = []

    # Load from recaps directory (text files from cron)
    if recaps_dir.exists():
        for f in recaps_dir.glob("*.txt"):
            try:
                date_str = f.stem
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                if file_date >= since:
                    with open(f, 'r') as fp:
                        recap_data.append({
                            'date': date_str,
                            'type': 'recap_text',
                            'content': fp.read(),
                            'path': str(f),
                        })
            except (ValueError, IOError):
                continue

    # Load from activities directory (JSON files)
    if activities_dir.exists():
        for f in activities_dir.glob("*.json"):
            try:
                date_str = f.stem
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                if file_date >= since:
                    with open(f, 'r') as fp:
                        data = json.load(fp)
                        activities = [Activity.from_dict(a) for a in data.get('activities', [])]
                        recap_data.append({
                            'date': date_str,
                            'type': 'activities_json',
                            'activities': activities,
                            'path': str(f),
                        })
            except (ValueError, IOError, json.JSONDecodeError):
                continue

    return sorted(recap_data, key=lambda x: x['date'])


def analyze_activities_for_wins(activities: List[Activity]) -> List[Dict[str, Any]]:
    """
    Analyze activities and identify potential wins.

    Looks for:
    - Significant file edits (many files in one session)
    - Completed features (keywords like "complete", "finish", "ship")
    - High-impact tasks (keywords like "fix", "build", "create", "implement")
    - Cross-project work
    """
    potential_wins = []

    # Group by project
    by_project = defaultdict(list)
    for activity in activities:
        project = activity.raw_data.get('project', 'Unknown')
        by_project[project].append(activity)

    # Analyze each project's activities
    for project, project_activities in by_project.items():
        if len(project_activities) < 2:
            continue

        # Look for significant Claude Code sessions
        claude_activities = [a for a in project_activities if a.source == ActivitySource.CLAUDE]
        for activity in claude_activities:
            files_edited = len(activity.raw_data.get('files_edited', []))
            task_descriptions = activity.raw_data.get('task_descriptions', [])

            # Significant session (many files or multiple tasks)
            if files_edited >= 5 or len(task_descriptions) >= 3:
                potential_wins.append({
                    'project': project,
                    'type': 'significant_session',
                    'description': activity.description,
                    'files_edited': files_edited,
                    'tasks': task_descriptions[:3],
                    'timestamp': activity.timestamp,
                    'confidence': 0.7,
                })

        # Look for git commits with significant keywords
        git_activities = [a for a in project_activities if a.source == ActivitySource.GIT]
        significant_keywords = ['complete', 'finish', 'ship', 'launch', 'deploy', 'fix', 'implement', 'add', 'create', 'build']

        for activity in git_activities:
            desc_lower = activity.description.lower()
            if any(kw in desc_lower for kw in significant_keywords):
                files_changed = activity.raw_data.get('files_changed', [])
                if len(files_changed) >= 3 or any(kw in desc_lower for kw in ['complete', 'finish', 'ship']):
                    potential_wins.append({
                        'project': project,
                        'type': 'git_milestone',
                        'description': activity.description,
                        'files_changed': len(files_changed),
                        'timestamp': activity.timestamp,
                        'confidence': 0.8,
                    })

        # Look for patterns indicating completed work
        total_files = sum(
            len(a.raw_data.get('files_edited', [])) + len(a.raw_data.get('files_changed', []))
            for a in project_activities
        )

        if total_files >= 10:
            potential_wins.append({
                'project': project,
                'type': 'sustained_effort',
                'description': f"Significant work on {project}",
                'total_files': total_files,
                'activity_count': len(project_activities),
                'timestamp': max(a.timestamp for a in project_activities),
                'confidence': 0.6,
            })

    # Sort by confidence and timestamp
    potential_wins.sort(key=lambda x: (-x['confidence'], x['timestamp']), reverse=True)

    return potential_wins


def format_win_entry(win: Dict[str, Any], index: int) -> str:
    """Format a single win entry in the established markdown format."""
    date = win['timestamp'].strftime('%B %Y')
    project = win['project']

    # Generate summary based on win type
    if win['type'] == 'significant_session':
        summary = f"AI-assisted development session editing {win['files_edited']} files"
        if win.get('tasks'):
            summary = win['tasks'][0].replace('[Claude] ', '')
    elif win['type'] == 'git_milestone':
        summary = win['description'].split('] ')[-1] if '] ' in win['description'] else win['description']
    else:
        summary = win['description']

    # Determine category
    category = "Development"
    if 'demo' in summary.lower():
        category = "Demo | POC"
    elif 'fix' in summary.lower():
        category = "Bug Fix"
    elif 'test' in summary.lower():
        category = "Testing"

    return f"""
### {index}. {summary[:60]}{'...' if len(summary) > 60 else ''}
**Date:** {date}
**Category:** {category}
**Project:** {project}

**Summary:**
{summary}

**Evidence:**
- {win.get('files_edited', win.get('total_files', 0))} files modified
- Activity detected via {win['type'].replace('_', ' ')}

---
"""


def generate_weekly_wins_summary(wins: List[Dict[str, Any]], week_start: datetime) -> str:
    """Generate the weekly wins summary document."""
    week_end = week_start + timedelta(days=6)
    week_range = f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')}"

    header = f"""# Weekly Wins Summary
## Week of {week_range}

*Auto-generated from daily activity tracking*

---

## Highlights This Week

"""

    # Group wins by project
    by_project = defaultdict(list)
    for win in wins:
        by_project[win['project']].append(win)

    body = ""
    win_index = 1

    for project, project_wins in by_project.items():
        body += f"\n## {project}\n"
        for win in project_wins[:3]:  # Top 3 per project
            body += format_win_entry(win, win_index)
            win_index += 1

    footer = f"""

---

## Summary Statistics

- **Total potential wins identified:** {len(wins)}
- **Projects with activity:** {len(by_project)}
- **Week:** {week_range}

*Review and refine these auto-detected wins for your official wins document.*
"""

    return header + body + footer


def archive_processed_recaps(recap_files: List[Dict[str, Any]]):
    """Move processed recap files to archive."""
    archive_dir = Path(__file__).parent.parent / "data" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    for recap in recap_files:
        if 'path' in recap:
            src = Path(recap['path'])
            if src.exists():
                # Create year-month subdirectory
                date = datetime.strptime(recap['date'], "%Y-%m-%d")
                month_dir = archive_dir / date.strftime("%Y-%m")
                month_dir.mkdir(exist_ok=True)

                dst = month_dir / src.name
                shutil.move(str(src), str(dst))


def run_weekly_wins(
    days_back: int = 7,
    archive: bool = True,
    output_dir: Optional[Path] = None
) -> str:
    """
    Run the weekly wins extraction process.

    Args:
        days_back: Number of days to look back
        archive: Whether to archive processed files
        output_dir: Where to save the wins summary

    Returns:
        Path to the generated wins file
    """
    print(f"Loading recaps from the past {days_back} days...")
    recap_files = load_recap_files(days_back)

    if not recap_files:
        print("No recap files found.")
        return ""

    print(f"Found {len(recap_files)} recap files")

    # Collect all activities
    all_activities = []
    for recap in recap_files:
        if recap['type'] == 'activities_json':
            all_activities.extend(recap['activities'])

    print(f"Analyzing {len(all_activities)} activities...")
    potential_wins = analyze_activities_for_wins(all_activities)

    if not potential_wins:
        print("No significant wins detected.")
        return ""

    print(f"Found {len(potential_wins)} potential wins")

    # Calculate week start (Monday of the week being processed)
    oldest_date = min(datetime.strptime(r['date'], "%Y-%m-%d") for r in recap_files)
    week_start = oldest_date - timedelta(days=oldest_date.weekday())

    # Generate summary
    summary = generate_weekly_wins_summary(potential_wins, week_start)

    # Determine output path
    if output_dir is None:
        quarter = get_current_quarter()
        output_dir = WINS_BASE / quarter
    output_dir.mkdir(parents=True, exist_ok=True)

    week_str = week_start.strftime("%Y-W%W")
    output_file = output_dir / f"weekly_wins_{week_str}.md"

    with open(output_file, 'w') as f:
        f.write(summary)

    print(f"Wins summary saved to: {output_file}")

    # Archive processed files
    if archive:
        print("Archiving processed recap files...")
        archive_processed_recaps(recap_files)

    return str(output_file)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Process weekly wins from recaps")
    parser.add_argument("--days", type=int, default=7, help="Days to look back")
    parser.add_argument("--no-archive", action="store_true", help="Don't archive processed files")
    parser.add_argument("--output", "-o", help="Output directory for wins file")

    args = parser.parse_args()

    output_dir = Path(args.output) if args.output else None

    result = run_weekly_wins(
        days_back=args.days,
        archive=not args.no_archive,
        output_dir=output_dir
    )

    if result:
        print(f"\nWeekly wins processing complete!")
        print(f"Output: {result}")


if __name__ == "__main__":
    main()
