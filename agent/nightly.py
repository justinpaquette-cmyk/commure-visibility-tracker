#!/usr/bin/env python3
"""Nightly recap agent.

Collects activities, reconciles with roadmap, and drafts proposed updates.
Designed to be run manually via `/recap` command in Claude Code.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List
from uuid import uuid4
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import (
    Activity, ActivitySource, Roadmap, Theme, ThemeStatus,
    Task, TaskStatus, ProposedChange, Project
)
from collectors.filesystem import collect_activities as collect_fs
from collectors.git import collect_activities as collect_git
from collectors.claude import collect_activities as collect_claude
from collectors.claude import get_session_summary as get_claude_summary


def load_config():
    """Load configuration files."""
    config_dir = Path(__file__).parent.parent / "config"

    with open(config_dir / "settings.json") as f:
        settings = json.load(f)

    with open(config_dir / "projects.json") as f:
        projects = json.load(f)

    return settings, projects


def load_roadmap() -> Roadmap:
    """Load current roadmap."""
    roadmap_path = Path(__file__).parent.parent / "data" / "roadmap.json"
    return Roadmap.load(str(roadmap_path))


def save_roadmap(roadmap: Roadmap):
    """Save roadmap."""
    roadmap_path = Path(__file__).parent.parent / "data" / "roadmap.json"
    roadmap.save(str(roadmap_path))


def load_todays_activities() -> List[Activity]:
    """Load activities already collected today."""
    data_dir = Path(__file__).parent.parent / "data" / "activities"
    today = datetime.now().strftime("%Y-%m-%d")
    filepath = data_dir / f"{today}.json"

    if not filepath.exists():
        return []

    with open(filepath) as f:
        data = json.load(f)
        return [Activity.from_dict(a) for a in data.get("activities", [])]


def collect_all_activities(lookback_hours: int = 24, verbose: bool = False) -> List[Activity]:
    """Collect activities from all sources."""
    activities = []

    if verbose:
        print("Collecting file system activities...")
    fs_activities = collect_fs(lookback_hours=lookback_hours, verbose=verbose)
    activities.extend(fs_activities)

    if verbose:
        print("\nCollecting git activities...")
    git_activities = collect_git(lookback_hours=lookback_hours, verbose=verbose)
    activities.extend(git_activities)

    if verbose:
        print("\nCollecting Claude Code activities...")
    claude_activities = collect_claude(lookback_hours=lookback_hours, verbose=verbose)
    activities.extend(claude_activities)

    # Load any manual activities from today
    if verbose:
        print("\nLoading manual activities...")
    manual = load_todays_activities()
    manual_only = [a for a in manual if a.source == ActivitySource.MANUAL]
    activities.extend(manual_only)

    # Sort by timestamp
    activities.sort(key=lambda a: a.timestamp, reverse=True)

    if verbose:
        print(f"\nTotal: {len(activities)} activities")

    return activities


def categorize_activities(
    activities: List[Activity],
    roadmap: Roadmap,
    projects_config: dict
) -> dict:
    """
    Categorize activities by project and theme.

    Returns:
        {
            "by_project": {project_name: [activities]},
            "by_theme": {theme_id: [activities]},
            "uncategorized": [activities],
            "summary": {...}
        }
    """
    result = {
        "by_project": defaultdict(list),
        "by_theme": defaultdict(list),
        "uncategorized": [],
        "summary": {
            "total_activities": len(activities),
            "projects_touched": set(),
            "sources": defaultdict(int),
        }
    }

    # Build theme lookup
    theme_keywords = {}
    for project in roadmap.projects:
        for theme in project.themes:
            # Create keyword associations
            words = theme.name.lower().split()
            for word in words:
                if len(word) > 3:  # Skip short words
                    theme_keywords[word] = theme

    for activity in activities:
        result["summary"]["sources"][activity.source.value] += 1

        # Try to find project
        project_name = activity.raw_data.get("project")
        if project_name:
            result["by_project"][project_name].append(activity)
            result["summary"]["projects_touched"].add(project_name)

            # Try to match theme by keywords in description
            desc_lower = activity.description.lower()
            matched_theme = None
            for keyword, theme in theme_keywords.items():
                if keyword in desc_lower:
                    matched_theme = theme
                    break

            if matched_theme:
                result["by_theme"][matched_theme.id].append(activity)
            else:
                result["uncategorized"].append(activity)
        else:
            result["uncategorized"].append(activity)

    # Convert set to list for JSON serialization
    result["summary"]["projects_touched"] = list(result["summary"]["projects_touched"])
    result["summary"]["sources"] = dict(result["summary"]["sources"])

    return result


def generate_proposed_changes(
    categorized: dict,
    roadmap: Roadmap,
    settings: dict
) -> List[ProposedChange]:
    """Generate proposed changes based on detected activity."""
    changes = []
    stale_days = settings.get("stale_threshold_days", 7)
    now = datetime.now()

    # Check for themes that should be marked active
    for theme_id, activities in categorized["by_theme"].items():
        # Find the theme
        for project in roadmap.projects:
            for theme in project.themes:
                if theme.id == theme_id:
                    if theme.status == ThemeStatus.PLANNED and len(activities) > 0:
                        changes.append(ProposedChange(
                            id=str(uuid4())[:8],
                            change_type="status_change",
                            description=f"Mark '{theme.name}' as ACTIVE (detected {len(activities)} activities)",
                            details={
                                "theme_id": theme_id,
                                "old_status": theme.status.value,
                                "new_status": "active",
                                "activity_count": len(activities),
                            }
                        ))
                    break

    # Check for stale active themes
    for project in roadmap.projects:
        for theme in project.themes:
            if theme.status == ThemeStatus.ACTIVE:
                activities = categorized["by_theme"].get(theme.id, [])
                if not activities:
                    # No recent activity - might be stale
                    if theme.last_touched:
                        days_since = (now - theme.last_touched).days
                        if days_since > stale_days:
                            changes.append(ProposedChange(
                                id=str(uuid4())[:8],
                                change_type="stale_warning",
                                description=f"'{theme.name}' has no activity for {days_since} days",
                                details={
                                    "theme_id": theme.id,
                                    "days_since_activity": days_since,
                                    "suggested_action": "Mark as blocked or complete?",
                                }
                            ))

    # Suggest new themes for uncategorized work
    if categorized["uncategorized"]:
        # Group by project
        by_project = defaultdict(list)
        for activity in categorized["uncategorized"]:
            project = activity.raw_data.get("project", "Unknown")
            by_project[project].append(activity)

        for project_name, activities in by_project.items():
            if len(activities) >= 3:  # Significant uncategorized work
                changes.append(ProposedChange(
                    id=str(uuid4())[:8],
                    change_type="new_theme_suggestion",
                    description=f"Consider creating a theme for work in '{project_name}' ({len(activities)} activities)",
                    details={
                        "project": project_name,
                        "activity_count": len(activities),
                        "sample_descriptions": [a.description for a in activities[:5]],
                    }
                ))

    return changes


def calculate_team_distribution(categorized: dict, roadmap: Roadmap) -> dict:
    """Calculate work distribution by team."""
    team_activities = defaultdict(int)

    for project in roadmap.projects:
        project_activities = categorized["by_project"].get(project.name, [])
        team_activities[project.team] += len(project_activities)

    total = sum(team_activities.values())
    if total == 0:
        return {}

    return {
        team: {
            "count": count,
            "percentage": round(count / total * 100)
        }
        for team, count in team_activities.items()
    }


def format_recap(
    categorized: dict,
    changes: List[ProposedChange],
    roadmap: Roadmap,
    distribution: dict,
    claude_summary: dict = None
) -> str:
    """Format the recap as a readable summary."""
    lines = []
    now = datetime.now()

    lines.append("=" * 60)
    lines.append(f"DAILY RECAP - {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 60)

    # Summary
    summary = categorized["summary"]
    lines.append(f"\nTotal activities: {summary['total_activities']}")
    lines.append(f"Projects touched: {', '.join(summary['projects_touched']) or 'None'}")
    lines.append(f"Sources: {', '.join(f'{k}({v})' for k, v in summary['sources'].items())}")

    # Claude Code summary
    if claude_summary and claude_summary.get('total_sessions', 0) > 0:
        lines.append(f"\n## Claude Code Sessions")
        lines.append(f"  Active sessions: {claude_summary['total_sessions']}")
        lines.append(f"  Total messages: {claude_summary['total_messages']}")
        lines.append(f"  Files edited: {claude_summary['total_files_edited']}")
        if claude_summary.get('tools_breakdown'):
            top_tools = sorted(claude_summary['tools_breakdown'].items(), key=lambda x: -x[1])[:5]
            lines.append(f"  Top tools: {', '.join(f'{t}({c})' for t, c in top_tools)}")

    # Team distribution
    if distribution:
        lines.append("\n## Team Distribution")
        for team, data in distribution.items():
            lines.append(f"  {team}: {data['percentage']}% ({data['count']} activities)")

    # Active themes with activity
    lines.append("\n## Activity by Theme")
    for project in roadmap.projects:
        project_activities = categorized["by_project"].get(project.name, [])
        if not project_activities:
            continue

        lines.append(f"\n### {project.name} ({project.team})")
        for theme in project.themes:
            theme_activities = categorized["by_theme"].get(theme.id, [])
            if theme_activities:
                status_icon = {
                    ThemeStatus.PLANNED: "○",
                    ThemeStatus.ACTIVE: "●",
                    ThemeStatus.BLOCKED: "!",
                    ThemeStatus.COMPLETE: "✓",
                }.get(theme.status, " ")
                lines.append(f"  [{status_icon}] {theme.name}: {len(theme_activities)} activities")

    # Uncategorized work
    if categorized["uncategorized"]:
        lines.append(f"\n## Uncategorized ({len(categorized['uncategorized'])} activities)")
        for activity in categorized["uncategorized"][:5]:
            lines.append(f"  - {activity.description[:60]}")
        if len(categorized["uncategorized"]) > 5:
            lines.append(f"  ... and {len(categorized['uncategorized']) - 5} more")

    # Proposed changes
    if changes:
        lines.append("\n## Proposed Changes (Review Required)")
        for i, change in enumerate(changes, 1):
            lines.append(f"\n  {i}. [{change.change_type}] {change.description}")
            if change.change_type == "new_theme_suggestion":
                samples = change.details.get("sample_descriptions", [])[:2]
                for sample in samples:
                    lines.append(f"       - {sample[:50]}")

    lines.append("\n" + "=" * 60)

    return "\n".join(lines)


def run_recap(lookback_hours: int = 24, verbose: bool = False, save: bool = True):
    """Run the full recap workflow."""
    settings, projects_config = load_config()
    roadmap = load_roadmap()

    # Collect activities
    if verbose:
        print("Collecting activities...\n")
    activities = collect_all_activities(lookback_hours, verbose)

    # Categorize
    if verbose:
        print("\nCategorizing activities...")
    categorized = categorize_activities(activities, roadmap, projects_config)

    # Generate proposed changes
    if verbose:
        print("Generating proposed changes...")
    changes = generate_proposed_changes(categorized, roadmap, settings)

    # Calculate distribution
    distribution = calculate_team_distribution(categorized, roadmap)

    # Get Claude session summary
    claude_summary = get_claude_summary(lookback_hours)

    # Format recap
    recap = format_recap(categorized, changes, roadmap, distribution, claude_summary)

    # Save proposed changes to roadmap
    if save and changes:
        # Clear old pending changes
        roadmap.pending_changes = changes
        roadmap.last_updated = datetime.now()
        save_roadmap(roadmap)
        if verbose:
            print(f"\nSaved {len(changes)} proposed changes to roadmap")

    return recap, changes


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run nightly recap")
    parser.add_argument("--hours", type=int, default=24, help="Hours to look back")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--no-save", action="store_true", help="Don't save proposed changes")

    args = parser.parse_args()

    recap, changes = run_recap(
        lookback_hours=args.hours,
        verbose=args.verbose,
        save=not args.no_save
    )

    print(recap)

    if changes:
        print(f"\n{len(changes)} proposed change(s) saved for review.")
        print("Use 'python cli/review.py' to approve or reject changes.")


if __name__ == "__main__":
    main()
