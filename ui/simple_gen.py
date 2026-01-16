#!/usr/bin/env python3
"""Generate simple dashboard. Embeds data for file:// compatibility."""

import json
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.simple_recap import generate_recap


def generate_standalone_html(data: dict, view_name: str = "day", view_label: str = "Today", ranges: list = None) -> str:
    """Generate standalone HTML with embedded data and navigation."""

    # Build navigation tabs
    if ranges:
        nav_items = []
        for r in ranges:
            active = "active" if r["name"] == view_name else ""
            nav_items.append(f'<a href="recap-{r["name"]}.html" class="nav-tab {active}">{r["label"]}</a>')
        nav_html = f'<div class="nav-tabs">{"".join(nav_items)}</div>'
    else:
        nav_html = ""

    # Build project rows with expandable details
    project_details = data.get("project_details", {})
    project_rows = ""
    for p in data["projects"]:
        proj_name = p["name"]
        details = project_details.get(proj_name, {})
        sessions = details.get("sessions", [])
        last_active = p.get("last_active", "")
        last_active_html = f'<span class="last-active">Last: {last_active}</span>' if last_active else ""

        # Build session details HTML
        sessions_html = ""
        if sessions:
            for s in sessions:
                task = s.get("task", "")[:200]
                if len(s.get("task", "")) > 200:
                    task += "..."
                files = s.get("files", [])
                time_str = s.get("time", "")
                time_html = f'<span class="session-time">{time_str}</span>' if time_str else ""
                files_str = f'<div class="session-files">{", ".join(files)}</div>' if files else ""
                sessions_html += f'''
                    <div class="session-item">
                        <div class="session-task">{time_html}{task}</div>
                        {files_str}
                    </div>'''

        # Wrap in expandable container if there are details
        if sessions_html:
            project_rows += f'''
            <details class="project-wrapper">
                <summary class="project">
                    <span class="project-name">{proj_name}<span class="expand-hint">(click to expand)</span></span>
                    <span class="project-stats">{p["activities"]} activities, {p["files"]} files {last_active_html}</span>
                </summary>
                <div class="project-details">
                    {sessions_html}
                </div>
            </details>'''
        else:
            project_rows += f'''
            <div class="project-wrapper">
                <div class="project">
                    <span class="project-name">{proj_name}</span>
                    <span class="project-stats">{p["activities"]} activities, {p["files"]} files {last_active_html}</span>
                </div>
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

    # Auto-generated summary
    summary_html = ""
    if data.get("summary"):
        summary_html = f'''
        <div class="section">
            <div class="section-title">What I Did</div>
            <div class="summary">{data["summary"]}</div>
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
    <title>{view_label} Recap - {data["date"]}</title>
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
        .nav-tabs {{
            display: flex;
            gap: 8px;
            margin-bottom: 24px;
        }}
        .nav-tab {{
            padding: 8px 16px;
            background: #1e293b;
            border-radius: 8px;
            color: #94a3b8;
            text-decoration: none;
            font-size: 0.875rem;
            transition: all 0.2s;
        }}
        .nav-tab:hover {{
            background: #334155;
            color: #e2e8f0;
        }}
        .nav-tab.active {{
            background: #3b82f6;
            color: #fff;
        }}
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
        .summary {{ font-size: 1rem; color: #cbd5e1; line-height: 1.6; }}
        .stats {{ display: flex; gap: 32px; }}
        .stat {{ text-align: center; }}
        .stat-value {{ font-size: 2.5rem; font-weight: 700; color: #3b82f6; }}
        .stat-label {{ font-size: 0.75rem; color: #64748b; text-transform: uppercase; }}
        .project-list {{ }}
        .project-wrapper {{
            border-bottom: 1px solid #334155;
            padding: 10px 0;
        }}
        .project-wrapper:last-child {{ border-bottom: none; }}
        details.project-wrapper {{ cursor: pointer; }}
        details.project-wrapper > summary {{ list-style: none; }}
        details.project-wrapper > summary::-webkit-details-marker {{ display: none; }}
        .project {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .project-name {{ font-weight: 500; }}
        .project-stats {{ color: #64748b; font-size: 0.875rem; }}
        .last-active {{ color: #94a3b8; font-size: 0.75rem; margin-left: 12px; font-style: italic; }}
        .expand-hint {{ color: #64748b; font-size: 0.7rem; margin-left: 8px; }}
        details.project-wrapper[open] .expand-hint {{ display: none; }}
        .project-details {{
            padding: 12px 0 4px 12px;
            margin-top: 8px;
            border-left: 2px solid #334155;
        }}
        .session-item {{
            padding: 8px 0;
            border-bottom: 1px solid #1e293b;
        }}
        .session-item:last-child {{ border-bottom: none; }}
        .session-task {{
            font-size: 0.85rem;
            color: #e2e8f0;
            line-height: 1.4;
        }}
        .session-time {{
            color: #64748b;
            font-size: 0.75rem;
            margin-right: 8px;
        }}
        .session-files {{
            font-size: 0.75rem;
            color: #64748b;
            margin-top: 4px;
        }}
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
        {nav_html}
        <h1>{view_label} Recap</h1>
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

        {summary_html}

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
    parser.add_argument("--all", action="store_true", help="Generate all views (day/week/month)")

    args = parser.parse_args()

    # Define time ranges
    ranges = [
        {"name": "day", "hours": 24, "label": "Today"},
        {"name": "week", "hours": 168, "label": "This Week"},
        {"name": "month", "hours": 720, "label": "This Month"},
        {"name": "6month", "hours": 4320, "label": "6 Months"},
    ]

    if args.all:
        print("Generating all recap views...")
        for r in ranges:
            data = generate_recap(r["hours"])
            html = generate_standalone_html(data, r["name"], r["label"], ranges)
            html_file = Path(__file__).parent / f"recap-{r['name']}.html"
            with open(html_file, 'w') as f:
                f.write(html)
            print(f"  {r['label']}: {data['total_activities']} activities")

        # Also create recap.html as alias to day view
        day_data = generate_recap(24)
        html = generate_standalone_html(day_data, "day", "Today", ranges)
        html_file = Path(__file__).parent / "recap.html"
        with open(html_file, 'w') as f:
            f.write(html)

        if args.open:
            webbrowser.open(f"file://{Path(__file__).parent / 'recap-day.html'}")
            print("Opened in browser")
    else:
        print("Generating recap...")
        data = generate_recap(args.hours)

        # Save JSON (for reference)
        json_file = Path(__file__).parent / "simple-data.json"
        with open(json_file, 'w') as f:
            json.dump(data, f, indent=2)

        # Determine which view based on hours
        view_name = "day"
        view_label = "Today"
        if args.hours >= 168:
            view_name = "week" if args.hours < 720 else "month"
            view_label = "This Week" if args.hours < 720 else "This Month"

        # Generate standalone HTML
        html = generate_standalone_html(data, view_name, view_label, ranges)
        html_file = Path(__file__).parent / "recap.html"
        with open(html_file, 'w') as f:
            f.write(html)

        print(f"  {data['total_activities']} activities across {len(data['projects'])} projects")

        if args.open:
            webbrowser.open(f"file://{html_file}")
            print("Opened in browser")


if __name__ == "__main__":
    main()
