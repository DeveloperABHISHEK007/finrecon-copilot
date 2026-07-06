"""
Shared helper: make the docs PDF scripts runnable from ANY Python interpreter.

The project's dependencies (fpdf2, pandas, ...) live in ./.venv. If a script is
launched with a Python that lacks them, ensure_venv() transparently re-launches
it under the venv interpreter (via subprocess - reliable on Windows, unlike
os.execv). Call it BEFORE importing fpdf / pandas.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_venv(probe: str = "fpdf") -> None:
    try:
        __import__(probe)
        return  # dependency already available - nothing to do
    except ModuleNotFoundError:
        pass

    root = Path(__file__).resolve().parents[1]
    venv_py = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if venv_py.exists() and Path(sys.executable).resolve() != venv_py.resolve():
        import subprocess
        print(f"[docs] using project venv: {venv_py}", flush=True)
        sys.exit(subprocess.run([str(venv_py), sys.argv[0], *sys.argv[1:]]).returncode)

    print(
        "\n[docs] Project dependencies are not installed in this interpreter.\n"
        "       Set up the venv once, then re-run:\n"
        "         python -m venv .venv\n"
        "         .venv\\Scripts\\python -m pip install -r requirements.txt\n"
    )
    raise SystemExit(1)
