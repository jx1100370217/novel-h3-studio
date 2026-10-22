"""Canonical repository paths — single source of truth.

The projects root is the most load-bearing path in the system: checkpoints
are written under it, tool events are attributed against it, and the Backlot
board watches it. Define it once.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Monorepo layout: when OpenMontage lives in <host>/openmontage/ next to the
# host's model backend (novel_h3/), the production workspace is the host's
# projects/ directory. Standalone checkouts keep the original behaviour.
_HOST_ROOT = REPO_ROOT.parent if (REPO_ROOT.parent / "novel_h3").is_dir() else REPO_ROOT
_DEFAULT_PROJECTS = _HOST_ROOT / "projects"

# Overridable for staging/screenshots/tests. Everything — checkpoint writes,
# event attribution, the Backlot board — follows the same root.
PROJECTS_DIR = Path(os.environ.get("OPENMONTAGE_PROJECTS_DIR") or _DEFAULT_PROJECTS)
