#!/bin/bash
# Start Studio AI (short-form + long-form, client brands) on http://127.0.0.1:4322.
SELF="$0"; [ -L "$SELF" ] && SELF="$(readlink "$SELF")"
exec /bin/bash "$(cd "$(dirname "$SELF")" && pwd)/01. Short-form/Open Studio AI short-form editor.command" "$@"
