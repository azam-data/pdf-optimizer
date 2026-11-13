@echo off
rem Build the portable app on Windows (Python 3.12 x64 with tkinter).
cd /d "%~dp0"
python -m pip install --user -r requirements-build.txt || goto :err
if not exist third_party\tessdata\eng.traineddata (
  mkdir third_party\tessdata 2>nul
  powershell -NoProfile -Command "Invoke-WebRequest https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata -OutFile third_party/tessdata/eng.traineddata" || goto :err
)
if not exist third_party\vcruntime\msvcp140.dll (
  mkdir third_party\vcruntime 2>nul
  copy /y %SystemRoot%\System32\msvcp140.dll third_party\vcruntime\ >nul || goto :err
  copy /y %SystemRoot%\System32\vcruntime140.dll third_party\vcruntime\ >nul || goto :err
  copy /y %SystemRoot%\System32\vcruntime140_1.dll third_party\vcruntime\ >nul || goto :err
)
python -m PyInstaller --noconfirm --clean pdf_optimizer.spec || goto :err
copy /y APP_README.txt "dist\PDF Optimizer\README.txt" >nul
copy /y THIRD-PARTY-NOTICES.txt "dist\PDF Optimizer\" >nul
echo.
echo Done: dist\PDF Optimizer
goto :eof
:err
echo Build failed.
exit /b 1
