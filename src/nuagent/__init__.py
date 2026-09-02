"""NuAgent — agentic workflow for verified, validated and calibrated nuclear
thermal-hydraulics (OpenFOAM) and tritium-transport (FESTIM) simulations.

The package is organised in layers so that every layer below the agent can be
used (and tested) without an LLM:

- ``nuagent.spec``          typed simulation specifications (Pydantic)
- ``nuagent.physics``       correlations, analytical solutions, reduced-order models
- ``nuagent.verification``  Richardson extrapolation / GCI, error metrics
- ``nuagent.backends``      solver backends (OpenFOAM, FESTIM, mock)
- ``nuagent.executors``     local / Docker / SLURM execution
- ``nuagent.calibration``   Bayesian calibration (emcee) and surrogates
- ``nuagent.uq``            sampling and Sobol sensitivity analysis
- ``nuagent.reporting``     Markdown report + provenance
- ``nuagent.agent``         the LangGraph workflow that ties it all together
"""

from importlib import metadata

try:
    __version__ = metadata.version("nuagent")
except metadata.PackageNotFoundError:  # pragma: no cover - source checkout
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
