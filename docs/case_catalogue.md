# Case catalogue

This catalogue separates **public evidence** from future work. Implemented cases are listed below with
their current qualification status. Planned extensions are summarized separately and are not evidence of
implemented or qualified capability.

Legend: ✅ qualified or validated evidence · ⚠ implemented, qualification incomplete

## A. Benchmark cases (known answers → agent qualification)

| # | Case | Physics / solver | Reference | Status |
|---|---|---|---|---|
| A1 | **Laminar heated pipe** (axisymmetric, uniform q″) | OpenFOAM `buoyantSimpleFoam`, laminar | exact: Nu = 48/11, f = 64/Re; thermal entry length | ✅ Nu +0.3 %, f +0.1 % |
| A2 | **Turbulent heated pipe** (water, Re 1e4–1e5) | OpenFOAM k-ω SST (wall-resolved or wall functions) | Gnielinski ±10 %, Petukhov, Dittus–Boelter ±25 %, Blasius/Prandtl–Kármán | ✅ Nu −9.6 % vs Gnielinski (−3.0 % vs D-B), f −7.6 % |
| A2-MF | **Turbulent heated pipe, closure ensemble** (`model_form`: SST, k-ε and realizable k-ε with Jayatilleke wall functions, Launder–Sharma) | same case, four closures, wall treatment per closure | as A2 | ✅ Nu 124.6 / 132.3 / 130.0 / 174.2 → model-form ±19.9 % vs GCI < 0.1 %; f ±13.9 % vs GCI 0.9 %; Launder–Sharma is the outlier here (it was the best closure for D1) — see `docs/examples/turbulent_pipe/report.md` §6 |
| A3 | **Tritium permeation, plane sheet** | FESTIM 2.x, transient diffusion | Crank series solution: J_ss = Dc₀/L, t_lag = L²/6D | ✅ trap-free permeation path qualified against analytical steady flux and time lag |
| A4 | **Permeation with one McNabb–Foster trap** | FESTIM | Oriani effective diffusivity (dilute limit) | ⚠ implemented; independent qualification incomplete |
| A5 | **Thermal desorption spectrum, one trap** | FESTIM (implant → rest → ramp) + first-order reduced model | Redhead/Kissinger peak-temperature relation | ⚠ reduced model implemented; FESTIM/TDS qualification incomplete |

## B. Implemented application case

| # | Case | Evidence | Status |
|---|---|---|---|
| D1 | **Rib-roughened cooling tube** (e/D = 0.04, p/e = 10, air, Re = 2×10⁴) | Real OpenFOAM runs; Webb correlation; closure comparison; reattachment diagnostic | ✅ implemented and validated; detailed results below |

## C. Planned work — not implemented or qualified

The following are future extensions only. They are tracked in [`roadmap.md`](roadmap.md), not counted
as current NuAgent capability:

- conjugate heat transfer;
- rod-bundle/subchannel CFD;
- one-way OpenFOAM -> FESTIM coolant/permeation coupling;
- Hartmann/Shercliff MHD;
- FESTIM-in-the-loop TDS calibration against real spectra;
- impinging-jet heat transfer;
- divertor-monoblock heat and hydrogen-isotope transport.

## D. Detailed evidence — rib-roughened cooling tube

The ribbed tube is where the workflow earns its keep: the *default* closure fails validation and the
diagnostics say why.

| Closure | Reattachment behind rib | f vs Webb | Nu vs Webb (wetted-area T) | Nu vs Webb (base T) |
|---|---|---|---|---|
| k-ω SST, wall-resolved (y⁺≈1) | **none** — one recirculation fills the whole gap (d-type) | −55 % | −66 % | −63 % |
| k-ω SST, wall functions | none | −47 % | −64 % | −63 % |
| standard k-ε, wall functions | 5.0 e | −11 % | −33 % | −28 % |
| realizable k-ε, wall functions | 4.5 e | −15 % | −48 % | −45 % |
| **Launder–Sharma low-Re k-ε, wall-resolved** | **4.0 e** | **−4 %** | −31 % | −25 % |

Experiments (Rau et al. 1998; Webb 1971) show k-type roughness for p/e = 10: reattachment at ≈4–5 e,
then a high-heat-transfer recovery region. The k-ω SST family predicts a cavity ("d-type") flow for this
geometry and therefore misses both the form drag and the enhancement; the ε-family recovers the flow
topology and the friction factor, while the remaining ≈25–30 % Nusselt deficit is the well-documented
RANS under-prediction of heat transfer in separated/reattaching regions (Iacovides & Raisee 1999 —
cured there by the Yap length-scale correction, not available in OpenFOAM's `LaunderSharmaKE`).
The critique node now flags "no reattachment between ribs" automatically and recommends the ε-family.

This comparison was assembled by hand from five separate runs. It is now a workflow feature: the
`model_form` block of the specification (see `examples/aerospace/ribbed_cooling_tube.yaml`) re-runs the
converged base grid with the listed closures — an orchestrator–workers fan-out with a deterministic
reduction — and the report's "Model-form uncertainty" section tabulates each closure's Nu and f against
the primary and against Webb, the per-closure reattachment length and reversed-flow fraction, and the
half-range spread as a model-form uncertainty next to the GCI. The pre-flight `review` node warns when
k-ω SST is selected for p/e ≈ 10 ribs, citing this table. (The mock backend reproduces the qualitative
pattern — an SST member without reattachment — so the eval task 07 exercises the whole chain without a
solver; the real-OpenFOAM ensemble run is scheduled in the roadmap.)

**Final 12-rib case** (`examples/aerospace/ribbed_cooling_tube.yaml`, Launder–Sharma, 37k cells, 10 cells across a rib,
three grids at ratio 1.4): Nu = 112.9 (−20.4 % vs Webb, −13 % with the base-temperature definition; Nu/Nu₀ = 2.18;
observed order 2.1, GCI 2.5 %), f = 0.2313 (−3.3 % vs Webb; f/f₀ = 8.85; still 2.4 % grid-dependent between the two
finest grids, so its GCI is not asymptotic), reattachment at 3.3 e, thermal-performance factor 1.06. Both quantities
pass their acceptance tolerances (25 % / 15 %); the report flags the remaining energy-balance closure (3 %) and the
non-asymptotic friction-factor grid study — the workflow does not rubber-stamp.
The nuclear connection is direct: rib-roughened fuel-pin cladding in Advanced Gas-cooled Reactors uses
exactly this heat-transfer mechanism, and the same RANS deficits are reported in AGR channel studies
(Keshmiri et al., Manchester).

Every application case plugs in through the same three artefacts: a `CaseSpec` model, a template set (or
FESTIM builder), and reference entries in the registry. The agent, the executors, the V&V machinery and
the reporting do not change.

## References

- Celik, I.B., Ghia, U., Roache, P.J., Freitas, C.J., Coleman, H., Raad, P.E. (2008). *J. Fluids Eng.* 130, 078001.
- Gnielinski, V. (1976). *Int. Chem. Eng.* 16, 359–368.  Petukhov, B.S. (1970). *Adv. Heat Transfer* 6.
- Crank, J. (1975). *The Mathematics of Diffusion*, 2nd ed.  Oriani, R.A. (1970). *Acta Metall.* 18, 147.
- Redhead, P.A. (1962). *Vacuum* 12, 203.  Müller, U., Bühler, L. (2001). *Magnetofluiddynamics in Channels and Containers*.
- Webb, R.L., Eckert, E.R.G., Goldstein, R.J. (1971). *Int. J. Heat Mass Transfer* 14, 601–617.
- Han, J.C. (1988). *J. Heat Transfer* 110, 321–328.  Rau, G. et al. (1998). *J. Turbomach.* 120, 368–375.
- Iacovides, H., Raisee, M. (1999). *Int. J. Heat Fluid Flow* 20, 320–328 (low-Re k-ε with Yap correction for ribbed passages).
- Keshmiri, A., Cotton, M.A., Addad, Y., Laurence, D. (2012). *Flow Turbul. Combust.* 89 (RANS/LES of rib-roughened AGR channels).
- Taslim, M.E., Ren, B. (2016). ISROMAC 2016, paper 44042.  Martin, H. (1977). *Adv. Heat Transfer* 13.
- Trupp, A.C., Azad, R.S. (1975). *Nucl. Eng. Des.* 32, 47–84.  Rehme, K. (1973). *Int. J. Heat Mass Transfer* 16, 933.
- Delaporte-Mathurin, R. et al. (2024). FESTIM: an open-source code for hydrogen transport simulations. *Int. J. Hydrogen Energy*.
