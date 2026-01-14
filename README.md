# Commure Visibility Tracker

A personal task tracking system that provides visibility into work across multiple teams by automatically detecting activity from multiple sources.

## Features

- **Multi-source activity detection:**
  - File system changes (modified files in project folders)
  - Git commits
  - Claude Code session logs (task requests, files edited, tool usage)
  - Manual activity entries

- **Team-based organization:** Configure projects by team for distribution visibility
- **Theme tracking:** Group work into themes/initiatives with status tracking
- **Nightly recap:** Automated summary of daily work with proposed roadmap updates
- **Review workflow:** Approve/reject proposed changes before updating the roadmap

## Quick Start

1. **Configure your projects** in `config/projects.json`:
```json
{
  "projects": [
    {
      "id": "my-project",
      "name": "My Project",
      "team": "Team A",
      "folder_path": "/path/to/project",
      "privacy": "public"
    }
  ],
  "excluded_folders": ["/path/to/personal"]
}
```

2. **Run the daily recap:**
```bash
python3 agent/nightly.py --hours 24
```

Or use the `/recap` command in Claude Code.

3. **Review proposed changes:**
```bash
python3 cli/review.py list
python3 cli/review.py approve all
```

## CLI Commands

### Recap Agent
```bash
# Run daily recap
python3 agent/nightly.py --hours 24

# Run with verbose output
python3 agent/nightly.py --hours 72 -v

# Preview without saving changes
python3 agent/nightly.py --no-save
```

### Manual Entry
```bash
# Log manual activity
python3 cli/manual.py log "Team standup meeting"

# Add a theme
python3 cli/manual.py theme add "API Redesign" -s active

# List themes
python3 cli/manual.py theme list

# Check status
python3 cli/manual.py status
```

### Review Changes
```bash
# List pending changes
python3 cli/review.py list

# Approve specific change
python3 cli/review.py approve <change_id>

# Approve all changes
python3 cli/review.py approve all

# Reject changes
python3 cli/review.py reject <change_id>
```

### Test Collectors
```bash
# Test Claude Code session collector
python3 collectors/claude.py --hours 24 --summary

# Test git collector
python3 collectors/git.py --hours 24 -v

# Test filesystem collector
python3 collectors/filesystem.py --hours 24 -v
```

## Sample Output

```
============================================================
DAILY RECAP - 2026-01-14 09:57
============================================================

Total activities: 42
Projects touched: Project A, Project B, Project C
Sources: claude(11), filesystem(27), git(4)

## Claude Code Sessions
  Active sessions: 7
  Total messages: 765
  Files edited: 67
  Top tools: Bash(273), Edit(110), Read(81)

## Team Distribution
  Sales Engineering: 81% (25 activities)
  Product Management: 19% (6 activities)

## Activity by Theme

### Project A (Team A)
  [●] Feature Development: 9 activities

### Project B (Team B)
  [●] Bug Fixes: 5 activities
```

## Project Structure

```
commure-task-tracker/
├── config/
│   ├── projects.json      # Project → team mappings
│   └── settings.json      # Scan paths, thresholds
├── data/
│   ├── roadmap.json       # Source of truth
│   └── activities/        # Daily activity logs
├── collectors/
│   ├── filesystem.py      # File change detection
│   ├── git.py             # Commit parsing
│   └── claude.py          # Claude Code session parsing
├── agent/
│   └── nightly.py         # Main recap agent
├── cli/
│   ├── manual.py          # Manual entry tool
│   └── review.py          # Change review tool
└── models.py              # Data models
```

## Requirements

- Python 3.8+
- No external dependencies (uses stdlib only)

## Future Enhancements

- Notion export integration
- Slack action item integration
- Historical reporting and trends
- Web dashboard (AI Studio hosted)
