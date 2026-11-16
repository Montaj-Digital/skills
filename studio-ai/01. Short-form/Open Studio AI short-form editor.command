#!/bin/bash
# Start the Studio AI and open it in your browser. Keep this window open while you work;
# close it (or press Ctrl+C) to stop the editor.
SELF="$0"; [ -L "$SELF" ] && SELF="$(readlink "$SELF")"
cd "$(dirname "$SELF")/04. Editor" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
if curl -s -o /dev/null --max-time 2 http://127.0.0.1:4322/api/project; then
  echo "The editor is already running. Opening it…"; open "http://127.0.0.1:4322/"; exit 0
fi
python3 server.py "$@"
