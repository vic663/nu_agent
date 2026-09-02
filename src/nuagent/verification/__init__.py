"""Solution verification: grid-convergence studies and error metrics."""

from nuagent.verification.gci import (
    GridConvergenceResult,
    grid_convergence_index,
    relative_error,
    richardson_extrapolation,
)

__all__ = [
    "GridConvergenceResult",
    "grid_convergence_index",
    "relative_error",
    "richardson_extrapolation",
]
