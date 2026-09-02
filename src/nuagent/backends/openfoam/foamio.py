"""Minimal, dependency-free readers for OpenFOAM ASCII field and polyMesh files.

Only what the post-processing needs is implemented: ``uniform`` /
``nonuniform List<scalar|vector>`` internal fields, patch ``value`` entries,
and the polyMesh ``points/faces/owner/neighbour/boundary`` files (ASCII).  The
mesh reader computes face centres, face area vectors and cell centres so that
QoIs can be extracted from raw written fields without function objects — this
keeps post-processing identical across OpenFOAM versions and avoids
depending on ParaView at run time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np

_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_COMMENT_LINE = re.compile(r"//[^\n]*")


def strip_comments(text: str) -> str:
    return _COMMENT_LINE.sub("", _COMMENT_BLOCK.sub("", text))


def _parse_list_block(text: str, start: int) -> tuple[np.ndarray, int]:
    """Parse ``N ( ... )`` starting at ``start`` (pointing at N). Returns (array, end_index)."""
    m = re.compile(r"\s*(\d+)\s*\(").match(text, start)
    if not m:
        raise ValueError("expected 'N (' list block")
    n = int(m.group(1))
    body_start = m.end()
    depth, i = 1, body_start
    while depth and i < len(text):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    body = text[body_start : i - 1]
    if n == 0:
        return np.zeros((0,)), i
    numbers = np.array(body.replace("(", " ").replace(")", " ").split(), dtype=float)
    if numbers.size == n:
        return numbers, i
    if numbers.size % n == 0:
        return numbers.reshape(n, -1), i
    raise ValueError(f"list block has {numbers.size} numbers for {n} entries")


def _parse_field_value(text: str, start: int) -> np.ndarray | float | None:
    """Parse ``uniform X;`` / ``uniform (x y z);`` / ``nonuniform List<T> N (...);`` at ``start``."""
    m = re.compile(r"\s*(uniform|nonuniform)\s*").match(text, start)
    if not m:
        return None
    if m.group(1) == "uniform":
        rest = text[m.end() :]
        vm = re.match(r"\(([^)]*)\)", rest)
        if vm:
            return np.array(vm.group(1).split(), dtype=float)
        sm = re.match(r"([-+0-9.eE]+)", rest)
        return float(sm.group(1)) if sm else None
    # 'List<type>' is omitted for zero-length lists, which are written as 'nonuniform 0();'
    lm = re.compile(r"(List<\w+>)?\s*").match(text, m.end())
    arr, _ = _parse_list_block(text, lm.end())
    return arr


@dataclass
class FoamField:
    name: str
    internal: np.ndarray | float | None
    boundary: dict[str, dict[str, str | np.ndarray | float | None]]

    def patch_value(self, patch: str, n_faces: int | None = None) -> np.ndarray:
        entry = self.boundary.get(patch, {})
        val = entry.get("value")
        if val is None:
            raise KeyError(f"patch {patch!r} of field {self.name} has no 'value' entry")
        if isinstance(val, float) or (
            isinstance(val, np.ndarray)
            and val.ndim == 1
            and n_faces
            and val.size != n_faces
            and val.size in (1, 3)
        ):
            n = n_faces or 1
            return np.tile(np.atleast_1d(val), (n, 1)) if np.ndim(val) else np.full(n, val)
        return val

    @property
    def internal_array(self) -> np.ndarray:
        if (
            isinstance(self.internal, np.ndarray)
            and self.internal.ndim >= 1
            and self.internal.shape[0] > 3
        ):
            return self.internal
        raise ValueError(f"field {self.name} has a uniform internal field; cell count unknown")


def read_field(path: Path) -> FoamField:
    text = strip_comments(Path(path).read_text())
    name = Path(path).name
    internal = None
    m = re.search(r"\binternalField\b", text)
    if m:
        internal = _parse_field_value(text, m.end())
    boundary: dict[str, dict] = {}
    bm = re.search(r"\bboundaryField\s*\{", text)
    if bm:
        i = bm.end()
        depth = 1
        # iterate over patch dictionaries at depth 1
        pat = re.compile(r"\s*([\w\".*|()\[\]\-]+)\s*\{")
        while depth and i < len(text):
            pm = pat.match(text, i)
            if not pm:
                break
            pname = pm.group(1).strip('"')
            j = pm.end()
            d = 1
            entry_start = j
            while d and j < len(text):
                if text[j] == "{":
                    d += 1
                elif text[j] == "}":
                    d -= 1
                j += 1
            body = text[entry_start : j - 1]
            entry: dict = {}
            tm = re.search(r"\btype\s+([\w:]+)\s*;", body)
            if tm:
                entry["type"] = tm.group(1)
            vm = re.search(r"\bvalue\b", body)
            if vm:
                entry["value"] = _parse_field_value(body, vm.end())
            gm = re.search(r"\bgradient\b", body)
            if gm:
                entry["gradient"] = _parse_field_value(body, gm.end())
            boundary[pname] = entry
            i = j
            if re.compile(r"\s*\}").match(text, i):
                depth = 0
    return FoamField(name=name, internal=internal, boundary=boundary)


@dataclass
class Patch:
    name: str
    type: str
    n_faces: int
    start_face: int

    @property
    def face_slice(self) -> slice:
        return slice(self.start_face, self.start_face + self.n_faces)


class PolyMesh:
    """Reader for ``constant/polyMesh`` (ASCII)."""

    def __init__(self, mesh_dir: Path) -> None:
        self.dir = Path(mesh_dir)
        self.points = self._read_list("points").reshape(-1, 3)
        self.faces = self._read_faces()
        self.owner = self._read_list("owner").astype(int)
        neigh = self._read_list("neighbour")
        self.neighbour = neigh.astype(int) if neigh.size else np.zeros(0, dtype=int)
        self.patches = self._read_boundary()
        self.n_cells = (
            int(max(self.owner.max(), self.neighbour.max() if self.neighbour.size else -1)) + 1
        )

    # -- raw readers ---------------------------------------------------- #
    def _text(self, name: str) -> str:
        return strip_comments((self.dir / name).read_text())

    def _read_list(self, name: str) -> np.ndarray:
        text = self._text(name)
        # skip header dictionary
        hdr_end = text.find("}") + 1
        m = re.compile(r"\s*(\d+)\s*\(").search(text, hdr_end)
        if not m:
            raise ValueError(f"cannot find list in {name}")
        arr, _ = _parse_list_block(text, m.start())
        return arr

    def _read_faces(self) -> list[np.ndarray]:
        text = self._text("faces")
        hdr_end = text.find("}") + 1
        m = re.compile(r"\s*(\d+)\s*\(").search(text, hdr_end)
        n = int(m.group(1))
        body_start = m.end()
        # each face: k(a b c ...)
        faces = []
        for fm in re.finditer(r"(\d+)\s*\(([^)]*)\)", text[body_start:]):
            faces.append(np.array(fm.group(2).split(), dtype=int))
            if len(faces) == n:
                break
        if len(faces) != n:
            raise ValueError(f"expected {n} faces, parsed {len(faces)}")
        return faces

    def _read_boundary(self) -> dict[str, Patch]:
        text = self._text("boundary")
        hdr_end = text.find("}") + 1
        patches: dict[str, Patch] = {}
        for pm in re.finditer(r"(\w+)\s*\{([^}]*)\}", text[hdr_end:]):
            body = pm.group(2)
            t = re.search(r"\btype\s+(\w+)", body)
            nf = re.search(r"\bnFaces\s+(\d+)", body)
            sf = re.search(r"\bstartFace\s+(\d+)", body)
            if t and nf and sf:
                patches[pm.group(1)] = Patch(
                    pm.group(1), t.group(1), int(nf.group(1)), int(sf.group(1))
                )
        return patches

    # -- geometry ------------------------------------------------------- #
    @cached_property
    def face_centres(self) -> np.ndarray:
        return np.array([self.points[f].mean(axis=0) for f in self.faces])

    @cached_property
    def face_areas(self) -> np.ndarray:
        """Face area vectors (triangle fan about the face centre)."""
        areas = np.zeros((len(self.faces), 3))
        for i, f in enumerate(self.faces):
            pts = self.points[f]
            c = pts.mean(axis=0)
            total = np.zeros(3)
            for k in range(len(pts)):
                total += 0.5 * np.cross(pts[k] - c, pts[(k + 1) % len(pts)] - c)
            areas[i] = total
        return areas

    @cached_property
    def cell_centres(self) -> np.ndarray:
        """Area-weighted mean of face centres (adequate for locating hex cells)."""
        centres = np.zeros((self.n_cells, 3))
        weights = np.zeros(self.n_cells)
        mag = np.linalg.norm(self.face_areas, axis=1)
        for fi, cell in enumerate(self.owner):
            centres[cell] += mag[fi] * self.face_centres[fi]
            weights[cell] += mag[fi]
        for k, cell in enumerate(self.neighbour):
            centres[cell] += mag[k] * self.face_centres[k]
            weights[cell] += mag[k]
        return centres / weights[:, None]

    def patch_face_centres(self, patch: str) -> np.ndarray:
        return self.face_centres[self.patches[patch].face_slice]

    def patch_face_areas(self, patch: str) -> np.ndarray:
        return self.face_areas[self.patches[patch].face_slice]

    def patch_owner_cells(self, patch: str) -> np.ndarray:
        return self.owner[self.patches[patch].face_slice]


def latest_time_dir(case_dir: Path) -> Path:
    """Most recent numeric time directory (excluding 0)."""
    times = []
    for d in Path(case_dir).iterdir():
        if d.is_dir():
            try:
                t = float(d.name)
            except ValueError:
                continue
            if t > 0:
                times.append((t, d))
    if not times:
        raise FileNotFoundError(f"no result time directories in {case_dir}")
    return max(times)[1]
