#!/usr/bin/env python3
"""Weekly report generator.

Generates shareable weekly reports in HTML and Markdown formats.
Aggregates daily snapshots, wins, and activity summaries.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.nightly import load_config, load_roadmap, collect_all_activities, categorize_activities
from agent.weekly_wins import analyze_activities_for_wins
from agent.ai_summarizer import load_ai_summaries
from collectors.claude import get_session_summary


def load_weekly_snapshots() -> List[Dict]:
    """Load snapshots from the past 7 days."""
    snapshot_file = Path(__file__).parent.parent / "data" / "history" / "daily_snapshots.json"

    if not snapshot_file.exists():
        return []

    with open(snapshot_file) as f:
        data = json.load(f)

    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    return [s for s in data.get("snapshots", []) if s.get("date", "") >= cutoff]


def aggregate_week_stats(snapshots: List[Dict]) -> Dict:
    """Aggregate statistics across the week."""
    if not snapshots:
        return {}

    total_activities = sum(s.get("total_activities", 0) for s in snapshots)
    total_messages = sum(s.get("claude_messages", 0) for s in snapshots)
    total_files = sum(s.get("files_edited", 0) for s in snapshots)
    total_sessions = sum(s.get("claude_sessions", 0) for s in snapshots)

    # Aggregate by project
    by_project = {}
    for s in snapshots:
        for proj, count in s.get("by_project", {}).items():
            by_project[proj] = by_project.get(proj, 0) + count

    # Aggregate by team
    by_team = {}
    for s in snapshots:
        for team, count in s.get("by_team", {}).items():
            by_team[team] = by_team.get(team, 0) + count

    # Aggregate by source
    by_source = {}
    for s in snapshots:
        for source, count in s.get("by_source", {}).items():
            by_source[source] = by_source.get(source, 0) + count

    return {
        "days_tracked": len(snapshots),
        "total_activities": total_activities,
        "total_messages": total_messages,
        "total_files_edited": total_files,
        "total_sessions": total_sessions,
        "by_project": dict(sorted(by_project.items(), key=lambda x: -x[1])),
        "by_team": by_team,
        "by_source": by_source,
        "daily_average": round(total_activities / len(snapshots), 1) if snapshots else 0,
    }


def generate_markdown_report(
    week_stats: Dict,
    wins: List[Dict],
    roadmap,
    week_start: datetime,
    week_end: datetime,
    ai_summaries: List[Dict] = None
) -> str:
    """Generate weekly report in Markdown format."""
    lines = []

    # Header
    lines.append(f"# Weekly Activity Report")
    lines.append(f"**{week_start.strftime('%B %d')} - {week_end.strftime('%B %d, %Y')}**")
    lines.append("")

    # Executive Summary
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"- **{week_stats.get('total_activities', 0)}** total activities across **{week_stats.get('days_tracked', 0)}** days")
    lines.append(f"- **{len(week_stats.get('by_project', {}))}** projects touched")
    lines.append(f"- **{week_stats.get('total_files_edited', 0)}** files edited")
    lines.append(f"- **{week_stats.get('total_sessions', 0)}** Claude Code sessions")
    lines.append("")

    # Team Distribution
    by_team = week_stats.get('by_team', {})
    if by_team:
        total = sum(by_team.values())
        lines.append("## Team Distribution")
        lines.append("")
        for team, count in by_team.items():
            pct = round(count / total * 100) if total > 0 else 0
            lines.append(f"- **{team}**: {pct}% ({count} activities)")
        lines.append("")

    # Project Breakdown
    by_project = week_stats.get('by_project', {})
    if by_project:
        lines.append("## Project Activity")
        lines.append("")
        lines.append("| Project | Activities |")
        lines.append("|---------|------------|")
        for proj, count in list(by_project.items())[:10]:
            lines.append(f"| {proj} | {count} |")
        lines.append("")

    # Active Themes
    lines.append("## Active Themes")
    lines.append("")
    for project in roadmap.projects:
        active_themes = [t for t in project.themes if t.status.value == 'active']
        if active_themes:
            lines.append(f"### {project.name}")
            for theme in active_themes:
                lines.append(f"- {theme.name}")
            lines.append("")

    # Key Accomplishments - prefer AI summaries if available
    accomplishments_source = ai_summaries if ai_summaries else wins
    if accomplishments_source:
        lines.append("## Key Accomplishments")
        if ai_summaries:
            lines.append("*Enhanced with AI analysis*")
        lines.append("")

        for item in accomplishments_source[:5]:
            project = item.get('project', '')
            summary = item.get('summary', item.get('description', ''))
            files = item.get('files_modified', item.get('files_edited', 0))
            category = item.get('category', '')

            # Skip items with poor summaries
            if not summary or summary == "Development work completed":
                continue

            # Format nicely
            if project and project not in ('Unknown', '', 'tracker', 'task', 'pk', 'Project'):
                lines.append(f"- **{project}**: {summary}")
            else:
                lines.append(f"- {summary}")

            # Add category for AI summaries
            if ai_summaries and category:
                lines.append(f"  - Category: {category}")
            elif files and files > 5:
                lines.append(f"  - {files} files modified")
        lines.append("")

    # Source Breakdown
    by_source = week_stats.get('by_source', {})
    if by_source:
        lines.append("## Activity Sources")
        lines.append("")
        for source, count in by_source.items():
            lines.append(f"- **{source.title()}**: {count}")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Generated by Task Tracker on {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    return "\n".join(lines)


def generate_html_report(
    week_stats: Dict,
    wins: List[Dict],
    roadmap,
    week_start: datetime,
    week_end: datetime,
    ai_summaries: List[Dict] = None
) -> str:
    """Generate weekly report in HTML format."""

    # Calculate team percentages
    by_team = week_stats.get('by_team', {})
    total_team = sum(by_team.values()) or 1
    team_pcts = {t: round(c / total_team * 100) for t, c in by_team.items()}

    # Build accomplishments HTML - prefer AI summaries if available
    accomplishments_source = ai_summaries if ai_summaries else wins
    accomplishments_html = ""
    valid_items = []

    for item in accomplishments_source[:5]:
        summary = item.get('summary', item.get('description', ''))
        project = item.get('project', '')
        files = item.get('files_modified', item.get('files_edited', 0))
        category = item.get('category', '')

        # Skip items with poor summaries
        if not summary or summary == "Development work completed":
            continue
        # Skip generic project names in display
        if project in ('Unknown', '', 'tracker', 'task', 'pk', 'Project'):
            project = ''

        valid_items.append({
            'summary': summary,
            'project': project,
            'files': files,
            'category': category
        })

    if valid_items:
        items_html = ""
        for item in valid_items:
            project_badge = f'<span class="accomplishment-project">{item["project"]}</span>' if item["project"] else ''
            # Show category for AI summaries, files for regular wins
            if ai_summaries and item["category"]:
                meta_badge = f'<span class="accomplishment-category">{item["category"]}</span>'
            elif item["files"] > 5:
                meta_badge = f'<span class="accomplishment-files">{item["files"]} files</span>'
            else:
                meta_badge = ''
            items_html += f"""
            <div class="accomplishment-item">
                <div class="accomplishment-text">{item["summary"]}</div>
                <div class="accomplishment-meta">{project_badge} {meta_badge}</div>
            </div>
            """
        ai_badge = '<span class="ai-badge">AI Enhanced</span>' if ai_summaries else ''
        accomplishments_html = f"""
        <div class="section accomplishments-section">
            <h2>Key Accomplishments {ai_badge}</h2>
            <div class="accomplishments-list">{items_html}</div>
        </div>
        """

    # Build project table
    by_project = week_stats.get('by_project', {})
    project_rows = ""
    for proj, count in list(by_project.items())[:10]:
        project_rows += f"<tr><td>{proj}</td><td>{count}</td></tr>"

    # Build active themes
    themes_html = ""
    for project in roadmap.projects:
        active_themes = [t for t in project.themes if t.status.value == 'active']
        if active_themes:
            theme_items = "".join(f"<li>{t.name}</li>" for t in active_themes)
            themes_html += f"""
            <div class="theme-group">
                <h4>{project.name}</h4>
                <ul>{theme_items}</ul>
            </div>
            """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Weekly Report - {week_start.strftime('%b %d')} to {week_end.strftime('%b %d, %Y')}</title>
    <style>
        :root {{
            --bg: #ffffff;
            --card: #f8fafc;
            --border: #e2e8f0;
            --text: #1e293b;
            --text-muted: #64748b;
            --accent: #3b82f6;
            --success: #22c55e;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 40px 20px;
            line-height: 1.6;
        }}

        .container {{
            max-width: 800px;
            margin: 0 auto;
        }}

        .header {{
            text-align: center;
            margin-bottom: 40px;
            padding-bottom: 20px;
            border-bottom: 2px solid var(--border);
        }}

        .header h1 {{
            font-size: 1.75rem;
            margin-bottom: 8px;
        }}

        .header .date-range {{
            color: var(--text-muted);
            font-size: 1rem;
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 32px;
        }}

        .stat-card {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}

        .stat-value {{
            font-size: 2rem;
            font-weight: 700;
            color: var(--accent);
        }}

        .stat-label {{
            font-size: 0.75rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .section {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
        }}

        .section h2 {{
            font-size: 1rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border);
        }}

        .wins-list {{
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}

        .win-item {{
            padding: 12px;
            background: rgba(34, 197, 94, 0.05);
            border-left: 3px solid var(--success);
            border-radius: 0 8px 8px 0;
        }}

        .win-category {{
            display: inline-block;
            padding: 2px 8px;
            font-size: 0.65rem;
            font-weight: 600;
            text-transform: uppercase;
            background: var(--success);
            color: white;
            border-radius: 4px;
            margin-bottom: 4px;
        }}

        .win-summary {{
            font-weight: 500;
            margin-bottom: 4px;
        }}

        .win-project {{
            font-size: 0.8rem;
            color: var(--text-muted);
        }}

        .team-bar {{
            display: flex;
            height: 24px;
            border-radius: 12px;
            overflow: hidden;
            margin-bottom: 8px;
        }}

        .team-segment {{
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 0.75rem;
            font-weight: 600;
        }}

        .team-segment:first-child {{ background: #3b82f6; }}
        .team-segment:nth-child(2) {{ background: #8b5cf6; }}

        table {{
            width: 100%;
            border-collapse: collapse;
        }}

        th, td {{
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}

        th {{
            font-weight: 600;
            color: var(--text-muted);
            font-size: 0.8rem;
            text-transform: uppercase;
        }}

        .theme-group {{
            margin-bottom: 16px;
        }}

        .theme-group h4 {{
            font-size: 0.9rem;
            margin-bottom: 8px;
        }}

        .theme-group ul {{
            margin-left: 20px;
            color: var(--text-muted);
        }}

        .footer {{
            text-align: center;
            color: var(--text-muted);
            font-size: 0.75rem;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid var(--border);
        }}

        .accomplishments-list {{
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}

        .accomplishment-item {{
            padding: 12px 16px;
            background: linear-gradient(135deg, rgba(34, 197, 94, 0.08), rgba(34, 197, 94, 0.02));
            border-left: 3px solid var(--success);
            border-radius: 0 8px 8px 0;
        }}

        .accomplishment-text {{
            font-weight: 500;
            color: var(--text);
            margin-bottom: 6px;
        }}

        .accomplishment-meta {{
            display: flex;
            gap: 12px;
            font-size: 0.8rem;
        }}

        .accomplishment-project {{
            color: var(--accent);
            font-weight: 500;
        }}

        .accomplishment-files {{
            color: var(--text-muted);
        }}

        .accomplishment-category {{
            color: var(--text-muted);
            font-style: italic;
        }}

        .ai-badge {{
            display: inline-block;
            padding: 2px 8px;
            font-size: 0.65rem;
            font-weight: 600;
            text-transform: uppercase;
            background: linear-gradient(135deg, #8b5cf6, #6366f1);
            color: white;
            border-radius: 4px;
            margin-left: 8px;
            vertical-align: middle;
        }}

        @media print {{
            body {{ padding: 20px; }}
            .section {{ break-inside: avoid; }}
        }}

        @media (max-width: 600px) {{
            .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Weekly Activity Report</h1>
            <div class="date-range">{week_start.strftime('%B %d')} - {week_end.strftime('%B %d, %Y')}</div>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{week_stats.get('total_activities', 0)}</div>
                <div class="stat-label">Activities</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len(by_project)}</div>
                <div class="stat-label">Projects</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{week_stats.get('total_sessions', 0)}</div>
                <div class="stat-label">AI Sessions</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{week_stats.get('total_files_edited', 0)}</div>
                <div class="stat-label">Files Edited</div>
            </div>
        </div>

        <div class="section">
            <h2>Team Distribution</h2>
            <div class="team-bar">
                {"".join(f'<div class="team-segment" style="width: {pct}%">{team} {pct}%</div>' for team, pct in team_pcts.items())}
            </div>
        </div>

        <div class="section">
            <h2>Project Activity</h2>
            <table>
                <thead>
                    <tr><th>Project</th><th>Activities</th></tr>
                </thead>
                <tbody>
                    {project_rows}
                </tbody>
            </table>
        </div>

        <div class="section">
            <h2>Active Themes</h2>
            {themes_html or '<p style="color: var(--text-muted)">No active themes</p>'}
        </div>

        {accomplishments_html}

        <div class="footer">
            Generated by Task Tracker on {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </div>
</body>
</html>"""

    return html


def generate_weekly_report(
    output_dir: Path = None,
    open_browser: bool = False
) -> Dict[str, str]:
    """
    Generate weekly report in both HTML and Markdown formats.

    Returns:
        Dict with 'html' and 'markdown' file paths
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Calculate week range
    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())  # Monday
    week_end = today

    # Load data
    print("Loading weekly data...")
    snapshots = load_weekly_snapshots()
    week_stats = aggregate_week_stats(snapshots)

    print("Collecting activities for wins analysis...")
    activities = collect_all_activities(168, verbose=False)  # 7 days
    wins = analyze_activities_for_wins(activities)

    # Try to load AI-enhanced summaries
    ai_summaries = load_ai_summaries(week_start)
    if ai_summaries:
        print(f"Using {len(ai_summaries)} AI-enhanced summaries")
    else:
        print("No AI summaries found - using auto-generated wins")

    roadmap = load_roadmap()

    # Generate reports
    print("Generating reports...")
    markdown = generate_markdown_report(week_stats, wins, roadmap, week_start, week_end, ai_summaries)
    html = generate_html_report(week_stats, wins, roadmap, week_start, week_end, ai_summaries)

    # Save files
    week_str = week_start.strftime("%Y-W%W")
    md_file = output_dir / f"weekly_report_{week_str}.md"
    html_file = output_dir / f"weekly_report_{week_str}.html"

    with open(md_file, 'w') as f:
        f.write(markdown)

    with open(html_file, 'w') as f:
        f.write(html)

    print(f"Saved: {md_file}")
    print(f"Saved: {html_file}")

    if open_browser:
        import webbrowser
        webbrowser.open(f"file://{html_file}")
        print(f"Opened in browser")

    return {
        'markdown': str(md_file),
        'html': str(html_file),
        'stats': week_stats,
        'wins_count': len(wins),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate weekly report")
    parser.add_argument("--output", "-o", help="Output directory")
    parser.add_argument("--open", action="store_true", help="Open HTML in browser")

    args = parser.parse_args()

    output_dir = Path(args.output) if args.output else None

    result = generate_weekly_report(output_dir, args.open)

    print(f"\nWeekly Report Summary:")
    print(f"  Activities: {result['stats'].get('total_activities', 0)}")
    print(f"  Projects: {len(result['stats'].get('by_project', {}))}")
    print(f"  Wins: {result['wins_count']}")


if __name__ == "__main__":
    main()
