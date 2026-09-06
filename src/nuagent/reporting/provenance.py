"""Provenance capture: enough to reproduce a run and audit the agent's decisions."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path
from typing import Any


def _git(cmd: list[str], cwd: Path | None = None) -> str | None:
    try:
        return subprocess.run(
            ["git", *cmd], cwd=cwd, capture_output=True, text=True, check=True, timeout=5
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def _git_state(repo: Path) -> dict[str, Any]:
    """Commit and working-tree state, only when ``repo`` really is the nuagent checkout.

    ``git rev-parse`` walks up the directory tree, so an installed (non-editable) copy would
    otherwise stamp results with the HEAD of whatever unrelated repository encloses site-packages.
    """
    top = _git(["rev-parse", "--show-toplevel"], repo)
    if top is None or Path(top).resolve() != repo.resolve():
        return {"commit": None, "dirty": None, "note": "not a nuagent git checkout"}
    porcelain = _git(["status", "--porcelain"], repo)
    return {
        "commit": _git(["rev-parse", "HEAD"], repo),
        "dirty": None if porcelain is None else bool(porcelain),
    }


def _pkg_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _openfoam_version() -> str | None:
    if os.environ.get("WM_PROJECT_VERSION"):
        return os.environ["WM_PROJECT_VERSION"]
    for rc in ("/usr/lib/openfoam", "/opt", "/usr/share/openfoam"):
        p = Path(rc)
        if p.exists():
            hits = sorted(str(x) for x in p.glob("openfoam*"))
            if hits:
                return Path(hits[-1]).name
    return None


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def collect_provenance(
    workdir: Path, spec: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    repo = Path(__file__).resolve().parents[3]
    inputs = {}
    root = Path(workdir)
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        try:
            rel = f.relative_to(root)
        except ValueError:  # pragma: no cover - rglob results are always under root
            continue
        # Note the explicit grouping: without it, `and` binds tighter than `or` and the
        # `is_file()` guard would not apply to the spec.yaml branch.  The directory test is made
        # against the *relative* path so that an absolute workdir containing e.g. "attempt"
        # cannot change which files are digested; grid levels and ensemble members are included
        # because their values are what the GCI and the model-form band are computed from.
        in_run_dir = any(
            p.startswith(("attempt", "verify_", "model_form_")) for p in rel.parts[:-1]
        )
        if (f.suffix in (".yaml", ".json") and in_run_dir) or rel.name == "spec.yaml":
            try:
                inputs[str(rel)] = file_digest(f)
            except OSError:
                pass
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "nuagent_version": _pkg_version("nuagent"),
        # ``dirty`` is tri-state on purpose: ``None`` means the working-tree state could not be
        # determined (no git, not a checkout, timeout).  Reporting ``false`` there would be a
        # positive claim of a clean tree made from no information.
        "git": _git_state(repo),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "hostname": platform.node(),
        "packages": {
            p: _pkg_version(p)
            for p in ("langgraph", "langchain-core", "numpy", "scipy", "emcee", "SALib", "pydantic")
        },
        "solvers": {
            "openfoam": _openfoam_version(),
            "festim": _pkg_version("FESTIM"),
            "mpirun": shutil.which("mpirun"),
        },
        "llm_model": os.environ.get("NUAGENT_LLM_MODEL"),
        "spec_sha256": hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16],
        "input_digests": inputs,
        "attempts": state.get("attempt"),
        "adjustments": state.get("adjustments", {}),
        "n_decisions": len(state.get("decisions", [])),
    }
