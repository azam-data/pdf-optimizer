
# Task queue (top to bottom). [auto] = overnight on Sonnet. [you] = interactive (Phase 0 on Sonnet, the rest on opusplan).

## Phase 0: safety net (run these with the Phase 0 prompt, watching)
- [x] P0.1 [you] tests/make_samples.py: generate the synthetic test PDFs listed in ROADMAP Phase 0
- [x] P0.2 [you] pytest suite + tests/baseline.json with expected sizes per sample and setting
- [x] P0.3 [auto] tools/build_notebooks.py builds notebooks/ from pdfopt_core.py; a test fails if they differ (E5) Decision: generate only the engine code cell in both notebooks, and leave the batch-logic cell of the Batch notebook alone.
  - Added tools/build_notebooks.py (engine cell only, `--check` mode) and tests/test_notebooks.py; notebooks regenerated.
- [x] P0.4 [auto] CI: run pytest on windows-latest before the build; download eng.traineddata in that job; tests must fail, not skip, when CI is set; also trigger the workflow on push to any branch and on pull_request, keeping the release and manual triggers.
  - Workflow triggers on push and pull_request, runs pytest (CI=true, after the tessdata download) before the build; the jbig2 test now fails instead of skipping on CI.

## Phase 1: bugs and small fixes
- [x] E1 [auto]
  - plan_folder now uses _is_within (normcase + realpath + commonpath + samefile), so a differently-cased output inside the input is rejected; xfail removed. The check rejects nested folders, so the walk never visits the output folder.
- [x] E2 [auto]
  - optimize_pdf catches OSError on the final os.replace and on the fallback copy and returns status "failed (output in use)"; run_folder's last-resort copy does the same, so the batch continues. New test tests/test_batch_locked.py; notebooks regenerated.
- [x] E3 [auto]
  - run_folder now deletes leftover *.tmp_pdfopt / *.fonts_pdfopt files (recursively) in the output folder before starting; new test tests/test_leftover_temp.py. pdfopt_core.py unchanged, so no notebook regeneration.
- [x] E4 [auto]
  - pdfopt-cli single-file mode exits 0 optimized, 3 original kept, 1 error; new `--json` prints the result with `exit_code`.
- [x] R3 [auto]
  - optimize_pdf copies PDFs that forbid modification ("copied (protected)") or that MuPDF had to repair ("copied (damaged)") unchanged; new tests/test_protected_damaged.py; notebooks regenerated.
- [x] Q5 [auto]
  - OCR words that are half or more "?" or mostly symbols are dropped before the text layer is written (_clean_ocr_words); new tests/test_ocr_filter.py; notebooks regenerated.
- [x] Q6 [auto]
  - Output files get a custom /PdfOptimizer key in the Info dict; when present, JPEG images are left untouched on re-runs (_is_marked/_set_mark); new tests/test_rerun_marker.py; notebooks regenerated.
- [x] Q7 [auto]
  - GUI checkbox "Keep fonts unchanged" and CLI --keep-fonts set optimize_fonts=False (no subsetting or hinting removal); defaults unchanged; new tests/test_keep_fonts.py.
- [x] R2 [auto]
  - jbig2 now gets a relative file name (cwd = temp dir) and a failed run is logged as a warning; notebooks regenerated.
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
