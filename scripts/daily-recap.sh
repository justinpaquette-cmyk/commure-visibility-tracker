#!/bin/bash
# Daily recap cron script
# Add to crontab: 0 18 * * * /path/to/daily-recap.sh
# Runs at 6 PM daily

TRACKER_DIR="/Users/justinpaquette/Documents/sales eng projects v2/productivity/commure-task-tracker"
OUTPUT_DIR="$TRACKER_DIR/data/recaps"
DATE=$(date +%Y-%m-%d)
OUTPUT_FILE="$OUTPUT_DIR/$DATE.txt"

# Ensure output directory exists
mkdir -p "$OUTPUT_DIR"

# Run the recap
cd "$TRACKER_DIR"
python3 agent/nightly.py --hours 24 > "$OUTPUT_FILE" 2>&1

# Optional: Send notification (uncomment one)

# macOS notification
# osascript -e 'display notification "Daily recap complete" with title "Task Tracker"'

# Terminal-notifier (if installed)
# terminal-notifier -title "Task Tracker" -message "Daily recap saved to $OUTPUT_FILE"

# Echo for cron log
echo "Recap saved to $OUTPUT_FILE"
