@echo off
REM ===========================================================================
REM  AutoFactorio launcher
REM  Forces the project's own .venv interpreter (double-clicking run.py would
REM  otherwise run under the base Python with no pygame and flash shut).
REM  Creates the venv + installs deps on first run. Pauses on error so the
REM  traceback stays readable.
REM ===========================================================================
setlocal
cd /d "%~dp0"
set "PYEXE=%~dp0.venv\Scripts\python.exe"

if not exist "%PYEXE%" (
    echo [AutoFactorio] First run: creating virtual environment...
    py -3.14 -m venv .venv 2>nul || py -m venv .venv || python -m venv .venv
    if not exist "%PYEXE%" (
        echo [AutoFactorio] ERROR: could not create the .venv. Is Python installed?
        pause
        exit /b 1
    )
    echo [AutoFactorio] Installing dependencies...
    "%PYEXE%" -m pip install --upgrade pip
    "%PYEXE%" -m pip install -r requirements.txt
)

"%PYEXE%" run.py %*
set "RC=%errorlevel%"
if not "%RC%"=="0" (
    echo.
    echo [AutoFactorio] exited with code %RC%. See the traceback above.
    pause
)
endlocal
