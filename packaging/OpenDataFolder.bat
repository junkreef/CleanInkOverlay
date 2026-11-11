@echo off
rem Opens the folder that holds the records, the saved screens, the settings and the logs (see app.launch).
setlocal
set "HOME_DIR=%LOCALAPPDATA%\CleanInkOverlay"
if defined CLEANINK_HOME set "HOME_DIR=%CLEANINK_HOME%"
if not exist "%HOME_DIR%" mkdir "%HOME_DIR%"
start "" "%HOME_DIR%"
