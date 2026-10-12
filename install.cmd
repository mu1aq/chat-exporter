@echo off
rem Install dependencies into a local .venv (Windows).
rem After this finishes, run the tool with:  .venv\Scripts\python chat2file.py <share-url>
setlocal
set "PROJECT_DIR=%~dp0"

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "BOOTSTRAP=py -3"
    goto have_python
)
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "BOOTSTRAP=python"
    goto have_python
)
echo Python was not found. Install Python 3.10 or newer. 1>&2
exit /b 9009

:have_python
set "VENV_PY=%PROJECT_DIR%.venv\Scripts\python.exe"
if not exist "%VENV_PY%" %BOOTSTRAP% -m venv "%PROJECT_DIR%.venv"

"%VENV_PY%" -m pip install --upgrade pip
"%VENV_PY%" -m pip install -e "%PROJECT_DIR%[browser]"
"%VENV_PY%" -m playwright install chromium

echo Done. Run:  "%VENV_PY%" "%PROJECT_DIR%chat2file.py" ^<share-url^>
exit /b %ERRORLEVEL%
