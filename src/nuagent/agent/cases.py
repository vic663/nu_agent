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
    backend: Any = None,
) -> CaseHandle | None:
    """Return the existing case in ``case_dir`` only if it is safe to re-report its numbers.

    Three conditions, all necessary:

    1. the specification hash matches — and that hash now includes
       :func:`~nuagent.backends.base.generator_fingerprint`, so a case built by different template
       code or a different NuAgent version is *not* reused;
    2. the run log exists;
    3. when ``backend`` is given, the log parses as **converged**.  Without (3) a directory left by
       a crashed or interrupted run is silently adopted and a synthetic ``rc=0`` recorded for it.
    """
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
    if not log.exists():
        return None
    if backend is not None:
        try:
            if not backend.parse_log(case).converged:
                return None
        except Exception:  # noqa: BLE001 - an unparseable log is not a reusable result
            return None
    return case
