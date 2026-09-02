"""Typed simulation specifications.

A :class:`SimulationSpec` is the *contract* between the planning agent and the
deterministic machinery below it.  The LLM (when used) only ever produces a
``SimulationSpec``; it never writes solver input files directly.  Every field
is validated, bounded and documented so that the schema doubles as the prompt
for structured output.

The spec is intentionally solver-agnostic: the same ``HeatedPipeCase`` can be
built by the OpenFOAM backend or by the analytical ``mock`` backend used in CI.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class FlowRegime(str, Enum):
    LAMINAR = "laminar"
    TRANSITIONAL = "transitional"
    TURBULENT = "turbulent"


class TurbulenceModel(str, Enum):
    LAMINAR = "laminar"
    K_OMEGA_SST = "kOmegaSST"
    K_EPSILON = "kEpsilon"


class WallTreatment(str, Enum):
    RESOLVED = "resolved"  # y+ ~ 1, low-Re integration to the wall
    WALL_FUNCTION = "wall_function"  # y+ ~ 30-100, log-law wall functions


class ExecutorKind(str, Enum):
    LOCAL = "local"
    DOCKER = "docker"
    SLURM = "slurm"


class BackendKind(str, Enum):
    OPENFOAM = "openfoam"
    FESTIM = "festim"
    MOCK = "mock"


# --------------------------------------------------------------------------- #
# Material / fluid properties
# --------------------------------------------------------------------------- #


class FluidProperties(BaseModel):
    """Constant thermophysical properties of the coolant (SI units)."""

    name: str = Field("water_300K", description="Human readable name of the fluid preset")
    rho: float = Field(996.0, gt=0, description="Density [kg/m^3]")
    mu: float = Field(8.5e-4, gt=0, description="Dynamic viscosity [Pa s]")
    cp: float = Field(4180.0, gt=0, description="Specific heat capacity [J/kg/K]")
    k: float = Field(0.61, gt=0, description="Thermal conductivity [W/m/K]")
    mol_weight: float = Field(
        18.0, gt=0, description="Molar mass [g/mol] (needed by OpenFOAM thermo)"
    )

    @property
    def nu(self) -> float:
        """Kinematic viscosity [m^2/s]."""
        return self.mu / self.rho

    @property
    def pr(self) -> float:
        """Prandtl number."""
        return self.mu * self.cp / self.k

    @property
    def alpha(self) -> float:
        """Thermal diffusivity [m^2/s]."""
        return self.k / (self.rho * self.cp)


FLUID_PRESETS: dict[str, FluidProperties] = {
    "water_300K": FluidProperties(
        name="water_300K", rho=996.0, mu=8.5e-4, cp=4180.0, k=0.61, mol_weight=18.0
    ),
    "water_550K": FluidProperties(
        name="water_550K", rho=760.0, mu=9.7e-5, cp=5000.0, k=0.60, mol_weight=18.0
    ),
    "air_300K": FluidProperties(
        name="air_300K", rho=1.16, mu=1.85e-5, cp=1007.0, k=0.0263, mol_weight=28.96
    ),
    # Synthetic unit-Prandtl liquid: keeps laminar thermal entry lengths short for verification
    "unit_prandtl_liquid": FluidProperties(
        name="unit_prandtl_liquid", rho=1000.0, mu=1.0e-3, cp=4180.0, k=4.18, mol_weight=18.0
    ),
    # Liquid metals relevant to fast reactors / fusion blankets (order-of-magnitude constants)
    "sodium_700K": FluidProperties(
        name="sodium_700K", rho=850.0, mu=2.6e-4, cp=1270.0, k=68.0, mol_weight=23.0
    ),
    "PbLi_600K": FluidProperties(
        name="PbLi_600K", rho=9600.0, mu=1.8e-3, cp=190.0, k=18.0, mol_weight=200.0
    ),
}


class TrapSpec(BaseModel):
    """McNabb–Foster trap (single level) for hydrogen-isotope transport."""

    name: str = "trap1"
    k_0: float = Field(..., gt=0, description="Trapping rate pre-exponential [m^3/s]")
    E_k: float = Field(..., ge=0, description="Trapping activation energy [eV]")
    p_0: float = Field(..., gt=0, description="Detrapping rate pre-exponential [1/s]")
    E_p: float = Field(..., ge=0, description="Detrapping energy [eV]")
    n: float = Field(..., gt=0, description="Trap site density [1/m^3]")


class HydrogenMaterial(BaseModel):
    """Arrhenius diffusion and solubility for a hydrogen-isotope host material."""

    name: str = Field("tungsten", description="Material name")
    D_0: float = Field(1.9e-7, gt=0, description="Diffusivity pre-exponential [m^2/s]")
    E_D: float = Field(0.2, ge=0, description="Diffusion activation energy [eV]")
    K_S_0: float | None = Field(
        None, description="Sieverts solubility pre-exponential [1/m^3/Pa^0.5]"
    )
    E_K_S: float | None = Field(None, description="Solubility activation energy [eV]")


HYDROGEN_MATERIAL_PRESETS: dict[str, HydrogenMaterial] = {
    # Frauenfelder (1969) tungsten diffusivity; commonly used in FESTIM examples
    "tungsten": HydrogenMaterial(name="tungsten", D_0=4.1e-7, E_D=0.39, K_S_0=1.87e24, E_K_S=1.04),
    # EUROFER97 (Aiello et al. 2002)
    "eurofer97": HydrogenMaterial(name="eurofer97", D_0=1.5e-7, E_D=0.15, K_S_0=1.0e23, E_K_S=0.27),
    # 316L stainless steel (Grant et al. 1987)
    "ss316L": HydrogenMaterial(name="ss316L", D_0=3.7e-7, E_D=0.55, K_S_0=1.4e23, E_K_S=0.14),
}


# --------------------------------------------------------------------------- #
# Case definitions (discriminated union on ``kind``)
# --------------------------------------------------------------------------- #


class MeshSpec(BaseModel):
    """Structured-mesh controls for the axisymmetric pipe."""

    n_radial: int = Field(40, ge=4, le=400, description="Cells across the radius")
    cells_per_diameter: float = Field(
        10.0, gt=0, le=200, description="Axial cells per pipe diameter"
    )
    target_yplus: float = Field(
        1.0, gt=0, description="Target y+ of the wall-adjacent cell (turbulent, resolved)"
    )
    wedge_angle_deg: float = Field(
        2.5, gt=0, lt=10, description="Half-opening angle of the wedge [deg]"
    )
    max_cells: int = Field(2_000_000, gt=0, description="Safety budget on the total cell count")


class NumericsSpec(BaseModel):
    """Solver numerics that the diagnostician agent is *allowed* to adjust."""

    max_iterations: int = Field(3000, ge=10, le=100_000)
    residual_target: float = Field(1e-5, gt=0, lt=1)
    relax_U: float = Field(0.7, gt=0, le=1)
    relax_p: float = Field(0.3, gt=0, le=1)
    relax_h: float = Field(0.7, gt=0, le=1)
    relax_turbulence: float = Field(0.7, gt=0, le=1)
    div_scheme: Literal["upwind", "linearUpwind", "limitedLinear"] = "linearUpwind"
    n_non_orthogonal_correctors: int = Field(0, ge=0, le=5)
    write_interval: int = Field(500, ge=1)


class HeatedPipeCase(BaseModel):
    """Steady, constant-property flow in a uniformly heated circular pipe.

    This is the canonical coolant-channel problem: the fully developed Nusselt
    number and Darcy friction factor have exact laminar solutions and
    well-characterised turbulent correlations (Gnielinski, Petukhov), which
    makes it ideal for automated verification and validation.
    """

    kind: Literal["heated_pipe"] = "heated_pipe"
    fluid: FluidProperties = Field(default_factory=lambda: FLUID_PRESETS["water_300K"])
    diameter: float = Field(0.02, gt=0, description="Pipe inner diameter [m]")
    length_over_diameter: float = Field(40.0, gt=0, le=500, description="Pipe length in diameters")
    reynolds: float = Field(..., gt=0, description="Bulk Reynolds number based on diameter")
    inlet_temperature: float = Field(300.0, gt=0, description="Inlet bulk temperature [K]")
    wall_heat_flux: float = Field(
        1.0e4, description="Uniform wall heat flux [W/m^2] (positive = heating)"
    )
    turbulence_model: TurbulenceModel = Field(
        TurbulenceModel.K_OMEGA_SST,
        description="Turbulence closure; use 'laminar' for Re < 2300",
    )
    wall_treatment: WallTreatment = WallTreatment.RESOLVED
    turbulent_prandtl: float = Field(
        0.85, gt=0, description="Turbulent Prandtl number for the alphat wall function"
    )
    inlet_turbulence_intensity: float = Field(0.05, gt=0, lt=1)
    mesh: MeshSpec = Field(default_factory=MeshSpec)
    numerics: NumericsSpec = Field(default_factory=NumericsSpec)
    developed_fraction: float = Field(
        0.25,
        gt=0,
        lt=1,
        description="Fraction of the pipe length (from the outlet) treated as fully developed",
    )

    @property
    def length(self) -> float:
        return self.length_over_diameter * self.diameter

    @property
    def inlet_velocity(self) -> float:
        return self.reynolds * self.fluid.mu / (self.fluid.rho * self.diameter)

    @property
    def regime(self) -> FlowRegime:
        if self.reynolds < 2300:
            return FlowRegime.LAMINAR
        if self.reynolds < 4000:
            return FlowRegime.TRANSITIONAL
        return FlowRegime.TURBULENT

    @model_validator(mode="after")
    def _consistent_turbulence(self) -> HeatedPipeCase:
        if (
            self.regime is FlowRegime.LAMINAR
            and self.turbulence_model is not TurbulenceModel.LAMINAR
        ):
            # Do not silently "fix"; the planner must make the physics choice explicit.
            raise ValueError(
                f"Re={self.reynolds:.0f} is laminar but turbulence_model={self.turbulence_model.value}; "
                "set turbulence_model='laminar'"
            )
        if self.regime is FlowRegime.TURBULENT and self.turbulence_model is TurbulenceModel.LAMINAR:
            raise ValueError(
                f"Re={self.reynolds:.0f} is turbulent; a laminar model is not appropriate"
            )
        return self


class PermeationCase(BaseModel):
    """Transient hydrogen-isotope permeation through a 1-D slab (FESTIM).

    Upstream face held at a fixed mobile concentration, downstream face at
    zero, initially empty.  The downstream flux has a closed-form series
    solution (see :func:`nuagent.physics.analytical.permeation_flux`), and
    with a single trap in local equilibrium an effective-diffusivity solution
    (Oriani) — both are used for verification.
    """

    kind: Literal["permeation"] = "permeation"
    material: HydrogenMaterial = Field(
        default_factory=lambda: HYDROGEN_MATERIAL_PRESETS["tungsten"]
    )
    thickness: float = Field(1.0e-3, gt=0, description="Slab thickness [m]")
    temperature: float = Field(600.0, gt=0, description="Uniform temperature [K]")
    upstream_concentration: float = Field(
        1.0e20, gt=0, description="Mobile concentration at x=0 [1/m^3]"
    )
    traps: list[TrapSpec] = Field(default_factory=list)
    n_cells: int = Field(200, ge=10, le=100_000)
    final_time: float | None = Field(
        None, gt=0, description="End time [s]; default = 6 x diffusion time L^2/D"
    )
    n_steps: int = Field(400, ge=10, le=1_000_000, description="Number of (uniform) time steps")


class TDSCase(BaseModel):
    """Thermal desorption spectroscopy: load, rest, then linear temperature ramp."""

    kind: Literal["tds"] = "tds"
    material: HydrogenMaterial = Field(
        default_factory=lambda: HYDROGEN_MATERIAL_PRESETS["tungsten"]
    )
    thickness: float = Field(1.0e-3, gt=0)
    traps: list[TrapSpec]
    implantation_flux: float = Field(1.0e20, gt=0, description="Implanted particle flux [1/m^2/s]")
    implantation_range: float = Field(3.0e-9, gt=0, description="Implantation depth [m]")
    implantation_width: float = Field(1.0e-9, gt=0, description="Gaussian width of the source [m]")
    implantation_time: float = Field(400.0, gt=0)
    implantation_temperature: float = Field(300.0, gt=0)
    rest_time: float = Field(50.0, ge=0)
    ramp_rate: float = Field(8.0, gt=0, description="Heating rate [K/s]")
    final_temperature: float = Field(1000.0, gt=0)
    n_cells: int = Field(500, ge=10, le=100_000)


CaseSpec = Annotated[HeatedPipeCase | PermeationCase | TDSCase, Field(discriminator="kind")]


# --------------------------------------------------------------------------- #
# V&V, calibration, UQ and execution controls
# --------------------------------------------------------------------------- #


class ReferenceSpec(BaseModel):
    """A reference solution the result must be compared against."""

    quantity: str = Field(
        ..., description="QoI name, e.g. 'Nu', 'f', 'permeation_flux_ss', 'time_lag'"
    )
    source: str = Field(
        ...,
        description=(
            "'analytical', or a correlation/dataset name: 'gnielinski', 'dittus_boelter', "
            "'petukhov', 'blasius', 'laminar', or 'dataset:<path>'"
        ),
    )
    tolerance: float = Field(
        0.10, gt=0, description="Acceptable relative deviation, e.g. 0.10 = 10 %"
    )


class VerificationSpec(BaseModel):
    mesh_study: bool = Field(True, description="Run a 3-level grid-refinement study with GCI")
    refinement_ratio: float = Field(2.0, gt=1)
    n_levels: int = Field(3, ge=2, le=5)
    require_asymptotic: bool = Field(
        False, description="Fail verification if observed order < 0.5 or oscillatory"
    )


class ValidationSpec(BaseModel):
    references: list[ReferenceSpec] = Field(default_factory=list)


class ParameterPrior(BaseModel):
    name: str
    low: float
    high: float
    log_scale: bool = Field(False, description="Sample log10(value) uniformly")


class CalibrationSpec(BaseModel):
    """Bayesian calibration of model parameters against observed data."""

    parameters: list[ParameterPrior]
    dataset: str = Field(..., description="CSV with columns x,y[,sigma] or 'synthetic'")
    noise_sigma: float | None = Field(None, gt=0, description="Observation noise if not in dataset")
    n_walkers: int = Field(32, ge=8)
    n_steps: int = Field(2000, ge=100)
    burn_in: int = Field(500, ge=0)
    surrogate: Literal["none", "gp"] = Field(
        "none", description="Use a GP surrogate instead of the full model"
    )
    surrogate_samples: int = Field(64, ge=8)


class UQSpec(BaseModel):
    parameters: list[ParameterPrior]
    n_samples: int = Field(
        256, ge=16, description="Base sample size for Saltelli (total = N*(2D+2))"
    )
    qois: list[str] = Field(default_factory=list)


class ExecutionSpec(BaseModel):
    executor: ExecutorKind = ExecutorKind.LOCAL
    n_procs: int = Field(1, ge=1, le=4096)
    max_attempts: int = Field(
        3, ge=1, le=10, description="Diagnose-and-retry budget for non-converged runs"
    )
    wallclock_minutes: int = Field(60, ge=1)
    require_approval: bool = Field(
        False, description="Pause for human approval before submitting HPC jobs"
    )
    slurm_partition: str | None = None
    slurm_account: str | None = None
    docker_image: str | None = None


class SimulationSpec(BaseModel):
    """Top-level task specification consumed by the workflow."""

    name: str = Field(
        ..., pattern=r"^[A-Za-z0-9_\-]+$", description="Short identifier used for directories"
    )
    description: str = Field("", description="Free-text description of the engineering question")
    backend: BackendKind = BackendKind.OPENFOAM
    case: CaseSpec
    verification: VerificationSpec = Field(default_factory=VerificationSpec)
    validation: ValidationSpec = Field(default_factory=ValidationSpec)
    calibration: CalibrationSpec | None = None
    uq: UQSpec | None = None
    execution: ExecutionSpec = Field(default_factory=ExecutionSpec)

    @model_validator(mode="after")
    def _backend_matches_case(self) -> SimulationSpec:
        cfd = isinstance(self.case, HeatedPipeCase)
        if self.backend is BackendKind.OPENFOAM and not cfd:
            raise ValueError("backend 'openfoam' only supports CFD cases (heated_pipe)")
        if self.backend is BackendKind.FESTIM and cfd:
            raise ValueError(
                "backend 'festim' only supports hydrogen-transport cases (permeation, tds)"
            )
        return self

    # Convenience -----------------------------------------------------------
    @classmethod
    def from_yaml(cls, path) -> SimulationSpec:
        import yaml

        with open(path) as fh:
            return cls.model_validate(yaml.safe_load(fh))

    def to_yaml(self, path) -> None:
        import yaml

        with open(path, "w") as fh:
            yaml.safe_dump(self.model_dump(mode="json"), fh, sort_keys=False)
