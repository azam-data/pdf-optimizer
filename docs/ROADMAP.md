# PDF Optimizer: codebase review and work plan

Nov 11, 2026 · @humayun

## Summary

The app works well on the files tested, but the review found two real bugs, three ways scan mode can lose content without warning, and about 50 MB of removable size. Fix order: tests first, then bugs, then quality, then size, then features.

The codebase is small: 1,625 lines in four files (`pdfopt_core.py` 979, `app_gui.py` 451, `pdfopt_batch.py` 133, `app_cli.py` 62). It has no automated tests, and the notebooks carry a pasted copy of the engine.

| Area | Main finding | Detail |
| --- | --- | --- |
| Bugs | The batch "output inside input" check is case-sensitive on Windows, and one locked output file aborts a whole batch | E1, E2 |
| Silent content loss | Scan mode erased pastel chart fills in a test and still reported "all pages verified" | Q1 to Q3 |
| Missed savings | Black-and-white scans stored as stencil masks are skipped; so are CMYK and palette images | M1 to M3 |
| OCR | A scanned page carrying any digital text (even a stamped page number) gets no OCR | Q4 |
| Size | 128 MB unpacked can become about 77 MB; the download can drop from 58 MB to about 36 MB today with no code change | S1 to S5 |
| Features | Fourteen additions need no new libraries; "fit under 10 MB" is the most useful | F1 to F14 |

**Which model does what.** Sonnet handles tests, bug fixes, packaging and simple features, which is most of the work. Opus is needed for four design-heavy tasks: the scan-mode picture guard, the verification redesign, CMYK handling and the NumPy rebuild. Fable is only worth using for one review pass after the scan-mode changes, and that pass is optional.

## Option 2: Edge cases and fixes

Nineteen issues, grouped by how serious they are. "Tested" means I reproduced it with a synthetic file; "In code" means it follows directly from the source; "Risk" means likely but not reproduced.

### Bugs

| ID | Problem | Status | Fix | Model |
| --- | --- | --- | --- | --- |
| E1 | `plan_folder` compares paths with `abspath` and `startswith`, which is case-sensitive. On Windows, output `d:\docs\out` inside input `D:\Docs` is not detected, so the walk can process its own output. | In code | Compare with `normcase` + `realpath` + `commonpath`; also exclude the output folder from the walk. | Sonnet |
| E2 | If an output file is open in another program, the final rename fails. In batch mode the fallback copy fails too, and the whole run stops. | In code | Catch the error per file, record "failed (output in use)", continue. | Sonnet |
| E3 | Closing the app or a crash mid-file leaves `*.tmp_pdfopt` and `*.fonts_pdfopt` files in the output folder. | In code | Write temp files to the system temp folder, or clean leftovers at start. | Sonnet |
| E4 | `pdfopt-cli` returns exit code 0 even when the original was kept because of an error, so microPDF cannot tell. | In code | Exit codes: 0 optimized, 3 original kept, 1 error; add `--json`. | Sonnet |
| E5 | The notebooks contain a pasted copy of the engine. That drift caused the `__file__` crash in the v1.1 notebooks. | Happened | Generate notebooks from `pdfopt_core.py` with a script in the repo; CI fails if they differ. | Sonnet |

### Silent quality loss

| ID | Problem | Status | Fix | Model |
| --- | --- | --- | --- | --- |
| Q1 | Scan mode erases light colour fills: pastel chart bars, shaded cells, highlighter. In my test the chart area went from RGB (226, 222, 213) to (248, 248, 248) and the result still said "all pages verified". | Tested | Detect pictures by colour saturation and by flat light areas, not only mid-grey; keep them in the colour layer. | Opus |
| Q2 | The stroke check only counts dark strokes (below 60% of paper brightness). Pencil notes, faint stamps and grey text between 60% and 88% can vanish unnoticed. | In code | Add a second check for mid-tone ink; keep the area as a picture when it fails. | Opus |
| Q3 | Verification is coarse. Normal pages are compared at 40 DPI on a page average, so a small missing item passes. Scan pages use a correlation that scored about 0.99 on every page tested, so it rejects almost nothing. | In code | Compare in tiles at 72 DPI and fail on the worst tile; for scan pages compare ink maps. | Opus |
| Q4 | OCR skips any page that already has text. A scan with only a digital "Page 7" stamp got no OCR. | Tested | Decide by how much of the page the existing text covers. | Sonnet |
| Q5 | OCR writes non-Latin text (Bangla) as "?" words, and signatures as noise words. | In code | Drop words that are mostly "?" or symbols. | Sonnet |
| Q6 | Running the optimizer on its own output re-encodes JPEGs again when it gains 10%, so quality erodes with each run. | In code | Mark optimized files in metadata; skip the lossy pass when the mark is present. | Sonnet |
| Q7 | Font subsetting makes later text editing in Acrobat harder, and hinting removal thins text slightly in some viewers. The switches exist in the engine but not in the app. | Known | Add a "Keep fonts unchanged" checkbox. | Sonnet |

### Missed savings

| ID | Problem | Status | Fix | Model |
| --- | --- | --- | --- | --- |
| M1 | Black-and-white scans stored as stencil masks are skipped. A 95 KB test page was left untouched; the same page as a normal 1-bit image compresses to 36 KB. | Tested | Re-encode losslessly with JBIG2, keeping the mask flags. | Sonnet |
| M2 | CMYK images are skipped entirely, so print-ready PDFs barely shrink. | In code | JPEG re-encode with correct CMYK inversion handling, verified by render. | Opus |
| M3 | Palette images are never touched, even oversized screenshots. | In code | Lossless downsample above the DPI threshold; recompress. | Sonnet |

### Robustness

| ID | Problem | Status | Fix | Model |
| --- | --- | --- | --- | --- |
| R1 | Scan mode holds several full-page arrays in memory. Very large scans (A3 at 600 DPI) may run out of memory; the page is then left as it was, with no clear message. | Risk | Cap pixels, process in tiles, report the reason. | Opus |
| R2 | `jbig2.exe` gets an absolute temp path. A Windows user name with non-English letters may break it, and the app then quietly uses the larger CCITT format. | Risk | Pass a relative file name; log the fallback. | Sonnet |
| R3 | Owner-protected PDFs marked "no changes allowed" are still modified. Damaged PDFs are silently repaired by MuPDF. | In code | Copy both unchanged by default, with a note. | Sonnet |
| R4 | Smaller items: Cancel does not interrupt a single OCR page or the final check; a saved window position can open off-screen; "skip existing" accepts zero-byte files; paths over 260 characters are untested. | In code | One clean-up task. | Sonnet |

The app has also never run on real Windows, only under Wine. The GitHub Actions build closes that gap once the repository is published.

## Option 3: Size reduction

The unpacked app can go from 128 MB to about 77 MB with no change in features, quality or speed. Two parts make up 59% of the folder: the PDF engine and NumPy's maths library.

### Where the 128 MB goes (measured on the v1.2 build)

| Part | Size (MB) | Needed? |
| --- | --- | --- |
| MuPDF engine (`mupdfcpp64.dll` 26.4 + `_mupdf.pyd` 13.0) | 38 | Yes. Includes the OCR engine. |
| NumPy's OpenBLAS library (`numpy.libs`) | 37 | No. The engine uses no linear algebra. |
| Two exes, each embedding the same 7.1 MB code archive | 15 | One copy is enough. |
| Python runtime (`python312.dll`) | 7 | Yes |
| NumPy itself | 6 | Yes |
| OpenSSL (`libcrypto-3.dll`, plus `libssl`) | 5 | No. The app never uses the network. |
| English OCR model | 4 | Yes |
| Tcl/Tk (GUI toolkit) | 7 | Mostly |
| `jbig2.exe` | 3 | Yes |
| Pillow | 3 | Yes |
| Everything else | 3 | Mixed (includes unused `psutil` and `yaml`) |

### What to remove

| ID | Change | Saves | Risk | Model |
| --- | --- | --- | --- | --- |
| S1 | Build NumPy without OpenBLAS in the GitHub Actions job. NumPy supports this and falls back to a small built-in routine set. | 37 MB | Medium. Needs a compiler step in CI and a benchmark to confirm speed is unchanged. | Opus |
| S2 | Share one code archive between the GUI and CLI exes (a thin CLI launcher, or one exe that attaches to the console). | 7 MB | Low | Sonnet |
| S3 | Exclude unused runtime modules: OpenSSL, sockets, asyncio, `psutil`, `yaml`, and similar. | About 7 MB | Low. The smoke test catches a missing module. | Sonnet |
| S4 | Trim unused Tcl/Tk data (encodings, extra themes). | 1 to 2 MB | Low | Sonnet |
| S5 | Publish the download as `.7z` instead of `.zip`. Measured with the same compression: 58.4 MB becomes 35.8 MB. | 22.6 MB of download | None for the app. Windows 10 users need 7-Zip to open it. | Sonnet |

S5 needs no code change and can ship first. S1 to S4 together take the folder to about 77 MB.

### What not to do

- **UPX compression of the DLLs.** It would cut more, but it raises antivirus false alarms and slows start-up. That is a bad trade on bank PCs.
- **A custom MuPDF build.** The engine is the largest part, but trimming it means maintaining your own PyMuPDF build. The effort is out of proportion.
- **Replacing NumPy with plain Python.** It would save 43 MB but make scan mode many times slower, which breaks the "same efficiency" condition.

## Option 1: Features that add no size

Fourteen features can be built from libraries already inside the app (MuPDF, Pillow, NumPy, Tesseract), so each adds only a few kilobytes of code. They are ranked by how much they help your stated problem: sending confidential PDFs under a 10 MB email limit.

| ID | Feature | What it gives you | Effort | Model |
| --- | --- | --- | --- | --- |
| F1 | Target size ("fit under 10 MB") | The app steps settings down (colour-layer DPI, JPEG quality, scan DPI) until the file fits, and reports what it traded. | Medium | Opus |
| F2 | Split into parts under the limit | A file that cannot fit is split into numbered parts, each under 10 MB. | Small | Sonnet |
| F3 | Presets | One choice (Email, Archive, Best quality) instead of separate options. | Small | Sonnet |
| F4 | Drop a file on the exe, and "Send to" | Optimize from Explorer without opening the app first. | Small | Sonnet |
| F5 | Parallel batch | Two to four files at once on multi-core PCs; large folders finish several times sooner. | Medium | Opus |
| F6 | Password support | Ask for the password of a protected PDF; optionally protect the output with AES-256. | Small | Sonnet |
| F7 | Privacy clean-up | Remove metadata, hidden text, attachments and scripts before sending. | Small | Sonnet |
| F8 | Remove blank pages | Scan mode already measures ink per page; blank scans can be dropped. | Small | Sonnet |
| F9 | Deskew scanned pages | Straighten tilted scans before conversion; improves OCR and compression. | Medium | Opus |
| F10 | Page tools | Merge, split, extract, rotate, delete pages. | Medium | Sonnet |
| F11 | Images to PDF, PDF to images | Turn phone photos or scanner JPEGs into one optimized PDF, and the reverse. | Small | Sonnet |
| F12 | OCR extras | OCR-only mode (no compression) and export of the recognized text as `.txt`. | Small | Sonnet |
| F13 | Before/after preview | Show one page before and after, at zoom, before saving a batch. | Medium | Sonnet |
| F14 | Housekeeping | Keep the original modified date, write a log file, show version and licences in an About box. | Small | Sonnet |

F10 overlaps with microPDF, so it may belong there instead. Bangla OCR is left out because it needs a second language model, which adds size.

## Work plan

Six phases, run in order. Phase 0 comes first because it is what lets a cheaper model change the engine safely: every later task is accepted by a test, not by someone reading the code.

| Phase | Tasks | Model | Done when |
| --- | --- | --- | --- |
| 0. Safety net | A `pytest` suite built on generated test PDFs (see list below); a baseline table of expected sizes; tests run on Windows in GitHub Actions; notebooks generated from the engine (E5). | Sonnet | CI is green on Windows and the baseline table is committed. |
| 1. Bugs and small fixes | E1 to E4, Q4 to Q7, R2 to R4. Each starts with a test that fails. | Sonnet | All new tests pass; baselines unchanged. |
| 2. Scan-mode quality | Q1, Q2, Q3, R1. | Opus | The pastel-chart, pencil and missing-item tests pass; scanned-document sizes stay within 5% of baseline. |
| 3. Missed savings | M1 and M3, then M2. | Sonnet (M1, M3), Opus (M2) | Stencil-mask, palette and CMYK test files shrink and render the same. |
| 4. Size | S5 first, then S2 to S4, then S1. | Sonnet (S2 to S5), Opus (S1) | Folder at or below 80 MB; full test suite passes on the built exe; scan-mode speed within 5% of before. |
| 5. Features | F1 to F3 first, then pick from F4 to F14. | Mostly Sonnet; Opus for F1, F5, F9 | Each feature ships with its own test and a README line. |

### Test PDFs to generate in Phase 0

All are synthetic, so no bank document enters the repository: a black-and-white scan, a grey scan, a colour scan with a blue signature and red stamp, a page with a logo and a seal, a page with a photo, a page with a pastel bar chart and highlighter, a stencil-mask scan, a page rotated 270 degrees, a page with an offset crop box, a scan with a digital page number, a file with many embedded fonts, a password-protected file, and a CMYK image file.

### How to run this cheaply in Claude Code

1. Export this doc as Markdown and commit it as `docs/ROADMAP.md`. Claude Code then reads tasks by ID.
2. Add a `CLAUDE.md` with four rules: never commit PDFs; run `pytest` before finishing; one task ID per session; never change a threshold without updating the baseline table.
3. Start a new session for each task. Short contexts keep usage down.
4. For the Opus tasks, use Opus only to plan and to write the failing test. Then switch to Sonnet to implement until the test passes.
5. Keep your real documents in a local folder that git ignores, and have a script print a before/after size table for them. Run it after Phases 2 and 3.
6. Use Fable once, after Phase 2, on the diff and the before/after page images only. Skip it if the tests and your own documents look right.

## Evidence for this review

The findings rest on five tests run on 11 November 2026 against the v1.2 engine, plus a read of all four source files. Items marked "In code" or "Risk" above were not reproduced.

| Test | Result |
| --- | --- |
| Scan page with four pastel chart bars, a highlighter band and light grey text | Converted to black and white (949 KB to 36 KB). Chart area changed from RGB (226, 222, 213) to (248, 248, 248). Reported as verified. |
| Scan page with a digital "Page 7" text stamp, OCR on | OCR skipped: "no image-only pages (text already present)". |
| Black-and-white scan stored as a stencil mask | Image skipped; file copied unchanged at 95 KB. |
| Scan page with an offset crop box, OCR on | Passed. The text-layer hit for "Bangladesh" landed within 2 points of the OCR position. |
| Size of each part of the built app; download recompressed with LZMA | 128 MB unpacked; zip 58.4 MB; LZMA 35.8 MB. |

Not measured: the saving from S3 and S4 (estimated from file sizes), the speed effect of S1, and memory use on very large scans (R1).
