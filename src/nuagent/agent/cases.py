"""Idempotent case reuse: recognise a case directory built from an identical specification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nuagent.backends.base import CaseHandle, spec_hash
from nuagent.spec import SimulationSpec


def reusable_case(
    case_dir: Path,
    spec: SimulationSpec,
    adjustments: dict[str, Any] | None,
    refinement: float = 1.0,
) -> CaseHandle | None:
    """Return the existing case in ``case_dir`` if it was built from this exact spec and has run."""
    meta = Path(case_dir) / "nuagent_case.json"
    if not meta.exists():
        return None
    try:
        d = json.loads(meta.read_text())
        case = CaseHandle.from_dict(d["case"])
    except Exception:  # noqa: BLE001
        return None
    expected = spec_hash(spec, {"refinement": refinement, "adjustments": adjustments or {}})
    if case.spec_hash != expected:
        return None
    log = case.path / case.metadata.get("log", "log.run")
    return case if log.exists() else None
