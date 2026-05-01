# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec para empacotar a NBA Analysis API como executável único.

Gera:
  Windows : dist/nba-api.exe
  Linux   : dist/nba-api
  macOS   : dist/nba-api

Como usar
---------
  pip install pyinstaller
  pyinstaller nba-api.spec

Ou via script do desktop:
  node ../nba-analyst-desktop/scripts/build-backend.js
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH)  # diretório deste .spec (raiz do backend)

a = Analysis(
    # Ponto de entrada: módulo run que chama uvicorn programaticamente
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Inclui todo o pacote src/
        (str(ROOT / "src"), "src"),
    ],
    hiddenimports=[
        # FastAPI / Starlette
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # nba_api
        "nba_api",
        "nba_api.live",
        "nba_api.live.nba",
        "nba_api.live.nba.endpoints",
        "nba_api.live.nba.endpoints.boxscore",
        "nba_api.live.nba.endpoints.scoreboard",
        "nba_api.stats",
        "nba_api.stats.endpoints",
        # Pandas / numpy internals comuns
        "pandas",
        "numpy",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="nba-api",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # mantém console para logs
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
