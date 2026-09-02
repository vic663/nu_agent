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

| # | Case | Why it matters | Reference | Design sketch | Status |
|---|---|---|---|---|---|
| D1 | **Rib-roughened cooling channel** (e/D_h ≈ 0.1, p/e = 10) | turbine-blade internal cooling; heat-transfer vs friction trade-off | Han (1988) rib-roughness functions R(e⁺), G(e⁺); Rau et al. (1998); liquid-crystal thermography data (Taslim & Ren, 2016) | 2-D periodic ribbed channel, k-ω SST, `blockMesh` multi-block; QoIs: Nu/Nu₀, f/f₀, thermal performance (Nu/Nu₀)/(f/f₀)^{1/3} | 🔧 week 1–2 |
| D2 | **Impinging jet (anti-ice piccolo tube)** | wing anti-ice; the PI validated this at Bombardier against NASA data | Martin (1977), Goldstein & Behbahani (1982) stagnation Nu correlations; ERCOFTAC/NASA impinging-jet data | axisymmetric jet onto a plate (H/D 2–8), k-ω SST / v²-f; QoIs: stagnation Nu, radial Nu(r) | 🔧 week 3 |

Every application case plugs in through the same three artefacts: a `CaseSpec` model, a template set (or
FESTIM builder), and reference entries in the registry. The agent, the executors, the V&V machinery and
the reporting do not change.

## References

- Celik, I.B., Ghia, U., Roache, P.J., Freitas, C.J., Coleman, H., Raad, P.E. (2008). *J. Fluids Eng.* 130, 078001.
- Gnielinski, V. (1976). *Int. Chem. Eng.* 16, 359–368.  Petukhov, B.S. (1970). *Adv. Heat Transfer* 6.
- Crank, J. (1975). *The Mathematics of Diffusion*, 2nd ed.  Oriani, R.A. (1970). *Acta Metall.* 18, 147.
- Redhead, P.A. (1962). *Vacuum* 12, 203.  Müller, U., Bühler, L. (2001). *Magnetofluiddynamics in Channels and Containers*.
- Han, J.C. (1988). *J. Heat Transfer* 110, 321–328.  Rau, G. et al. (1998). *J. Turbomach.* 120, 368–375.
- Taslim, M.E., Ren, B. (2016). ISROMAC 2016, paper 44042.  Martin, H. (1977). *Adv. Heat Transfer* 13.
- Trupp, A.C., Azad, R.S. (1975). *Nucl. Eng. Des.* 32, 47–84.  Rehme, K. (1973). *Int. J. Heat Mass Transfer* 16, 933.
- Delaporte-Mathurin, R. et al. (2024). FESTIM: an open-source code for hydrogen transport simulations. *Int. J. Hydrogen Energy*.
