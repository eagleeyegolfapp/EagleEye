#!/bin/bash
# Reopen the EagleEye social UI. Safe to run anytime.
# Closing the window does not stop scheduled posts.
DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/EagleEye Marketing 2.0/automation"
URL="http://127.0.0.1:8787/"
cd "$DIR" || exit 1
if curl -sf -o /dev/null --max-time 1 "$URL"; then
  open "$URL"
  exit 0
fi
exec /usr/bin/python3 "$DIR/dashboard.py"
