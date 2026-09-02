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
    for f in sorted(Path(workdir).rglob("*")):
        if (
            f.is_file()
            and f.suffix in (".yaml", ".json")
            and "attempt" in str(f.parent)
            or f.name in ("spec.yaml",)
        ):
            try:
                inputs[str(f.relative_to(workdir))] = file_digest(f)
            except OSError:
                pass
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "nuagent_version": _pkg_version("nuagent"),
        "git": {
            "commit": _git(["rev-parse", "HEAD"], repo),
            "dirty": bool(_git(["status", "--porcelain"], repo)),
        },
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
