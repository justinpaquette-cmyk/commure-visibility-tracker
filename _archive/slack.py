"""Slack action item collector.

Imports action items from Slack via:
1. Manual paste (no setup required)
2. File import (export from Slack)
3. API (requires Slack app setup - future)

Includes intelligent project inference from content and channels.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Activity, ActivitySource


def load_projects_config() -> Dict[str, Any]:
    """Load projects configuration."""
    config_path = Path(__file__).parent.parent / "config" / "projects.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {"projects": []}


def infer_project_from_content(
    text: str,
    channels: List[str],
    projects_config: Dict[str, Any] = None
) -> Optional[str]:
    """
    Infer project from Slack content and channels.

    Uses multiple signals:
    1. Slack channel mappings (highest confidence)
    2. Partial channel matching (e.g., "compassus-835-client" matches "compassus")
    3. Project name/alias mentions in text
    4. Client name mentions

    Args:
        text: The action item text
        channels: List of #channels mentioned
        projects_config: Projects configuration (loaded if not provided)

    Returns:
        Project name or None if no match found (allows matcher to recategorize)
    """
    if projects_config is None:
        projects_config = load_projects_config()

    projects = projects_config.get("projects", [])
    text_lower = text.lower()

    # Build lookup structures
    channel_to_project = {}
    alias_to_project = {}
    name_to_project = {}

    for project in projects:
        project_name = project.get("name", "")

        # Map channels to project
        for channel in project.get("slack_channels", []):
            channel_to_project[channel.lower().strip('#')] = project_name

        # Map aliases to project
        for alias in project.get("aliases", []):
            alias_to_project[alias.lower()] = project_name

        # Map project name and ID
        name_to_project[project_name.lower()] = project_name
        name_to_project[project.get("id", "").lower()] = project_name

    # Signal 1: Exact channel mapping (highest confidence)
    for channel in channels:
        channel_clean = channel.lower().strip('#')
        if channel_clean in channel_to_project:
            return channel_to_project[channel_clean]

    # Signal 2: Partial channel matching (e.g., "compassus-835-client" matches "compassus")
    for channel in channels:
        channel_clean = channel.lower().strip('#')
        for config_channel, project_name in channel_to_project.items():
            if channel_clean.startswith(config_channel) or config_channel.startswith(channel_clean):
                return project_name

    # Signal 3: Alias matching in text
    for alias, project_name in alias_to_project.items():
        if alias in text_lower:
            return project_name

    # Signal 4: Project name matching in text
    for name, project_name in name_to_project.items():
        if name and len(name) > 2 and name in text_lower:
            return project_name

    # Return None to let the matcher try other signals
    return None


def parse_slack_action_items(text: str) -> List[dict]:
    """
    Parse action items from Slack's action item format.

    Expected formats:
    - "[ ] Action item text - @person - #channel - date"
    - "• Action item text"
    - "- [ ] Action item"
    - Numbered lists: "1. Action item"
    """
    items = []

    lines = text.strip().split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip headers/metadata
        if line.startswith('#') and not line.startswith('# '):
            continue
        if line.lower().startswith('action items'):
            continue

        # Extract action item text
        item_text = None
        is_complete = False

        # Format: "[ ] text" or "[x] text"
        checkbox_match = re.match(r'^\[([x ])\]\s*(.+)', line, re.IGNORECASE)
        if checkbox_match:
            is_complete = checkbox_match.group(1).lower() == 'x'
            item_text = checkbox_match.group(2)

        # Format: "- [ ] text" or "• [ ] text"
        bullet_checkbox = re.match(r'^[-•*]\s*\[([x ])\]\s*(.+)', line, re.IGNORECASE)
        if bullet_checkbox:
            is_complete = bullet_checkbox.group(1).lower() == 'x'
            item_text = bullet_checkbox.group(2)

        # Format: "- text" or "• text" (simple bullet)
        if not item_text:
            bullet_match = re.match(r'^[-•*]\s+(.+)', line)
            if bullet_match:
                item_text = bullet_match.group(1)

        # Format: "1. text" (numbered)
        if not item_text:
            numbered_match = re.match(r'^\d+\.\s+(.+)', line)
            if numbered_match:
                item_text = numbered_match.group(1)

        if item_text:
            # Extract @mentions
            mentions = re.findall(r'@(\w+)', item_text)

            # Extract #channels
            channels = re.findall(r'#([\w-]+)', item_text)

            # Clean up the text
            clean_text = re.sub(r'\s*[-–]\s*@\w+', '', item_text)  # Remove trailing @mentions
            clean_text = re.sub(r'\s*[-–]\s*#[\w-]+', '', clean_text)  # Remove trailing #channels
            clean_text = re.sub(r'\s*[-–]\s*\d{1,2}/\d{1,2}(/\d{2,4})?', '', clean_text)  # Remove dates
            clean_text = clean_text.strip()

            if clean_text and len(clean_text) > 3:
                items.append({
                    'text': clean_text,
                    'raw_text': item_text,
                    'is_complete': is_complete,
                    'mentions': mentions,
                    'channels': channels,
                })

    return items


def import_from_paste(paste_text: str, project_name: str = None) -> List[Activity]:
    """
    Import action items from pasted text.

    Args:
        paste_text: Text copied from Slack
        project_name: Project to associate with (auto-inferred if not provided)

    Returns:
        List of Activity objects
    """
    items = parse_slack_action_items(paste_text)
    activities = []

    now = datetime.now()

    # Load projects config once for inference
    projects_config = load_projects_config() if project_name is None else None

    for i, item in enumerate(items):
        if item['is_complete']:
            continue  # Skip completed items

        # Infer project if not explicitly provided
        if project_name is None:
            inferred_project = infer_project_from_content(
                item['raw_text'],
                item['channels'],
                projects_config
            )
        else:
            inferred_project = project_name

        # Lower confidence if we couldn't infer a project
        # This allows the matcher to potentially recategorize using other signals
        confidence = 0.9 if inferred_project else 0.5

        activity = Activity(
            source=ActivitySource.SLACK,
            timestamp=now,
            description=f"[Slack] {item['text']}",
            confidence=confidence,
            raw_data={
                'raw_text': item['raw_text'],
                'mentions': item['mentions'],
                'channels': item['channels'],
                'project': inferred_project,  # Can be None, matcher will try other signals
                'type': 'action_item',
                'needs_categorization': inferred_project is None,
            },
        )
        activities.append(activity)

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

    # Merge
    existing_descs = {a.description for a in existing}
    for activity in activities:
        if activity.description not in existing_descs:
            existing.append(activity)

    # Save
    with open(filepath, "w") as f:
        json.dump({
            "date": date.strftime("%Y-%m-%d"),
            "collected_at": datetime.now().isoformat(),
            "activities": [a.to_dict() for a in existing],
        }, f, indent=2)

    return str(filepath)


def interactive_import():
    """Interactive mode for pasting action items."""
    print("\n=== Slack Action Item Import ===")
    print("Paste your action items below (press Enter twice when done):\n")

    lines = []
    empty_count = 0

    while True:
        try:
            line = input()
            if line == "":
                empty_count += 1
                if empty_count >= 2:
                    break
            else:
                empty_count = 0
                lines.append(line)
        except EOFError:
            break

    if not lines:
        print("No input received.")
        return

    text = '\n'.join(lines)
    activities = import_from_paste(text)

    if not activities:
        print("\nNo action items found in the input.")
        return

    print(f"\nFound {len(activities)} action item(s):\n")
    for a in activities:
        print(f"  • {a.description}")

    confirm = input("\nSave these? [Y/n]: ").strip().lower()
    if confirm in ('', 'y', 'yes'):
        path = save_activities(activities)
        print(f"\nSaved to {path}")
    else:
        print("Cancelled.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Import Slack action items")
    parser.add_argument("--file", "-f", help="Import from file instead of interactive")
    parser.add_argument("--project", "-p", default="Slack", help="Project name to associate")

    args = parser.parse_args()

    if args.file:
        with open(args.file, 'r') as f:
            text = f.read()
        activities = import_from_paste(text, args.project)
        if activities:
            print(f"Found {len(activities)} action items:")
            for a in activities:
                print(f"  • {a.description}")
            path = save_activities(activities)
            print(f"\nSaved to {path}")
        else:
            print("No action items found.")
    else:
        interactive_import()
