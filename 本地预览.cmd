@echo off
setlocal
set "LISTENOTE_DATA=%~dp0.test-data\preview"
set "LISTENOTE_DISABLE_UPDATE_CHECK=1"
start "" /D "%~dp0" "%~dp0.preview\Listenote\runtime\pythonw.exe" "%~dp0Listenote\app\startup.py" --local-preview --no-update-check
endlocal
