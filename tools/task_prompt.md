
# You are doing task {TASK}. Work only on this task.
1. Read CLAUDE.md, the {TASK} line in docs/TASKS.md, and the {TASK} row in docs/ROADMAP.md if it has one.
2. Run `git status`. If an earlier attempt left changes, continue from them; do not start over.
3. Write or update a test that shows the problem and confirm it fails. If a test is marked
   xfail for {TASK}, remove the xfail mark. Skip this step only for pure packaging changes.
4. Make the smallest change that makes the test pass. Do not touch unrelated code.
5. Run `python -m pytest -q`. Everything must pass.
6. If pdfopt_core.py changed and tools/build_notebooks.py exists, run it.
7. Commit everything: `git add -A` then `git commit -m "{TASK}: <what changed>"`.
8. In docs/TASKS.md change "- [ ] {TASK}" to "- [x] {TASK}", add one indented line saying what
   changed, and commit that.
If you cannot finish (unclear requirement, a test you cannot make pass, a decision only the owner can
make), add a line to docs/BLOCKED.md that starts with {TASK}, then the reason;
commit it and stop without ticking the task.
