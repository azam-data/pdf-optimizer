
# Task queue (top to bottom). [auto] = overnight on Sonnet. [you] = interactive (Phase 0 on Sonnet, the rest on opusplan).

## Phase 0: safety net (run these with the Phase 0 prompt, watching)
- [x] P0.1 [you] tests/make_samples.py: generate the synthetic test PDFs listed in ROADMAP Phase 0
- [x] P0.2 [you] pytest suite + tests/baseline.json with expected sizes per sample and setting
- [x] P0.3 [auto] tools/build_notebooks.py builds notebooks/ from pdfopt_core.py; a test fails if they differ (E5) Decision: generate only the engine code cell in both notebooks, and leave the batch-logic cell of the Batch notebook alone.
  - Added tools/build_notebooks.py (engine cell only, `--check` mode) and tests/test_notebooks.py; notebooks regenerated.
- [ ] P0.4 [auto] CI: run pytest on windows-latest before the build; download eng.traineddata in that job; tests must fail, not skip, when CI is set; also trigger the workflow on push to any branch and on pull_request, keeping the release and manual triggers.

## Phase 1: bugs and small fixes
- [ ] E1 [auto]
- [ ] E2 [auto]
- [ ] E3 [auto]
- [ ] E4 [auto]
- [ ] R3 [auto]
- [ ] Q5 [auto]
- [ ] Q6 [auto]
- [ ] Q7 [auto]
- [ ] R2 [auto]
- [ ] R4 [auto]
- [ ] Q4 [you]
- [ ] Q8 [you]

## Phase 2: scan-mode quality
- [ ] Q3 [you]
- [ ] Q1 [you]
- [ ] Q2 [you]
- [ ] R1 [you]

## Phase 3: missed savings
- [ ] M1 [you]
- [ ] M3 [you]
- [ ] M2 [you]

## Phase 4: size
- [ ] S5 [auto]
- [ ] S3 [auto]
- [ ] S4 [auto]
- [ ] S2 [auto]
- [ ] S1 [you]

## Phase 5: features (reorder or delete lines as you like)
- [ ] F3 [auto]
- [ ] F2 [auto]
- [ ] F1 [you]
- [ ] F4 [auto]
- [ ] F7 [auto]
- [ ] F8 [auto]
- [ ] F14 [auto]
- [ ] F6 [auto]
- [ ] F12 [auto]
- [ ] F5 [you]
- [ ] F9 [you]
