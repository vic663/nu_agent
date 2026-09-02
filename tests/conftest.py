import shutil
from pathlib import Path

import pytest

from nuagent.backends.openfoam.backend import find_foam_bashrc

FIXTURES = Path(__file__).parent / "fixtures"


def openfoam_available() -> bool:
    return shutil.which("blockMesh") is not None or find_foam_bashrc() is not None


def festim_available() -> bool:
    try:
        import festim  # noqa: F401

        return True
    except Exception:
        return False


requires_openfoam = pytest.mark.skipif(not openfoam_available(), reason="OpenFOAM not installed")
requires_festim = pytest.mark.skipif(not festim_available(), reason="FESTIM/dolfinx not installed")


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
