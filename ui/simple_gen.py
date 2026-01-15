#!/usr/bin/env python3
"""Generate simple dashboard. Embeds data for file:// compatibility."""

import json
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.simple_recap import generate_recap


def generate_standalone_html(data: dict) -> str:
    """Generate standalone HTML with embedded data."""

    # Build project rows
    project_rows = ""
    for p in data["projects"][:8]:
        project_rows += f'''
            <div class="project">
                <span class="project-name">{p["name"]}</span>
                <span class="project-stats">{p["activities"]} activities, {p["files"]} files</span>
            </div>'''

    # Build wins
    wins_html = ""
    if data["daily"].get("wins"):
        wins_items = "".join(f'<div class="win">{w}</div>' for w in data["daily"]["wins"])
        wins_html = f'''
        <div class="section">
            <div class="section-title">Wins</div>
            <div class="wins-list">{wins_items}</div>
        </div>'''

    # Build blockers
    blockers_html = ""
    if data["daily"].get("blockers"):
        blocker_items = "".join(f'<div class="blocker">{b}</div>' for b in data["daily"]["blockers"])
        blockers_html = f'''
        <div class="section">
            <div class="section-title">Blockers</div>
            <div class="blockers-list">{blocker_items}</div>
        </div>'''

    # Intent section
    intent_html = ""
    if data["daily"].get("intent"):
        intent_html = f'''
        <div class="section">
            <div class="section-title">Today's Intent</div>
            <div class="intent">{data["daily"]["intent"]}</div>
        </div>'''

    # Team distribution bar
    team_html = ""
    team = data.get("team", {})
    if team and len(team) > 1:
        team_items = list(team.items())
        colors = ["#3b82f6", "#8b5cf6", "#22c55e", "#f59e0b"]
        bars = "".join(f'<div style="width:{pct}%;background:{colors[i % len(colors)]}" class="team-bar-seg"></div>'
                       for i, (name, pct) in enumerate(team_items) if pct > 0)
        legend = " · ".join(f'{name} {pct}%' for name, pct in team_items if pct > 0)
        team_html = f'''
        <div class="section">
            <div class="section-title">Team Distribution</div>
            <div class="team-bar">{bars}</div>
            <div class="team-legend">{legend}</div>
        </div>'''

    # Claude stats
    claude = data.get("claude", {})
    claude_html = ""
    if claude.get("sessions", 0) > 0:
        claude_html = f'''
        <div class="section">
            <div class="section-title">Claude Code</div>
            <div class="claude-stats">
                <div class="claude-stat"><span class="claude-val">{claude.get("sessions", 0)}</span> sessions</div>
                <div class="claude-stat"><span class="claude-val">{claude.get("messages", 0)}</span> messages</div>
                <div class="claude-stat"><span class="claude-val">{claude.get("tools", 0)}</span> tool uses</div>
            </div>
        </div>'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Recap - {data["date"]}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            padding: 32px;
            min-height: 100vh;
        }}
        .container {{ max-width: 600px; margin: 0 auto; }}
        h1 {{ font-size: 1.25rem; font-weight: 500; color: #94a3b8; margin-bottom: 8px; }}
        .date {{ font-size: 2rem; font-weight: 700; margin-bottom: 32px; }}
        .section {{
            background: #1e293b;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
        }}
        .section-title {{
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: #64748b;
            margin-bottom: 12px;
        }}
        .intent {{ font-size: 1.1rem; color: #f8fafc; line-height: 1.5; }}
        .stats {{ display: flex; gap: 32px; }}
        .stat {{ text-align: center; }}
        .stat-value {{ font-size: 2.5rem; font-weight: 700; color: #3b82f6; }}
        .stat-label {{ font-size: 0.75rem; color: #64748b; text-transform: uppercase; }}
        .project-list {{ display: flex; flex-direction: column; gap: 8px; }}
        .project {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #334155;
        }}
        .project:last-child {{ border-bottom: none; }}
        .project-name {{ font-weight: 500; }}
        .project-stats {{ color: #64748b; font-size: 0.875rem; }}
        .wins-list, .blockers-list {{ display: flex; flex-direction: column; gap: 8px; }}
        .win {{
            padding: 8px 12px;
            background: rgba(34, 197, 94, 0.1);
            border-left: 3px solid #22c55e;
            border-radius: 0 6px 6px 0;
        }}
        .blocker {{
            padding: 8px 12px;
            background: rgba(239, 68, 68, 0.1);
            border-left: 3px solid #ef4444;
            border-radius: 0 6px 6px 0;
        }}
        .footer {{
            text-align: center;
            color: #475569;
            font-size: 0.75rem;
            margin-top: 32px;
        }}
        .explainer {{
            background: #1e293b;
            border-radius: 12px;
            padding: 16px 20px;
            margin-bottom: 16px;
            border: 1px solid #334155;
        }}
        .explainer-toggle {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            color: #94a3b8;
            font-size: 0.8rem;
        }}
        .explainer-toggle:hover {{ color: #e2e8f0; }}
        .explainer-content {{
            display: none;
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px solid #334155;
            font-size: 0.8rem;
            color: #94a3b8;
            line-height: 1.6;
        }}
        .explainer-content.open {{ display: block; }}
        .explainer-content dt {{
            color: #e2e8f0;
            font-weight: 500;
            margin-top: 8px;
        }}
        .explainer-content dt:first-child {{ margin-top: 0; }}
        .explainer-content dd {{ margin-left: 0; margin-top: 2px; }}
        .team-bar {{
            display: flex;
            height: 8px;
            border-radius: 4px;
            overflow: hidden;
            margin-bottom: 8px;
        }}
        .team-bar-seg {{ height: 100%; }}
        .team-legend {{
            font-size: 0.75rem;
            color: #94a3b8;
        }}
        .claude-stats {{
            display: flex;
            gap: 24px;
        }}
        .claude-stat {{
            font-size: 0.875rem;
            color: #94a3b8;
        }}
        .claude-val {{
            font-weight: 700;
            color: #a78bfa;
            margin-right: 4px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Daily Recap</h1>
        <div class="date">{data["date"]}</div>

        <div class="explainer">
            <div class="explainer-toggle" onclick="this.nextElementSibling.classList.toggle('open')">
                <span>How to read this dashboard</span>
                <span>+</span>
            </div>
            <div class="explainer-content">
                <dl>
                    <dt>Activities</dt>
                    <dd>Units of work: 1 git commit = 1 activity, 1 directory with edits = 1 activity, 1 Claude session = 1 activity</dd>
                    <dt>Files</dt>
                    <dd>Total unique files touched across all activity sources</dd>
                    <dt>Projects</dt>
                    <dd>Matched from folder paths in config. Shows where time was spent.</dd>
                    <dt>Team Distribution</dt>
                    <dd>% of activities by team, based on which team owns each project</dd>
                    <dt>Claude Code</dt>
                    <dd>Sessions = separate coding conversations. Messages = back-and-forth exchanges. Tool uses = file reads, edits, commands run.</dd>
                    <dt>Wins / Blockers</dt>
                    <dd>Manually logged via <code>daily.py win "..."</code> or <code>daily.py block "..."</code></dd>
                </dl>
            </div>
        </div>

        {intent_html}

        <div class="section">
            <div class="stats">
                <div class="stat">
                    <div class="stat-value">{data["total_activities"]}</div>
                    <div class="stat-label">Activities</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{data["total_files"]}</div>
                    <div class="stat-label">Files</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{len(data["projects"])}</div>
                    <div class="stat-label">Projects</div>
                </div>
            </div>
        </div>

        {team_html}

        {claude_html}

        <div class="section">
            <div class="section-title">By Project</div>
            <div class="project-list">{project_rows if project_rows else '<div style="color:#475569;font-style:italic">No activity</div>'}</div>
        </div>

        {wins_html}
        {blockers_html}

        <div class="footer">
            Generated {datetime.now().strftime("%H:%M")}
        </div>
    </div>
</body>
</html>'''


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate simple dashboard")
    parser.add_argument("--hours", type=int, default=24, help="Hours to look back")
    parser.add_argument("--open", action="store_true", help="Open in browser")

    args = parser.parse_args()

    print("Generating recap...")
    data = generate_recap(args.hours)

    # Save JSON (for reference)
    json_file = Path(__file__).parent / "simple-data.json"
    with open(json_file, 'w') as f:
        json.dump(data, f, indent=2)

    # Generate standalone HTML
    html = generate_standalone_html(data)
    html_file = Path(__file__).parent / "recap.html"
    with open(html_file, 'w') as f:
        f.write(html)

    print(f"  {data['total_activities']} activities across {len(data['projects'])} projects")

    if args.open:
        webbrowser.open(f"file://{html_file}")
        print("Opened in browser")


if __name__ == "__main__":
    main()
