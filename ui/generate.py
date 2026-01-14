#!/usr/bin/env python3
"""Generate recap UI data and optionally open in browser."""

import json
import os
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.nightly import (
    load_config, load_roadmap, collect_all_activities,
    categorize_activities, calculate_team_distribution
)
from collectors.claude import get_session_summary


def generate_ui_data(lookback_hours: int = 24) -> dict:
    """Generate data for the recap UI."""
    settings, projects_config = load_config()
    roadmap = load_roadmap()

    # Collect and categorize
    activities = collect_all_activities(lookback_hours, verbose=False)
    categorized = categorize_activities(activities, roadmap, projects_config)
    distribution = calculate_team_distribution(categorized, roadmap)
    claude_summary = get_session_summary(lookback_hours)

    # Build themes list
    themes = []
    for project in roadmap.projects:
        for theme in project.themes:
            theme_activities = categorized["by_theme"].get(theme.id, [])
            if theme_activities or theme.status.value == 'active':
                themes.append({
                    'name': theme.name,
                    'project': project.name,
                    'status': theme.status.value,
                    'count': len(theme_activities),
                })

    # Sort themes by activity count
    themes.sort(key=lambda x: -x['count'])

    # Get source breakdown
    sources = categorized["summary"].get("sources", {})

    # Build UI data
    ui_data = {
        'date': datetime.now().strftime('%B %d, %Y'),
        'total_activities': categorized["summary"]["total_activities"],
        'projects_touched': len(categorized["summary"]["projects_touched"]),
        'claude_sessions': claude_summary.get('total_sessions', 0),
        'files_edited': claude_summary.get('total_files_edited', 0),
        'team_a_pct': list(distribution.values())[0]['percentage'] if distribution else 50,
        'team_a_name': list(distribution.keys())[0] if distribution else 'Team A',
        'team_b_name': list(distribution.keys())[1] if len(distribution) > 1 else 'Team B',
        'themes': themes[:6],  # Top 6 themes
        'sources': {
            'claude': sources.get('claude', 0),
            'filesystem': sources.get('filesystem', 0),
            'git': sources.get('git', 0),
            'slack': sources.get('slack', 0),
            'manual': sources.get('manual', 0),
        },
        'claude_messages': claude_summary.get('total_messages', 0),
        'claude_tools': sum(claude_summary.get('tools_breakdown', {}).values()),
    }

    return ui_data


def save_ui_data(data: dict, output_dir: Path = None):
    """Save UI data to JSON file."""
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_file = output_dir / "recap-data.json"
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)

    return output_file


def open_ui(output_dir: Path = None):
    """Open the recap UI in the default browser."""
    if output_dir is None:
        output_dir = Path(__file__).parent

    html_file = output_dir / "recap.html"

    if not html_file.exists():
        print(f"Error: {html_file} not found")
        return

    # Open in browser
    webbrowser.open(f"file://{html_file}")
    print(f"Opened {html_file} in browser")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate recap UI")
    parser.add_argument("--hours", type=int, default=24, help="Hours to look back")
    parser.add_argument("--open", "-o", action="store_true", help="Open in browser after generating")
    parser.add_argument("--json-only", action="store_true", help="Only output JSON to stdout")

    args = parser.parse_args()

    print("Generating recap data...")
    data = generate_ui_data(args.hours)

    if args.json_only:
        print(json.dumps(data, indent=2))
        return

    output_file = save_ui_data(data)
    print(f"Saved to: {output_file}")

    if args.open:
        open_ui()


if __name__ == "__main__":
    main()
