#!/bin/bash
# Checks every tool Studio AI needs and says how to fix anything missing.
cd "$(dirname "$0")" || exit 1
python3 "./doctor.py" --claude
echo; read -r -p "Press Enter to close. " _
