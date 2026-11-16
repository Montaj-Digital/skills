#!/bin/bash
# One-click install of everything Studio AI needs. Safe to run again to update.
cd "$(dirname "$0")" || exit 1
exec /bin/bash "./install.sh"
