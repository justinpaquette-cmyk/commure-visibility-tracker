#!/usr/bin/env python3
"""AI-enhanced accomplishment summarization.

Runs weekly to generate polished, contextual summaries of wins
using AI analysis of the raw activity data.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Activity


def load_weekly_activities(days: int = 7) -> List[Activity]:
    """Load activities from the past N days."""
    from agent.nightly import collect_all_activities
    return collect_all_activities(days * 24, verbose=False)


def prepare_context_for_ai(activities: List[Activity]) -> str:
    """Prepare activity context for AI analysis."""
    from collections import defaultdict

    # Group by project
    by_project = defaultdict(list)
    for a in activities:
        project = a.raw_data.get('project', 'Unknown')
        by_project[project].append(a)

    # Build context string
    lines = []
    lines.append("# Weekly Activity Summary for AI Analysis")
    lines.append(f"Period: {(datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("")

    for project, acts in by_project.items():
        if len(acts) < 2:
            continue

        lines.append(f"## Project: {project}")
        lines.append(f"Activities: {len(acts)}")

        # Collect file information
        all_files = set()
        for a in acts:
            files = a.raw_data.get('files_edited', []) + a.raw_data.get('files_changed', [])
            all_files.update(files)

        if all_files:
            lines.append(f"Files touched: {len(all_files)}")
            # Sample some files
            sample_files = list(all_files)[:10]
            lines.append(f"Sample files: {', '.join(sample_files)}")

        # Get git commits if any
        git_commits = [a for a in acts if a.source.value == 'git']
        if git_commits:
            lines.append("Git commits:")
            for gc in git_commits[:5]:
                subject = gc.raw_data.get('subject', gc.description)
                lines.append(f"  - {subject}")

        # Get task descriptions (but filter out obvious prompts)
        for a in acts:
            task_descs = a.raw_data.get('task_descriptions', [])
            for desc in task_descs[:3]:
                # Skip if looks like a prompt
                desc_lower = desc.lower()
                if any(desc_lower.startswith(p) for p in ['please', 'can you', 'help me', 'create', 'write']):
                    continue
                if len(desc) > 20:
                    lines.append(f"  Task: {desc[:100]}")
                    break

        lines.append("")

    return "\n".join(lines)


def generate_ai_summaries_prompt(context: str) -> str:
    """Generate the prompt for AI to create summaries."""
    return f"""You are analyzing a week of software engineering activities to identify key accomplishments.

Based on the following activity data, generate 3-5 polished accomplishment summaries. Each summary should:
1. Be a single sentence that describes what was achieved (not what was done)
2. Use active, professional language (e.g., "Built X to enable Y" not "Worked on X")
3. Focus on value and impact where possible
4. Be specific but concise (under 100 characters)

{context}

Return a JSON array of accomplishments with this format:
[
  {{
    "project": "Project Name",
    "summary": "One sentence describing the accomplishment",
    "category": "Feature|Infrastructure|Testing|Documentation|Integration"
  }}
]

Only include meaningful accomplishments - skip routine maintenance or unclear activities.
Return ONLY the JSON array, no other text."""


def call_claude_api(prompt: str) -> Optional[str]:
    """Call Claude API to generate summaries."""
    try:
        import anthropic
    except ImportError:
        print("anthropic package not installed. Run: pip install anthropic")
        return None

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("ANTHROPIC_API_KEY not set in environment")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-3-haiku-20240307",  # Use Haiku for cost efficiency
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return message.content[0].text
    except Exception as e:
        print(f"Claude API error: {e}")
        return None


def parse_ai_response(response: str) -> List[Dict[str, Any]]:
    """Parse the AI response into structured data."""
    if not response:
        return []

    try:
        # Try to extract JSON from response
        response = response.strip()
        if response.startswith('['):
            return json.loads(response)

        # Try to find JSON in the response
        import re
        json_match = re.search(r'\[[\s\S]*\]', response)
        if json_match:
            return json.loads(json_match.group())
    except json.JSONDecodeError as e:
        print(f"Failed to parse AI response: {e}")

    return []


def save_ai_summaries(summaries: List[Dict[str, Any]], week_start: datetime) -> Path:
    """Save AI-generated summaries to file."""
    output_dir = Path(__file__).parent.parent / "data" / "ai_summaries"
    output_dir.mkdir(parents=True, exist_ok=True)

    week_str = week_start.strftime("%Y-W%W")
    output_file = output_dir / f"summaries_{week_str}.json"

    with open(output_file, 'w') as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "week": week_str,
            "summaries": summaries
        }, f, indent=2)

    return output_file


def load_ai_summaries(week_start: datetime = None) -> List[Dict[str, Any]]:
    """Load AI-generated summaries for a week."""
    if week_start is None:
        week_start = datetime.now() - timedelta(days=datetime.now().weekday())

    output_dir = Path(__file__).parent.parent / "data" / "ai_summaries"
    week_str = week_start.strftime("%Y-W%W")
    output_file = output_dir / f"summaries_{week_str}.json"

    if not output_file.exists():
        return []

    try:
        with open(output_file) as f:
            data = json.load(f)
            return data.get("summaries", [])
    except (json.JSONDecodeError, IOError):
        return []


def run_ai_summarization(days: int = 7, dry_run: bool = False) -> List[Dict[str, Any]]:
    """
    Run the AI summarization process.

    Args:
        days: Number of days to look back
        dry_run: If True, don't call API, just show what would be sent

    Returns:
        List of AI-generated summaries
    """
    print(f"Loading activities from the past {days} days...")
    activities = load_weekly_activities(days)
    print(f"Found {len(activities)} activities")

    if not activities:
        print("No activities to analyze")
        return []

    print("Preparing context for AI...")
    context = prepare_context_for_ai(activities)

    prompt = generate_ai_summaries_prompt(context)

    if dry_run:
        print("\n=== DRY RUN - Would send to Claude: ===")
        print(prompt)
        print("=== END DRY RUN ===\n")
        return []

    print("Calling Claude API for analysis...")
    response = call_claude_api(prompt)

    if not response:
        print("No response from API")
        return []

    print("Parsing response...")
    summaries = parse_ai_response(response)

    if not summaries:
        print("No summaries generated")
        print(f"Raw response: {response[:200]}...")
        return []

    print(f"Generated {len(summaries)} summaries:")
    for s in summaries:
        print(f"  - [{s.get('project', '?')}] {s.get('summary', '')}")

    # Save summaries
    week_start = datetime.now() - timedelta(days=datetime.now().weekday())
    output_file = save_ai_summaries(summaries, week_start)
    print(f"\nSaved to: {output_file}")

    return summaries


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate AI-enhanced accomplishment summaries")
    parser.add_argument("--days", type=int, default=7, help="Days to look back")
    parser.add_argument("--dry-run", action="store_true", help="Show prompt without calling API")

    args = parser.parse_args()

    summaries = run_ai_summarization(args.days, args.dry_run)

    if summaries:
        print(f"\nSuccessfully generated {len(summaries)} accomplishment summaries")


if __name__ == "__main__":
    main()
