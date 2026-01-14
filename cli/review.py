#!/usr/bin/env python3
"""Review CLI for approving/rejecting proposed changes."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Roadmap, ThemeStatus


def load_roadmap() -> Roadmap:
    """Load current roadmap."""
    roadmap_path = Path(__file__).parent.parent / "data" / "roadmap.json"
    return Roadmap.load(str(roadmap_path))


def save_roadmap(roadmap: Roadmap):
    """Save roadmap."""
    roadmap_path = Path(__file__).parent.parent / "data" / "roadmap.json"
    roadmap.save(str(roadmap_path))


def apply_change(roadmap: Roadmap, change_id: str) -> bool:
    """Apply a proposed change to the roadmap."""
    change = None
    for c in roadmap.pending_changes:
        if c.id == change_id:
            change = c
            break

    if not change:
        print(f"Change not found: {change_id}")
        return False

    if change.change_type == "status_change":
        theme_id = change.details.get("theme_id")
        new_status = change.details.get("new_status")

        for project in roadmap.projects:
            for theme in project.themes:
                if theme.id == theme_id:
                    theme.status = ThemeStatus(new_status)
                    theme.last_touched = datetime.now()
                    change.approved = True
                    return True

    elif change.change_type == "stale_warning":
        # Just mark as acknowledged
        change.approved = True
        return True

    elif change.change_type == "new_theme_suggestion":
        # This would need more info - just acknowledge for now
        change.approved = True
        print(f"Acknowledged. Use 'python cli/manual.py theme add <name>' to create the theme.")
        return True

    return False


def reject_change(roadmap: Roadmap, change_id: str) -> bool:
    """Reject a proposed change."""
    for change in roadmap.pending_changes:
        if change.id == change_id:
            change.approved = False
            return True
    return False


def cmd_list(args):
    """List pending changes."""
    roadmap = load_roadmap()

    pending = [c for c in roadmap.pending_changes if c.approved is None]

    if not pending:
        print("No pending changes to review.")
        return

    print(f"\n{len(pending)} pending change(s):\n")

    for change in pending:
        print(f"  [{change.id}] {change.change_type}")
        print(f"      {change.description}")
        if change.details.get("sample_descriptions"):
            print("      Samples:")
            for sample in change.details["sample_descriptions"][:2]:
                print(f"        - {sample[:50]}")
        print()


def cmd_approve(args):
    """Approve a change."""
    if not args:
        print("Usage: review.py approve <change_id or 'all'>")
        return

    roadmap = load_roadmap()

    if args[0] == "all":
        pending = [c for c in roadmap.pending_changes if c.approved is None]
        for change in pending:
            apply_change(roadmap, change.id)
        save_roadmap(roadmap)
        print(f"Approved {len(pending)} change(s)")
    else:
        if apply_change(roadmap, args[0]):
            save_roadmap(roadmap)
            print(f"Approved change {args[0]}")
        else:
            print(f"Failed to apply change {args[0]}")


def cmd_reject(args):
    """Reject a change."""
    if not args:
        print("Usage: review.py reject <change_id or 'all'>")
        return

    roadmap = load_roadmap()

    if args[0] == "all":
        pending = [c for c in roadmap.pending_changes if c.approved is None]
        for change in pending:
            reject_change(roadmap, change.id)
        save_roadmap(roadmap)
        print(f"Rejected {len(pending)} change(s)")
    else:
        if reject_change(roadmap, args[0]):
            save_roadmap(roadmap)
            print(f"Rejected change {args[0]}")


def cmd_clear(args):
    """Clear all processed changes."""
    roadmap = load_roadmap()
    processed = [c for c in roadmap.pending_changes if c.approved is not None]
    roadmap.pending_changes = [c for c in roadmap.pending_changes if c.approved is None]
    save_roadmap(roadmap)
    print(f"Cleared {len(processed)} processed change(s)")


def cmd_help(args):
    """Show help."""
    print("""
Review CLI - Approve or reject proposed roadmap changes

Commands:
  list                  Show pending changes
  approve <id>          Approve a specific change
  approve all           Approve all pending changes
  reject <id>           Reject a specific change
  reject all            Reject all pending changes
  clear                 Clear processed changes

Examples:
  python cli/review.py list
  python cli/review.py approve a1b2c3d4
  python cli/review.py approve all
""")


def main():
    if len(sys.argv) < 2:
        cmd_list([])
        return

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "list": cmd_list,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "clear": cmd_clear,
        "help": cmd_help,
        "-h": cmd_help,
        "--help": cmd_help,
    }

    if command in commands:
        commands[command](args)
    else:
        print(f"Unknown command: {command}")
        cmd_help([])


if __name__ == "__main__":
    main()
