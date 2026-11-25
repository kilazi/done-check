#!/bin/sh
# done-check Stop hook entry: runs the stdlib-only Python check, lets go if python3 is missing.
DIR=$(cd "$(dirname "$0")" && pwd)
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$DIR/done_check.py"
fi
cat >/dev/null
echo '{"systemMessage":"done-check: python3 not found, not checking"}'
exit 0
