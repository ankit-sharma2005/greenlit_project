"""Make the experiment packages importable from the tests without installation."""

from __future__ import annotations

import sys
from pathlib import Path

EXPERIMENTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EXPERIMENTS))
sys.path.insert(0, str(EXPERIMENTS / "apps"))
sys.path.insert(0, str(EXPERIMENTS / "runner"))
sys.path.insert(0, str(EXPERIMENTS / "analysis"))
