PDF Optimizer 1.2  -  portable, offline PDF compressor
=======================================================

Start:  double-click "PDF Optimizer.exe". No installation, no admin rights.
        Keep the whole folder together (the _internal folder holds the engine).

Single file : choose a PDF -> "Save as" is filled in as <name>_optimized.pdf -> Optimize.
Folder      : choose an input folder and an output folder. The folder tree is recreated,
              every PDF is optimized under the same name, every other file is copied.
              A CSV report is written NEXT TO the output folder.

Scanned pages : Auto (recommended) = scans rebuilt as sharp black text, coloured ink
                (stamps, blue signatures) kept only where present.
                Black & white only = smallest.  Off = never convert scans.
Grain removal : Off / Light / Medium (default) / Strong. Strong may remove small isolated bullets.
OCR           : "Make scanned pages searchable" adds an invisible English text layer to pages that
                are only images, so you can search, select and copy text. The page looks the same.
                Takes roughly 3-6 s per page; pages that already contain text are skipped.

Safety: the input is never modified; every page is checked after optimizing; if anything
looks wrong or the file does not get smaller, the original is copied instead. Password-
protected and digitally signed PDFs are copied unchanged. Nothing is sent anywhere.

Command line (for scripts or microPDF):
  pdfopt-cli.exe input.pdf [output.pdf] [--scan auto|bw|off] [--grain 0-3] [--ocr]
  pdfopt-cli.exe INPUT_FOLDER OUTPUT_FOLDER [--scan ...] [--grain ...] [--ocr] [--skip-existing]

Your last folders and options are remembered in settings.json next to the exe.
Third-party components and licences: see THIRD-PARTY-NOTICES.txt and _internal\licenses.
