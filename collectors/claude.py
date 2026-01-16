"""Claude Code session activity collector.

Parses Claude Code conversation logs to extract:
- Task descriptions from user messages
- Files edited via tool use
- Session duration and activity metrics
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
from collections import defaultdict
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Activity, ActivitySource


def load_config() -> tuple:
    """Load project and settings configuration."""
    config_dir = Path(__file__).parent.parent / "config"

    with open(config_dir / "settings.json") as f:
        settings = json.load(f)

    with open(config_dir / "projects.json") as f:
        projects = json.load(f)

    return settings, projects


def get_claude_projects_dir() -> Path:
    """Get the Claude Code projects directory."""
    return Path.home() / ".claude" / "projects"


def decode_project_path(encoded_name: str) -> str:
    """Convert Claude's encoded project folder name back to a path."""
    # Remove leading dash and convert dashes to slashes
    if encoded_name.startswith('-'):
        encoded_name = encoded_name[1:]
    return '/' + encoded_name.replace('-', '/')


def find_session_files(since: datetime) -> List[Dict[str, Any]]:
    """Find all session files modified since the given time."""
    projects_dir = get_claude_projects_dir()
    sessions = []

    if not projects_dir.exists():
        return sessions

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        for f in project_dir.iterdir():
            if f.suffix == '.jsonl' and f.is_file():
                stat = f.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime)

                if mtime >= since:
                    sessions.append({
                        'path': f,
                        'project_encoded': project_dir.name,
                        'project_path': decode_project_path(project_dir.name),
                        'mtime': mtime,
                        'size': stat.st_size,
                    })

    return sessions


def parse_session_file(
    session_path: Path,
    since: datetime
) -> Dict[str, Any]:
    """
    Parse a Claude Code session file and extract activity data.

    Returns:
        {
            'user_messages': [...],
            'files_edited': [...],
            'tools_used': {...},
            'first_timestamp': datetime,
            'last_timestamp': datetime,
            'message_count': int,
        }
    """
    result = {
        'user_messages': [],
        'files_edited': set(),
        'files_read': set(),
        'tools_used': defaultdict(int),
        'first_timestamp': None,
        'last_timestamp': None,
        'message_count': 0,
        'task_descriptions': [],
    }

    try:
        with open(session_path, 'r') as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = data.get('type')
                timestamp_str = data.get('timestamp')

                if timestamp_str:
                    try:
                        # Parse ISO format timestamp
                        ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        ts = ts.replace(tzinfo=None)  # Make naive for comparison

                        if ts < since:
                            continue

                        if result['first_timestamp'] is None or ts < result['first_timestamp']:
                            result['first_timestamp'] = ts
                        if result['last_timestamp'] is None or ts > result['last_timestamp']:
                            result['last_timestamp'] = ts
                    except:
                        pass

                if entry_type == 'user':
                    result['message_count'] += 1
                    msg = data.get('message', {})
                    content = msg.get('content', '')

                    if isinstance(content, str) and content.strip():
                        # Extract first line as potential task description
                        first_line = content.strip().split('\n')[0][:200]
                        if len(first_line) > 10:  # Skip very short messages
                            result['user_messages'].append({
                                'content': first_line,
                                'timestamp': timestamp_str,
                            })

                            # Look for task-like messages (imperatives, questions)
                            task_patterns = [
                                r'^(create|build|add|fix|update|implement|write|make|help|can you|please)',
                                r'^(I need|I want|let\'s|we need)',
                            ]
                            for pattern in task_patterns:
                                if re.match(pattern, first_line.lower()):
                                    result['task_descriptions'].append(first_line)
                                    break

                elif entry_type == 'assistant':
                    msg = data.get('message', {})
                    content = msg.get('content', [])

                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get('type') == 'tool_use':
                                tool_name = block.get('name', 'unknown')
                                result['tools_used'][tool_name] += 1

                                # Extract file paths from tool inputs
                                tool_input = block.get('input', {})

                                if tool_name in ['Edit', 'Write']:
                                    file_path = tool_input.get('file_path')
                                    if file_path:
                                        result['files_edited'].add(file_path)

                                elif tool_name == 'Read':
                                    file_path = tool_input.get('file_path')
                                    if file_path:
                                        result['files_read'].add(file_path)

    except Exception as e:
        pass

    # Convert sets to lists for JSON serialization
    result['files_edited'] = list(result['files_edited'])
    result['files_read'] = list(result['files_read'])
    result['tools_used'] = dict(result['tools_used'])

    return result


def find_project_for_path(path: str, projects: List[dict]) -> Optional[dict]:
    """Find which configured project a path belongs to."""
    path = os.path.abspath(path) if path else ''
    for project in projects:
        project_path = os.path.abspath(project.get('folder_path', ''))
        if path.startswith(project_path):
            return project
    return None


def collect_activities(
    lookback_hours: Optional[int] = None,
    verbose: bool = False
) -> List[Activity]:
    """
    Collect activities from Claude Code session logs.

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
    projects = projects_config.get("projects", [])
    excluded_folders = projects_config.get("excluded_folders", [])

    if verbose:
        print(f"Scanning Claude Code sessions since {since}")

    activities = []
    sessions = find_session_files(since)

    if verbose:
        print(f"Found {len(sessions)} active session files")

    for session in sessions:
        # Check if session is in excluded folder
        session_project_path = session['project_path']
        is_excluded = any(
            session_project_path.startswith(ex)
            for ex in excluded_folders
        )
        if is_excluded:
            if verbose:
                print(f"  Skipping excluded: {session_project_path}")
            continue

        # Parse session
        session_data = parse_session_file(session['path'], since)

        if session_data['message_count'] == 0:
            continue

        # Find matching project
        project = find_project_for_path(session_project_path, projects)
        project_name = project['name'] if project else os.path.basename(session_project_path)

        if verbose:
            print(f"  {project_name}: {session_data['message_count']} messages, {len(session_data['files_edited'])} files edited")

        # Create activity for the session
        if session_data['task_descriptions']:
            # Use the most recent task description
            description = session_data['task_descriptions'][-1]
        elif session_data['files_edited']:
            # Summarize files edited
            file_count = len(session_data['files_edited'])
            description = f"Edited {file_count} file(s) in {project_name}"
        else:
            description = f"Claude Code session in {project_name}"

        # Determine timestamp
        timestamp = session_data['last_timestamp'] or session['mtime']

        activity = Activity(
            source=ActivitySource.CLAUDE,
            timestamp=timestamp,
            description=f"[Claude] {description}",
            confidence=0.9,  # High confidence - direct from Claude logs
            raw_data={
                'project': project_name,
                'project_path': session_project_path,
                'session_file': str(session['path']),
                'message_count': session_data['message_count'],
                'files_edited': session_data['files_edited'][:10],  # Limit
                'files_read': session_data['files_read'][:10],
                'tools_used': session_data['tools_used'],
                'task_descriptions': session_data['task_descriptions'][:5],
                'duration_minutes': (
                    (session_data['last_timestamp'] - session_data['first_timestamp']).total_seconds() / 60
                    if session_data['first_timestamp'] and session_data['last_timestamp']
                    else None
                ),
            },
            project_path=session_project_path,
        )
        activities.append(activity)

        # Also create activities for significant task descriptions
        for i, task_desc in enumerate(session_data['task_descriptions'][:-1]):  # Skip last (already used)
            if len(task_desc) > 20:  # Skip very short ones
                task_activity = Activity(
                    source=ActivitySource.CLAUDE,
                    timestamp=timestamp - timedelta(minutes=i+1),  # Approximate ordering
                    description=f"[Claude] {task_desc}",
                    confidence=0.85,
                    raw_data={
                        'project': project_name,
                        'type': 'task_request',
                    },
                    project_path=session_project_path,
                )
                activities.append(task_activity)

    # Sort by timestamp
    activities.sort(key=lambda a: a.timestamp, reverse=True)

    if verbose:
        print(f"\nCollected {len(activities)} Claude Code activities")

    return activities


def save_activities(activities: List[Activity], date: Optional[datetime] = None) -> str:
    """Save activities to the daily log file."""
    if date is None:
        date = datetime.now()

    data_dir = Path(__file__).parent.parent / "data" / "activities"
    data_dir.mkdir(parents=True, exist_ok=True)

    filename = date.strftime("%Y-%m-%d") + ".json"
    filepath = data_dir / filename

    # Load existing
    existing = []
    if filepath.exists():
        with open(filepath) as f:
            data = json.load(f)
            existing = [Activity.from_dict(a) for a in data.get("activities", [])]

    # Merge (avoid duplicates based on description + source)
    existing_keys = {
        (a.description, a.source.value, a.timestamp.isoformat()[:16])
        for a in existing
    }

    for activity in activities:
        key = (activity.description, activity.source.value, activity.timestamp.isoformat()[:16])
        if key not in existing_keys:
            existing.append(activity)

    # Save
    with open(filepath, "w") as f:
        json.dump({
            "date": date.strftime("%Y-%m-%d"),
            "collected_at": datetime.now().isoformat(),
            "activities": [a.to_dict() for a in existing],
        }, f, indent=2)

    return str(filepath)


def get_session_summary(lookback_hours: int = 24) -> Dict[str, Any]:
    """
    Get a high-level summary of Claude Code sessions.

    Returns summary statistics useful for the recap.
    """
    since = datetime.now() - timedelta(hours=lookback_hours)
    sessions = find_session_files(since)

    # Load projects config for consistent naming
    _, projects_config = load_config()
    projects = projects_config.get("projects", [])

    summary = {
        'total_sessions': len(sessions),
        'total_messages': 0,
        'total_files_edited': 0,
        'projects_active': set(),
        'tools_breakdown': defaultdict(int),
        'sessions_by_project': {},
    }

    # Import map_claude_project_name for consistent naming
    from agent.simple_recap import map_claude_project_name

    for session in sessions:
        session_data = parse_session_file(session['path'], since)

        if session_data['message_count'] == 0:
            continue

        # Use raw encoded folder name for project matching (more reliable)
        project_name = map_claude_project_name(session['project_encoded'], projects)
        if project_name is None:  # Excluded project
            continue
        summary['total_messages'] += session_data['message_count']
        summary['total_files_edited'] += len(session_data['files_edited'])
        summary['projects_active'].add(project_name)

        for tool, count in session_data['tools_used'].items():
            summary['tools_breakdown'][tool] += count

        # Aggregate into existing entry or create new one
        if project_name not in summary['sessions_by_project']:
            summary['sessions_by_project'][project_name] = {
                'messages': 0,
                'files_edited': [],
                'duration_minutes': None,
                'session_count': 0,
            }

        proj_data = summary['sessions_by_project'][project_name]
        proj_data['messages'] += session_data['message_count']
        proj_data['files_edited'].extend(session_data['files_edited'])  # Store actual files, not count
        proj_data['session_count'] += 1
        if session_data.get('duration_minutes'):
            if proj_data['duration_minutes'] is None:
                proj_data['duration_minutes'] = 0
            proj_data['duration_minutes'] += session_data['duration_minutes']

    summary['projects_active'] = list(summary['projects_active'])
    summary['tools_breakdown'] = dict(summary['tools_breakdown'])

    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Collect Claude Code session activity")
    parser.add_argument("--hours", type=int, default=24, help="Hours to look back")
    parser.add_argument("--save", action="store_true", help="Save to daily log")
    parser.add_argument("--summary", action="store_true", help="Show summary only")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.summary:
        summary = get_session_summary(args.hours)
        print(f"\n=== CLAUDE CODE SUMMARY (last {args.hours}h) ===\n")
        print(f"Active sessions: {summary['total_sessions']}")
        print(f"Total messages: {summary['total_messages']}")
        print(f"Files edited: {summary['total_files_edited']}")
        print(f"Projects: {', '.join(summary['projects_active'])}")
        print(f"\nTools used:")
        for tool, count in sorted(summary['tools_breakdown'].items(), key=lambda x: -x[1])[:10]:
            print(f"  {tool}: {count}")
    else:
        activities = collect_activities(
            lookback_hours=args.hours,
            verbose=args.verbose
        )

        print(f"\n--- Claude Code Activities ---")
        for a in activities[:15]:
            print(f"[{a.timestamp.strftime('%Y-%m-%d %H:%M')}] {a.description}")
            if a.raw_data.get('files_edited'):
                print(f"    Files: {', '.join(os.path.basename(f) for f in a.raw_data['files_edited'][:3])}")
        if len(activities) > 15:
            print(f"... and {len(activities) - 15} more")

        if args.save:
            path = save_activities(activities)
            print(f"\nSaved to {path}")
