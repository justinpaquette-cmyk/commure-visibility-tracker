#!/usr/bin/env python3
"""Weekly wins processor.

Runs every Friday at 9 AM to:
1. Collect all recap files from the past week
2. Analyze activities for potential wins
3. Generate a wins summary in the established format
4. Archive processed recaps

Also supports daily wins detection for UI integration.
"""

import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict, Counter

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Activity, ActivitySource


# Wins output directory (matches existing structure)
WINS_BASE = Path("/Users/justinpaquette/Documents/sales eng projects v2/Justin's_Wins/2026")


def load_wins_config() -> dict:
    """Load wins configuration from config file."""
    config_path = Path(__file__).parent.parent / "config" / "wins_config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    # Default config if file doesn't exist
    return {
        "thresholds": {
            "significant_session_files": 5,
            "sustained_effort_files": 10,
            "significant_tasks": 3,
        },
        "keyword_tiers": {
            "high_impact": ["ship", "launch", "deploy", "complete", "finish", "release"],
            "medium_impact": ["implement", "build", "create", "fix", "solve"],
            "low_impact": ["add", "update", "modify", "refactor"],
        },
        "categories": [],
        "min_confidence": 0.5,
    }


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


def count_keywords(text: str, keywords: List[str]) -> int:
    """Count how many keywords appear in text."""
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw in text_lower)


def score_specificity(text: str) -> float:
    """Score text by how specific/descriptive it is."""
    if not text:
        return 0.0
    # Longer descriptions with more unique words are more specific
    words = set(text.lower().split())
    # Penalize very short or very generic descriptions
    if len(words) < 3:
        return 0.1
    # Bonus for descriptive words
    descriptive = ['implement', 'create', 'build', 'fix', 'add', 'update', 'refactor']
    bonus = sum(0.1 for w in descriptive if w in words)
    return min(1.0, len(words) / 10 + bonus)


def is_prompt_text(text: str) -> bool:
    """Check if text looks like a raw prompt rather than an accomplishment."""
    if not text:
        return True

    text_lower = text.lower().strip()

    # Prompt starters - things users say to AI
    prompt_starters = [
        'please', 'can you', 'could you', 'help me', 'i want', 'i need',
        'lets', "let's", 'write', 'create', 'make', 'build', 'add',
        'implement', 'fix', 'update', 'modify', 'change', 'show me',
        'tell me', 'explain', 'walk me', 'orient yourself', 'review',
        'check', 'look at', 'analyze', 'give me', 'generate', 'do ',
    ]

    for starter in prompt_starters:
        if text_lower.startswith(starter):
            return True

    # Questions are prompts
    if text.strip().endswith('?'):
        return True

    # Very short text is usually a prompt
    if len(text.split()) < 5:
        return True

    # Contains "I " suggesting user is speaking
    if ' i ' in text_lower or text_lower.startswith('i '):
        return True

    return False


def clean_prompt_text(text: str) -> str:
    """Clean up raw prompt text to make it presentable."""
    if not text:
        return ""

    # Check if this is clearly a prompt - return empty to skip it
    if is_prompt_text(text):
        return ""

    # Remove [Project] prefixes
    text = re.sub(r'^\[.*?\]\s*', '', text)

    # Remove "Modified/Edited X files" prefixes
    text = re.sub(r'^(Modified|Edited)\s+\d+\s+files?\s+(in|at)\s+', '', text)

    # Capitalize first letter
    text = text.strip()
    if text:
        text = text[0].upper() + text[1:]

    return text


def generate_smart_summary(activities: List[Activity], max_length: int = 100) -> str:
    """Generate intelligent, polished summary from activities."""

    # Collect potential summaries with quality scores
    candidates = []

    for a in activities:
        # Prefer git commit messages - they're usually well-written
        if a.source == ActivitySource.GIT:
            subject = a.raw_data.get('subject', '')
            if subject and len(subject) > 10:
                # Git commits are usually good quality
                cleaned = clean_prompt_text(subject)
                if cleaned and len(cleaned) > 10:
                    candidates.append((cleaned, 0.9))

    # Sort by quality score, then by length (prefer concise)
    candidates.sort(key=lambda x: (-x[1], len(x[0])))

    # Use git commit if available
    for text, score in candidates:
        if len(text) > max_length:
            text = text[:max_length].rsplit(' ', 1)[0] + "..."
        return text

    # Collect all files for pattern detection
    files_edited = set()
    file_details = []
    project_name = None

    for a in activities:
        files = a.raw_data.get('files_edited', []) + a.raw_data.get('files_changed', [])
        files_edited.update(files)
        for f in files:
            if f:
                file_details.append(f)
        if not project_name:
            project_name = a.raw_data.get('project', '')

    if files_edited:
        extensions = [os.path.splitext(f)[1] for f in files_edited if f]
        ext_counts = Counter(ext for ext in extensions if ext)

        # Try to infer work type from file patterns
        file_str = ' '.join(file_details).lower()
        file_count = len(files_edited)

        # Build more descriptive summaries based on file patterns
        contexts = []

        # Agent/automation work
        if 'agent' in file_str or 'nightly' in file_str:
            contexts.append('automation')
        # Testing
        if 'test' in file_str or 'spec' in file_str:
            contexts.append('testing')
        # UI/Components
        if 'component' in file_str or '.tsx' in file_str or 'ui/' in file_str:
            contexts.append('UI')
        # API/Backend
        if 'api' in file_str or 'endpoint' in file_str or 'route' in file_str:
            contexts.append('API')
        # Config
        if 'config' in file_str or 'settings' in file_str:
            contexts.append('configuration')
        # Collectors/Integration
        if 'collector' in file_str or 'integration' in file_str:
            contexts.append('integration')
        # Reports
        if 'report' in file_str:
            contexts.append('reporting')

        if contexts:
            context_str = ' and '.join(contexts[:2])
            return f"Enhanced {context_str} ({file_count} files)"

        # Generate based on file types
        if ext_counts:
            top_ext = ext_counts.most_common(1)[0][0]
            ext_map = {
                '.py': 'Python backend development',
                '.ts': 'TypeScript development',
                '.tsx': 'React component development',
                '.js': 'JavaScript development',
                '.jsx': 'React development',
                '.css': 'Styling and UI polish',
                '.html': 'UI/template development',
                '.json': 'Configuration and data work',
                '.md': 'Documentation updates',
                '.sql': 'Database development',
            }
            work_type = ext_map.get(top_ext, 'Development')
            return f"{work_type} ({file_count} files)"

        return f"Development work ({file_count} files)"

    return ""  # Return empty if we can't generate a good summary


def categorize_win(text: str, categories: List[dict]) -> str:
    """Categorize a win based on keywords."""
    text_lower = text.lower()

    for category in sorted(categories, key=lambda c: c.get('priority', 99)):
        keywords = category.get('keywords', [])
        if any(kw in text_lower for kw in keywords):
            return category['name']

    return "Development"


def analyze_activities_for_wins(
    activities: List[Activity],
    config: dict = None
) -> List[Dict[str, Any]]:
    """
    Analyze activities and identify potential wins using tiered scoring.

    Uses configurable keyword tiers and thresholds for more accurate detection.
    """
    if config is None:
        config = load_wins_config()

    thresholds = config.get("thresholds", {})
    keyword_tiers = config.get("keyword_tiers", {})
    categories = config.get("categories", [])
    min_confidence = config.get("min_confidence", 0.5)

    potential_wins = []

    # Group by project
    by_project = defaultdict(list)
    for activity in activities:
        project = activity.raw_data.get('project', 'Unknown')
        by_project[project].append(activity)

    # Analyze each project's activities
    for project, project_activities in by_project.items():
        if len(project_activities) < 1:
            continue

        # Collect all descriptions for this project
        all_descriptions = []
        for a in project_activities:
            all_descriptions.append(a.description)
            all_descriptions.extend(a.raw_data.get('task_descriptions', []))

        combined_text = ' '.join(all_descriptions)

        # Calculate win score using multiple signals
        win_score = 0.0
        win_signals = []

        # Signal 1: High-impact keywords (weight: 0.4)
        high_impact = keyword_tiers.get("high_impact", [])
        high_count = count_keywords(combined_text, high_impact)
        if high_count > 0:
            signal_score = 0.4 * min(high_count / 2, 1.0)
            win_score += signal_score
            win_signals.append(f"{high_count} high-impact keywords")

        # Signal 2: Medium-impact keywords (weight: 0.2)
        medium_impact = keyword_tiers.get("medium_impact", [])
        medium_count = count_keywords(combined_text, medium_impact)
        if medium_count > 0:
            signal_score = 0.2 * min(medium_count / 3, 1.0)
            win_score += signal_score
            win_signals.append(f"{medium_count} medium-impact keywords")

        # Signal 3: File volume (weight: 0.25)
        total_files = sum(
            len(a.raw_data.get('files_edited', [])) + len(a.raw_data.get('files_changed', []))
            for a in project_activities
        )
        sustained_threshold = thresholds.get("sustained_effort_files", 10)
        if total_files >= sustained_threshold:
            win_score += 0.25
            win_signals.append(f"{total_files} files modified")
        elif total_files >= sustained_threshold / 2:
            win_score += 0.15
            win_signals.append(f"{total_files} files modified")

        # Signal 4: Multiple sessions/activities (weight: 0.15)
        if len(project_activities) >= 3:
            win_score += 0.15
            win_signals.append(f"{len(project_activities)} activities")

        # Only include wins above confidence threshold
        if win_score >= min_confidence:
            summary = generate_smart_summary(project_activities)
            category = categorize_win(summary + ' ' + combined_text, categories)

            potential_wins.append({
                'project': project,
                'type': 'tiered_analysis',
                'description': summary,
                'summary': summary,
                'category': category,
                'files_modified': total_files,
                'activity_count': len(project_activities),
                'timestamp': max(a.timestamp for a in project_activities),
                'confidence': round(win_score, 2),
                'signals': win_signals,
            })

        # Also check individual high-value activities
        for activity in project_activities:
            if activity.source == ActivitySource.CLAUDE:
                files_edited = len(activity.raw_data.get('files_edited', []))
                task_descriptions = activity.raw_data.get('task_descriptions', [])
                session_threshold = thresholds.get("significant_session_files", 5)

                if files_edited >= session_threshold or len(task_descriptions) >= 3:
                    # Check if this would be a duplicate
                    existing = [w for w in potential_wins if w['project'] == project]
                    if not existing or files_edited > existing[0].get('files_modified', 0):
                        # Don't use raw prompts - try to find a good summary
                        summary = ""

                        # Look for non-prompt descriptions
                        for desc in task_descriptions:
                            cleaned = clean_prompt_text(desc)
                            if cleaned and not is_prompt_text(cleaned):
                                summary = cleaned
                                break

                        # Fallback to file-based summary
                        if not summary:
                            summary = generate_smart_summary([activity])

                        # Skip if we still don't have a good summary
                        if not summary or summary == "Development work completed":
                            continue

                        potential_wins.append({
                            'project': project,
                            'type': 'significant_session',
                            'description': summary,
                            'summary': summary,
                            'category': categorize_win(summary, categories),
                            'files_edited': files_edited,
                            'tasks': task_descriptions[:3],
                            'timestamp': activity.timestamp,
                            'confidence': 0.7,
                            'signals': [f"{files_edited} files edited in session"],
                        })

    # Deduplicate by project, keeping highest confidence
    seen_projects = {}
    for win in potential_wins:
        proj = win['project']
        if proj not in seen_projects or win['confidence'] > seen_projects[proj]['confidence']:
            seen_projects[proj] = win

    final_wins = list(seen_projects.values())

    # Sort by confidence
    final_wins.sort(key=lambda x: -x['confidence'])

    return final_wins


def format_win_entry(win: Dict[str, Any], index: int) -> str:
    """Format a single win entry in the established markdown format."""
    date = win['timestamp'].strftime('%B %Y')
    project = win['project']

    # Use smart summary if available, otherwise generate
    summary = win.get('summary', win.get('description', 'Development work'))

    # Use pre-computed category or determine from summary
    category = win.get('category', 'Development')

    # Build evidence section
    evidence_lines = []
    files_count = win.get('files_edited', win.get('files_modified', win.get('total_files', 0)))
    if files_count:
        evidence_lines.append(f"- {files_count} files modified")

    if win.get('signals'):
        for signal in win['signals'][:2]:
            evidence_lines.append(f"- {signal}")

    confidence = win.get('confidence', 0)
    evidence_lines.append(f"- Confidence: {int(confidence * 100)}%")

    evidence = '\n'.join(evidence_lines)

    # Smart truncation for title
    title = summary[:80]
    if len(summary) > 80:
        title = summary[:80].rsplit(' ', 1)[0] + "..."

    return f"""
### {index}. {title}
**Date:** {date}
**Category:** {category}
**Project:** {project}

**Summary:**
{summary}

**Evidence:**
{evidence}

---
"""


def run_daily_wins(date: datetime = None, activities: List[Activity] = None) -> List[Dict[str, Any]]:
    """
    Extract wins from a single day's activities.

    Used for UI integration to show daily highlights.

    Args:
        date: Date to extract wins for (defaults to today)
        activities: Pre-collected activities (uses collect_all_activities if not provided)
    """
    if date is None:
        date = datetime.now()

    config = load_wins_config()

    # Adjust thresholds for daily (lower than weekly)
    daily_config = config.copy()
    daily_config["thresholds"] = {
        "significant_session_files": config["thresholds"].get("daily_session_files", 3),
        "sustained_effort_files": config["thresholds"].get("daily_effort_files", 5),
        "significant_tasks": 2,
    }
    daily_config["min_confidence"] = 0.4  # Lower threshold for daily

    # Use provided activities or collect fresh
    if activities is None:
        # Try to import and collect
        try:
            from agent.nightly import collect_all_activities
            activities = collect_all_activities(24, verbose=False)
        except ImportError:
            # Fall back to JSON file
            activities_dir = Path(__file__).parent.parent / "data" / "activities"
            activities_file = activities_dir / f"{date.strftime('%Y-%m-%d')}.json"

            if not activities_file.exists():
                return []

            try:
                with open(activities_file) as f:
                    data = json.load(f)
                    activities = [Activity.from_dict(a) for a in data.get('activities', [])]
            except (json.JSONDecodeError, IOError):
                return []

    if not activities:
        return []

    # Analyze with daily config
    wins = analyze_activities_for_wins(activities, daily_config)

    # Limit to max wins per day
    max_wins = config.get("max_wins_per_day", 5)
    return wins[:max_wins]


def format_win_for_ui(win: Dict[str, Any]) -> Dict[str, Any]:
    """Format a win for UI display."""
    return {
        'project': win.get('project', 'Unknown'),
        'summary': win.get('summary', win.get('description', '')),
        'category': win.get('category', 'Development'),
        'confidence': int(win.get('confidence', 0) * 100),
        'signals': win.get('signals', [])[:2],
        'files_modified': win.get('files_modified', win.get('files_edited', 0)),
    }


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
