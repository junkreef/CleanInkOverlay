@echo off
rem CleanInkOverlay (release package): starts the web UI at http://127.0.0.1:8000 and opens it in the browser.
rem Recording is started from the page; CleanInkOverlay_live.bat starts it right away. Options go to app.launch.
rem Keep this file ASCII-only: cmd mis-parses batch files with other characters, depending on the code page.
setlocal
cd /d "%~dp0"
if not exist "runtime\python\python.exe" goto not_unpacked
"runtime\python\python.exe" -X utf8 -m app.launch %*
if errorlevel 1 pause
exit /b

:not_unpacked
rem A double-click inside the zip preview runs this file alone from a temporary folder. The message says (in Japanese):
rem "Extract the whole zip first, then run CleanInkOverlay.bat in the extracted folder."
powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; [void][System.Windows.MessageBox]::Show([regex]::Unescape('zip \u3092\u3059\u3079\u3066\u5c55\u958b\u3057\u3066\u304b\u3089\u3001\u5c55\u958b\u3057\u305f\u30d5\u30a9\u30eb\u30c0\u30fc\u306e\u4e2d\u306e CleanInkOverlay.bat \u3092\u5b9f\u884c\u3057\u3066\u304f\u3060\u3055\u3044\u3002\u000a\u000a\u0028zip \u306e\u4e2d\u306e\u30d5\u30a1\u30a4\u30eb\u3092\u76f4\u63a5\u30c0\u30d6\u30eb\u30af\u30ea\u30c3\u30af\u3057\u3066\u3082\u52d5\u304d\u307e\u305b\u3093\u0029'), 'CleanInkOverlay')"
exit /b 1
