---
description: Daily work recap - simple dashboard with auto cron setup
allowed-tools: Bash, Read, Write
---

# Daily Recap

Simple productivity tracking. No complexity.

## What To Do

1. **Generate recap and open dashboard:**

```bash
python3 ui/simple_gen.py --open
```

2. **Check if cron is set up** (run once to enable auto-collection):

```bash
crontab -l 2>/dev/null | grep -q "simple_gen.py" && echo "Cron is running" || echo "Cron not set - run setup below"
```

3. **If cron not set, add it** (runs every hour during work hours):

```bash
PROJECT_DIR="$(pwd)"
(crontab -l 2>/dev/null; echo "0 9-18 * * 1-5 cd '$PROJECT_DIR' && /usr/bin/python3 ui/simple_gen.py") | crontab -
echo "Cron job added - dashboard auto-updates hourly 9am-6pm weekdays"
```

## Quick Commands

**Morning form (2 min):**
```bash
python3 cli/daily.py form
```

**Quick win:**
```bash
python3 cli/daily.py win "Description"
```

**Quick blocker:**
```bash
python3 cli/daily.py block "Description"
```

**Show today's entry:**
```bash
python3 cli/daily.py show
```

## The System

- `cli/daily.py` - Your intentional input (intent, wins, blockers)
- `agent/simple_recap.py` - Collects activities from Claude/git/filesystem
- `ui/simple_gen.py` - Generates standalone HTML dashboard

## Understanding the Dashboard

- **Activities**: 1 git commit = 1 activity, 1 edited directory = 1 activity, 1 Claude session = 1 activity
- **Files**: Total unique files touched across all sources
- **Projects**: Matched from `config/projects.json` folder paths
- **Team Distribution**: % of activities by team ownership
- **Claude Code**: Sessions, messages exchanged, and tool invocations

~2000 lines total. No AI summarization, no auto-themes, no complexity.
