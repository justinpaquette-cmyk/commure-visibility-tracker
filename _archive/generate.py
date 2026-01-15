#!/usr/bin/env python3
"""Generate recap UI data and optionally open in browser."""

import json
import os
import subprocess
import sys
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.nightly import (
    load_config, load_roadmap, collect_all_activities,
    categorize_activities, calculate_team_distribution
)
from collectors.claude import get_session_summary
from agent.weekly_wins import run_daily_wins, format_win_for_ui
from agent.auto_themes import run_auto_themes


def load_snapshots(days: int = 14) -> list:
    """Load historical snapshots for trends."""
    snapshot_file = Path(__file__).parent.parent / "data" / "history" / "daily_snapshots.json"

    if not snapshot_file.exists():
        return []

    with open(snapshot_file) as f:
        data = json.load(f)

    # Get snapshots from last N days
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [s for s in data.get("snapshots", []) if s.get("date", "") >= cutoff]


def calculate_trends(snapshots: list) -> dict:
    """Calculate week-over-week trends from snapshots."""
    if len(snapshots) < 2:
        return {}

    # Split into this week and last week
    today = datetime.now()
    week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")

    this_week = [s for s in snapshots if s.get("date", "") >= week_ago]
    last_week = [s for s in snapshots if s.get("date", "") < week_ago]

    if not this_week or not last_week:
        return {}

    # Calculate averages
    def avg(data, key):
        vals = [s.get(key, 0) for s in data]
        return sum(vals) / len(vals) if vals else 0

    this_avg = avg(this_week, "total_activities")
    last_avg = avg(last_week, "total_activities")

    # Calculate percentage change
    if last_avg > 0:
        activities_change = round((this_avg - last_avg) / last_avg * 100)
    else:
        activities_change = 0

    # Activity sparkline data (last 7 days)
    sparkline = []
    for i in range(7):
        date = (today - timedelta(days=6-i)).strftime("%Y-%m-%d")
        day_data = next((s for s in snapshots if s.get("date") == date), None)
        sparkline.append(day_data.get("total_activities", 0) if day_data else 0)

    return {
        "activities_change": activities_change,
        "sparkline": sparkline,
        "days_tracked": len(snapshots),
        "this_week_avg": round(this_avg, 1),
        "last_week_avg": round(last_avg, 1),
    }


def generate_ui_data(lookback_hours: int = 24, include_wins: bool = True, auto_themes: bool = True) -> dict:
    """Generate data for the recap UI."""
    settings, projects_config = load_config()

    # Collect activities first
    activities = collect_all_activities(lookback_hours, verbose=False)

    # Run auto-theme detection and status updates
    if auto_themes and activities:
        run_auto_themes(activities, auto_add=True, auto_status=True, verbose=False)

    # Load roadmap (after auto-themes may have modified it)
    roadmap = load_roadmap()

    # Categorize activities
    categorized = categorize_activities(activities, roadmap, projects_config)
    distribution = calculate_team_distribution(categorized, roadmap)
    claude_summary = get_session_summary(lookback_hours)

    # Load trends data
    snapshots = load_snapshots(14)
    trends = calculate_trends(snapshots)

    # Get wins for daily view
    wins = []
    if include_wins and lookback_hours <= 48:  # Only for daily/short lookbacks
        daily_wins = run_daily_wins(activities=activities)
        wins = [format_win_for_ui(w) for w in daily_wins]

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
        'trends': trends,
        'wins': wins,
    }

    return ui_data


def generate_all_views() -> dict:
    """Generate data for all time views (today, week, month)."""
    views = {
        'today': generate_ui_data(24, include_wins=True),
        'week': generate_ui_data(168, include_wins=False),   # 7 days
        'month': generate_ui_data(720, include_wins=False),  # 30 days
    }
    return {
        'generated_at': datetime.now().isoformat(),
        'views': views,
        'default_view': 'today',
    }


def save_ui_data(data: dict, output_dir: Path = None):
    """Save UI data to JSON file."""
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_file = output_dir / "recap-data.json"
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)

    return output_file


def generate_standalone_html(data: dict, output_dir: Path = None) -> Path:
    """Generate a standalone HTML file with embedded data."""
    if output_dir is None:
        output_dir = Path(__file__).parent

    template_file = output_dir / "recap.html"
    output_file = output_dir / "recap-standalone.html"

    with open(template_file) as f:
        html = f.read()

    # Embed data as a script tag before the main script
    data_script = f"""<script>
        // Embedded data (generated {datetime.now().strftime('%Y-%m-%d %H:%M')})
        window.RECAP_DATA = {json.dumps(data)};
    </script>
    <script>"""

    # Replace the opening script tag with our embedded data + script
    html = html.replace("<script>", data_script, 1)

    # Also update loadRecapData to use embedded data
    html = html.replace(
        "const response = await fetch('recap-data.json');",
        "const response = { ok: true, json: async () => window.RECAP_DATA }; // Use embedded data"
    )

    with open(output_file, 'w') as f:
        f.write(html)

    return output_file


def open_ui(output_dir: Path = None, standalone: bool = True):
    """Open the recap UI in the default browser."""
    if output_dir is None:
        output_dir = Path(__file__).parent

    if standalone:
        html_file = output_dir / "recap-standalone.html"
    else:
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
    parser.add_argument("--hours", type=int, default=None, help="Hours to look back (default: generate all views)")
    parser.add_argument("--open", "-o", action="store_true", help="Open in browser after generating")
    parser.add_argument("--json-only", action="store_true", help="Only output JSON to stdout")
    parser.add_argument("--all-views", action="store_true", help="Generate all time views (today/week/month)")

    args = parser.parse_args()

    # Default behavior: generate all views
    if args.hours is None or args.all_views:
        print("Generating all views (today, week, month)...")
        data = generate_all_views()
    else:
        print(f"Generating recap data ({args.hours} hours)...")
        data = generate_ui_data(args.hours)

    if args.json_only:
        print(json.dumps(data, indent=2))
        return

    output_file = save_ui_data(data)
    print(f"Saved to: {output_file}")

    # Also generate standalone HTML with embedded data
    standalone_file = generate_standalone_html(data)
    print(f"Standalone: {standalone_file}")

    if args.open:
        open_ui(standalone=True)


if __name__ == "__main__":
    main()
