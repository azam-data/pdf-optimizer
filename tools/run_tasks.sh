#!/bin/bash
# Runs the [auto] tasks in docs/TASKS.md one at a time, each in a fresh Claude Code session.
# Start: source .venv/bin/activate && caffeinate -i ./tools/run_tasks.sh
cd "$(dirname "$0")/.." || exit 1
LOCK="/tmp/pdfopt-runner.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "A runner is already active (if not, delete $LOCK)."; exit 1
fi
trap 'rmdir "$LOCK"' EXIT
mkdir -p logs
MODEL="sonnet"; MAX_ATTEMPTS=3; last=""; attempts=0
TOOLS='Read,Edit,Write,Glob,Grep,Bash(python -m pytest:*),Bash(python tools/build_notebooks.py),Bash(python tools/build_notebooks.py:*),Bash(python tests/make_samples.py),Bash(python tests/make_samples.py:*),Bash(git status:*),Bash(git diff:*),Bash(git log:*),Bash(git add:*),Bash(git commit:*)'
now() { date '+%Y-%m-%d %H:%M'; }
while true; do
  line=$(grep -m1 -E '^- \[ \] ' docs/TASKS.md)
  [ -z "$line" ] && { echo "$(now) All tasks done."; break; }
  task=$(echo "$line" | sed -E 's/^- \[ \] ([A-Z0-9.]+).*/\1/')
  if echo "$line" | grep -q '\[you\]'; then echo "$(now) Next task $task needs you. Stopping."; break; fi
  if [ -s docs/BLOCKED.md ] && grep -q "^$task" docs/BLOCKED.md; then echo "$(now) $task is blocked, see docs/BLOCKED.md."; break; fi
  if [ "$task" = "$last" ]; then attempts=$((attempts+1)); else attempts=1; last="$task"; fi
  if [ "$attempts" -gt "$MAX_ATTEMPTS" ]; then echo "$(now) $task failed $MAX_ATTEMPTS times. Stopping."; break; fi
  log="logs/$(date +%Y%m%d-%H%M%S)-$task.json"
  echo "$(now) Starting $task (attempt $attempts), log: $log"
  prompt=$(sed "s/{TASK}/$task/g" tools/task_prompt.md)
  before=$(git rev-parse HEAD)
  claude -p "$prompt" --model "$MODEL" --permission-mode acceptEdits \
    --allowedTools "$TOOLS" --max-turns 80 --output-format json > "$log" 2>&1
  # Safety: an unattended task must never change the test baseline (committed or not).
  if [ -n "$(git diff --name-only "$before" -- tests/baseline.json)" ]; then
    echo "$(now) $task changed tests/baseline.json. Review: git diff $before -- tests/baseline.json"; break
  fi
  if grep -qiE 'usage limit|limit reached|hit your limit' "$log"; then
    echo "$(now) Usage limit. Waiting 30 minutes, then retrying $task."
    attempts=$((attempts-1)); sleep 1800; continue
  fi
  if grep -qE "^- \[x\] $task( |$)" docs/TASKS.md; then echo "$(now) $task done."; else echo "$(now) $task not finished, retrying."; fi
done
