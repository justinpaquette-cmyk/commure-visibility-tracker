#!/bin/bash
# Friday wins processor
# Add to crontab: 0 9 * * 5 /path/to/friday-wins.sh
# Runs at 9 AM every Friday

TRACKER_DIR="/Users/justinpaquette/Documents/sales eng projects v2/productivity/commure-task-tracker"
LOG_FILE="$TRACKER_DIR/data/recaps/wins-processing.log"

echo "=== Friday Wins Processing ===" >> "$LOG_FILE"
echo "Started: $(date)" >> "$LOG_FILE"

cd "$TRACKER_DIR"

# Run weekly wins processor
python3 agent/weekly_wins.py --days 7 >> "$LOG_FILE" 2>&1

echo "Completed: $(date)" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# macOS notification
osascript -e 'display notification "Weekly wins processed! Check your Wins folder." with title "Task Tracker"' 2>/dev/null || true
