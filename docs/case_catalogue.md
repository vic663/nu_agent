# Case catalogue

The physics NuAgent orchestrates is *internal-flow convective heat transfer* and *hydrogen-isotope
transport in solids*. Both are shared by very different applications — reactor coolant channels, fusion
blankets and divertors, gas-turbine cooling passages, aircraft anti-ice systems — and both have benchmark
problems with known answers, which is what makes an agent qualifiable.

Legend: ✅ implemented · 🔧 designed, in roadmap · 💡 candidate

## A. Benchmark cases (known answers → agent qualification)

| # | Case | Physics / solver | Reference | Status |
|---|---|---|---|---|
| A1 | **Laminar heated pipe** (axisymmetric, uniform q″) | OpenFOAM `buoyantSimpleFoam`, laminar | exact: Nu = 48/11, f = 64/Re; thermal entry length | ✅ Nu +0.3 %, f +0.1 % |
| A2 | **Turbulent heated pipe** (water, Re 1e4–1e5) | OpenFOAM k-ω SST (wall-resolved or wall functions) | Gnielinski ±10 %, Petukhov, Dittus–Boelter ±25 %, Blasius/Prandtl–Kármán | ✅ Nu −9.6 % vs Gnielinski (−3.0 % vs D-B), f −7.6 % |
| A2-MF | **Turbulent heated pipe, closure ensemble** (`model_form`: SST, k-ε and realizable k-ε with Jayatilleke wall functions, Launder–Sharma) | same case, four closures, wall treatment per closure | as A2 | ✅ Nu 124.6 / 132.3 / 130.0 / 174.2 → model-form ±19.9 % vs GCI < 0.1 %; f ±13.9 % vs GCI 0.9 %; Launder–Sharma is the outlier here (it was the best closure for D1) — see `docs/examples/turbulent_pipe/report.md` §6 |
| A3 | **Tritium permeation, plane sheet** | FESTIM 2.x, transient diffusion | Crank series solution: J_ss = Dc₀/L, t_lag = L²/6D | ✅ generated/post-processed; solver in container |
| A4 | **Permeation with one McNabb–Foster trap** | FESTIM | Oriani effective diffusivity (dilute limit) | ✅ |
| A5 | **Thermal desorption spectrum, one trap** | FESTIM (implant → rest → ramp) + first-order reduced model | Redhead/Kissinger peak-temperature relation | ✅ reduced model; FESTIM runner written |
| A6 | **Hartmann/Shercliff MHD duct flow** | OpenFOAM `mhdFoam` (laminar incompressible MHD) | exact Hartmann profile u(y; Ha); pressure gradient | 🔧 analytical solution implemented (`physics/analytical.hartmann_velocity`); template = OpenFOAM `hartmann` tutorial |

## B. Application cases — fission

| # | Case | Why it matters | Reference data | Design sketch | Status |
|---|---|---|---|---|---|
| B1 | **Conjugate heat transfer in a heated tube** (solid wall + coolant) | fuel-pin/cladding-to-coolant path; ORNL group does CHT routinely | analytical 1-D conduction + A2 correlations | `chtMultiRegionSimpleFoam`, wedge with a solid annulus region; QoIs: wall/interface temperature, Nu | 🔧 week 2 |
| B2 | **Bare rod-bundle subchannel** (square lattice, P/D 1.2–1.3) | the canonical LWR/SFR coolant geometry | Trupp & Azad (1975), Hooper & Rehme (1984); Rehme friction correlation | periodic subchannel (¼ symmetry) with `snappyHexMesh` or multi-block `blockMesh`; QoIs: f, Nu, secondary-flow strength | 🔧 week 3 |
| B3 | **Natural-circulation loop** | passive safety systems (SMRs) | loop analytical solution (Vijayan) | 1-D/2-D loop with `buoyantSimpleFoam`, gravity on | 💡 |

## C. Application cases — fusion

| # | Case | Why it matters | Reference | Design sketch | Status |
|---|---|---|---|---|---|
| C1 | **Coupled coolant channel → tritium permeation through the channel wall** | tritium inventory and permeation into coolant loops is a licensing-level question for blankets | one-way coupling; verify against A2 + A3 in the limits | OpenFOAM computes the wall-temperature profile T_w(x) (A2); FESTIM solves permeation through the pipe wall with T(x) as a spatially varying temperature (`temperature=lambda x: …`) and Sieverts BCs; QoIs: permeation flux distribution, total inventory. **Multiphysics code integration.** | 🔧 week 2 — priority |
| C2 | **Liquid-metal MHD duct** (PbLi, Ha 10²–10³) | blanket pressure drop and heat transfer are MHD-dominated | Shercliff/Hunt exact solutions; A6 | `mhdFoam` (laminar) → later VertexCFD/quasi-2-D models; QoIs: pressure gradient, velocity profile, Hartmann-layer thickness | 🔧 week 2 |
| C3 | **Divertor monoblock (W/Cu/CuCrZr) heat + tritium** | FESTIM's flagship application | FESTIM monoblock example; Delaporte-Mathurin et al. | 2-D axisymmetric monoblock, coupled `HeatTransferProblem` + `HydrogenTransportProblem` | 🔧 week 3 |
| C4 | **TDS calibration against real spectra** | trap parameters are the key uncertainty of inventory predictions | published W TDS data | reduced-model calibration → GP surrogate of FESTIM TDS → posterior comparison | 🔧 week 2 |

## D. Application cases — aerospace (transferable heat transfer, PI's background)

| # | Case | Why it matters | Reference | Status |
|---|---|---|---|---|
| D1 | **Rib-roughened cooling tube** (transverse square ribs, e/D = 0.04, p/e = 10, air, Re = 2×10⁴) | turbine-blade internal cooling and enhanced heat-exchanger tubes; the *same* rib turbulators are used on UK AGR fuel cladding | Webb, Eckert & Goldstein (1971) roughness functions R(e⁺), G(e⁺); Han (1988) for channels; Rau et al. (1998) | ✅ implemented, validated — see below |
| D2 | **Impinging jet (anti-ice piccolo tube)** | wing anti-ice; the PI validated this at Bombardier against NASA data | Martin (1977), Goldstein & Behbahani (1982); ERCOFTAC/NASA impinging-jet data | 🔧 week 3 — axisymmetric jet onto a heated plate (H/D 2–8); QoIs: stagnation Nu, radial Nu(r) |

### D1 results — turbulence-model comparison (real OpenFOAM runs, 6-rib development case, 13.5k cells)

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
