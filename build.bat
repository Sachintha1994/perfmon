@echo off
rem Builds dist\PerfMon\PerfMon.exe and installer\PerfMon-Setup-<version>.exe
setlocal
cd /d "%~dp0"

echo [1/5] Installing build dependencies...
python -m pip install --quiet -r requirements.txt pyinstaller pillow || goto :fail

echo [2/5] Downloading bundled components (LibreHardwareMonitor, PawnIO)...
python packaging\fetch_vendor.py || goto :fail

echo [3/5] Drawing icon...
python packaging\make_icon.py || goto :fail

echo [4/5] Building PerfMon.exe...
python -m PyInstaller --noconfirm --clean --windowed --name PerfMon ^
  --icon packaging\icon.ico --add-data "static;static" ^
  --distpath dist --workpath build server.py || goto :fail

echo [5/5] Building installer...
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo Inno Setup 6 not found. Install it with:  winget install JRSoftware.InnoSetup
  echo The portable app is still available in dist\PerfMon\
  goto :eof
)
"%ISCC%" /Q packaging\PerfMon.iss || goto :fail

echo.
echo Done. Installer: %~dp0installer\
goto :eof

:fail
echo BUILD FAILED
exit /b 1
