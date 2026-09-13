# -----------------------------------------------------------------------------
# Role: Provides shared UI smoke test helpers for the image block.
# File Name: ui_smoke_common.py
# Author: Alexandre EL
# Email: alex@hackinvent.com
# Created Date: 2024-10-05
# -----------------------------------------------------------------------------

"""Local import shim for block-owned smoke tests."""

from importlib import util
from pathlib import Path
import sys


def _load_root_common():
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "tests" / "ui_smoke_common.py"
        if candidate.is_file() and candidate.resolve() != current:
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            spec = util.spec_from_file_location("_bloxsmith_root_ui_smoke_common", candidate)
            if spec is None or spec.loader is None:
                break
            module = util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module
    raise RuntimeError("Unable to locate root tests/ui_smoke_common.py")


_root_common = _load_root_common()

for _name, _value in _root_common.__dict__.items():
    if not _name.startswith("_"):
        globals()[_name] = _value
