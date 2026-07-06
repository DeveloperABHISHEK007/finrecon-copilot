@echo off
REM FinRecon Copilot - double-click or run `run.bat` to launch the full pipeline.
REM Uses the project's virtual environment automatically.
setlocal
set "HERE=%~dp0"
if exist "%HERE%.venv\Scripts\python.exe" (
    "%HERE%.venv\Scripts\python.exe" "%HERE%run.py" %*
) else (
    echo [run] .venv not found. Create it first:
    echo     python -m venv .venv
    echo     .venv\Scripts\python -m pip install -r requirements.txt
    exit /b 1
)
