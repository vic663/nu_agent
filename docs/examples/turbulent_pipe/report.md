# NuAgent report — `pipe-turbulent-Re20k`

**Status:** SUCCESS  &nbsp;|&nbsp; **Backend:** openfoam &nbsp;|&nbsp; **Case:** heated_pipe &nbsp;|&nbsp; **Generated:** 2026-09-02T05:25:47+0000

> Turbulent forced convection of water in a 20 mm pipe at Re = 20 000 with 50 kW/m2 uniform wall heat flux. Validates the fully developed Nusselt number against Gnielinski (+-10 %) and the friction factor against Petukhov.



## 1. Problem definition

| Parameter | Value |
|---|---|
| Fluid | water_300K (ρ=996.0 kg/m³, μ=0.00085 Pa·s, Pr=5.82) |
| Diameter / length | 0.02 m / 0.8 m (L/D = 40.0) |
| Reynolds number | 2e+04 (turbulent); U_in = 0.8534 m/s |
| Wall heat flux | 5e+04 W/m²; T_in = 300.0 K |
| Turbulence model | kOmegaSST, wall treatment: resolved, Pr_t = 0.85 |
| Base mesh | 40 radial × 10.0 cells/D, target y+ = 1.0 |
| Numerics | linearUpwind, relax U/p/h = 0.7/0.3/0.7, target residual 1e-05 |
| Execution | local, 1 proc(s), max 3 attempt(s) |


## 2. Run summary

| Item | Value |
|---|---|
| Attempts | 1 |
| Final numerics adjustments | `none` |
| Convergence | all tracked residuals below 1e-05 at iteration 823 (worst h=4.21e-06; ignored: Uz) |
| Iterations / steps | 823 |
| Final residuals | Ux=1.0e-09, Uy=1.4e-08, Uz=2.3e-05, h=4.2e-06, p_rgh=1.0e-08, omega=7.5e-10, k=1.5e-09 |
| Wall time | 65.5 s (local) |

![residuals](figures/residuals.png)


## 3. Quantities of interest

| QoI | Value |
|---|---|
| Nu | 124.59 |
| Nu_std_developed | 0.34179 |
| f | 0.024163 |
| f_dp | 0.024163 |
| f_tau | 0.02463 |
| Re | 20000 |
| Pr | 5.8246 |
| T_wall_outlet | 315.34 |
| dp_per_length | 438.19 |
| n_cells | 16000 |


**Consistency checks**

| Check | Value |
|---|---|
| tau_wall_developed | 2.2334 |
| friction_factor_consistency | -0.018999 |
| yplus_avg_estimate | 0.96796 |
| mass_balance_error | -0.0012688 |
| outlet_bulk_temperature | 302.25 |
| energy_balance_error | -0.0012036 |

- wall shear stress from near-wall velocity gradient (first-order estimate)
- friction factor 'f' taken from dp/dx; f_tau uses near-wall velocity gradient (first-order estimate)


![profiles](figures/profiles.png)


## 4. Solution verification



**Grid-refinement study** (refinement ratio 2.0, 3 levels)

| Level | h [m] | cells | Nu | f | 
|---|---|---|---|---|
| r=1 | 7.071e-04 | 16000 | 124.59 | 0.024163 | 
| r=0.5 | 1.414e-03 | 4000 | 124.95 | 0.02354 | 
| r=0.25 | 2.828e-03 | 1000 | 153.91 | 0.026428 | 


**GCI (Celik et al. 2008 / ASME V&V 20)**

| QoI | observed order p | Richardson extrapolate | GCI (fine, 95 %) | convergence | asymptotic |
|---|---|---|---|---|---|
| Nu | 6.3238 | 124.59 | 0.00 % | monotonic | yes |
| f | 2.2131 | 0.024334 | 0.89 % | oscillatory | yes |

- Nu: observed order p=6.32 exceeds the formal order; GCI may be optimistic
- f: oscillatory convergence: GCI reported but should be interpreted with caution


![gci](figures/gci.png)



## 5. Validation

| QoI | Computed | Reference | Source | Deviation | Tolerance | Ref. band | Result |
|---|---|---|---|---|---|---|---|
| Nu | 124.59 | 137.84 | gnielinski | -9.6 % | ±15 % | ±10 % | PASS |
| Nu [dittus_boelter] | 124.59 | 128.43 | dittus_boelter | -3.0 % | ±25 % | ±25 % | PASS |
| f | 0.024163 | 0.026151 | petukhov | -7.6 % | ±10 % | ±5 % | PASS |


**Overall validation:** PASSED
- Nu: numerical-uncertainty band overlaps the reference band.
- Nu [dittus_boelter]: numerical-uncertainty band overlaps the reference band.
- f: numerical-uncertainty band does not overlap the reference band.





## 6. Review

**Verdict:** accept_with_warnings — 1 warning(s) from rule-based review
- ⚠ grid convergence for f is oscillatory


## Decision log

| # | Node | Message |
|---|---|---|
| 1 | plan | using the provided specification |
| 2 | build | built openfoam case (attempt 1, 16000 cells) |
| 3 | run | local run finished rc=0 in 65.5s |
| 4 | monitor | converged: all tracked residuals below 1e-05 at iteration 823 (worst h=4.21e-06; ignored: Uz) |
| 5 | postprocess | extracted QoIs |
| 6 | verify | level r=0.5: 4000 cells, rc=0 |
| 7 | verify | level r=0.25: 1000 cells, rc=0 |
| 8 | verify | grid convergence index computed |
| 9 | validate | Nu: -9.6% vs gnielinski (pass), Nu [dittus_boelter]: -3.0% vs dittus_boelter (pass), f: -7.6% vs petukhov (pass) |
| 10 | critique | accept_with_warnings: 1 warning(s) from rule-based review |


## Provenance

```json
{
  "timestamp": "2026-09-02T05:25:47+0000",
  "nuagent_version": "0.1.0",
  "git": {
    "commit": null,
    "dirty": true
  },
  "python": "3.11.15",
  "platform": "Linux-6.18.44-fc-v22-x86_64-with-glibc2.39",
  "hostname": "vm",
  "packages": {
    "langgraph": "1.2.11",
    "langchain-core": "1.6.1",
    "numpy": "2.4.4",
    "scipy": "1.17.1",
    "emcee": "3.1.6",
    "SALib": "1.5.2",
    "pydantic": "2.13.3"
  },
  "solvers": {
    "openfoam": null,
    "festim": null,
    "mpirun": "/usr/bin/mpirun"
  },
  "llm_model": null,
  "spec_sha256": "cd0a60a73e9f09e2",
  "attempts": 1,
  "adjustments": {},
  "n_decisions": 10
}
```

_Report generated by NuAgent 0.1.0. Every number above is traceable to files under `runs/pipe-turbulent-Re20k`._