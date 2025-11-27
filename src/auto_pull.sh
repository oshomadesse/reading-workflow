#!/bin/bash

# Define variables
REPO_DIR="/Users/seihoushouba/Documents/Oshomadesse-pc/11_Engineering/📖 books-summary"
LOG_FILE="$REPO_DIR/data/integrated/auto_pull.log"
DATE=$(date "+%Y-%m-%d %H:%M:%S")

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

echo "[$DATE] Starting auto-pull..." >> "$LOG_FILE"

# Navigate to repository
cd "$REPO_DIR" || {
    echo "[$DATE] ❌ Failed to cd to $REPO_DIR" >> "$LOG_FILE"
    exit 1
}

# Pull changes
# Using --rebase to avoid merge commits if there are local changes (though artifacts should be clean)
# Using -X theirs to prefer remote changes if conflicts arise in artifacts (unlikely with auto-move)
OUTPUT=$(git pull origin main --rebase 2>&1)
EXIT_CODE=$?

echo "$OUTPUT" >> "$LOG_FILE"

if [ $EXIT_CODE -eq 0 ]; then
    echo "[$DATE] ✅ Pull successful." >> "$LOG_FILE"
else
    echo "[$DATE] ❌ Pull failed with exit code $EXIT_CODE." >> "$LOG_FILE"
fi
