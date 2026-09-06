# Changelog

## 0.1.4 — Unreleased — adversarial audit response

> Release date is set when the `v0.1.4` tag is cut, after the three GitHub Actions jobs
> (unit / OpenFOAM / FESTIM) have run green. `CITATION.cff`'s `date-released` is added at
> the same moment. Until then this section is unreleased and nothing here claims otherwise.

v0.1.3 was audited against the failure modes a V&V reviewer would use on a scientific CFD code:
where can *execution success* masquerade as *physical credibility*, and where does the repository
claim more than its own artefacts support. This release is the response. Nothing below is a new
feature; every entry closes a way the workflow could return, or the documentation could claim, a
result that was not earned.

### Correctness

- **Multi-trap effective diffusivity was wrong.** `agent/vv.py` applied the single-trap Oriani
  formula once per trap, giving `D/Π(1 + nᵢkᵢ/pᵢ)`. Trap retardation terms **add**:
  `D_eff = D/(1 + Σ nᵢkᵢ/pᵢ)` (Oriani 1970; McNabb & Foster 1963; and the independent `c_t,i`
  summed in FESTIM's own mobile balance). For two traps with `n·k/p = 1e7` each the old form
  under-predicted `D_eff` by six orders of magnitude — in the *reference solution* the permeation
  time lag is validated against. Single-trap results are unchanged. New:
  `physics.analytical.effective_diffusivity_multitrap`.
- **Grid families were not systematic refinements.** The y⁺ target was anchored to the base grid,
  so a three-level wall-resolved study ran at y⁺ = 1 → 2 → 4 and the coarse levels left the
  regime the closure is written for; separately, a cell-count floor could give two wall-function
  levels an identical radial mesh. The target is now anchored to the **coarsest** level of the
  planned family (`mesh.family_min_refinement`), so a 3-level study at ratio 2 runs y⁺ =
  0.25 → 0.5 → 1 and every level stays wall-resolved. `verify` additionally checks the *realised*
  meshes (`verification.family`) for strict coarsening in every direction and for a near-wall
  regime that does not change across levels, and the report now states plainly whether the family
  is a systematic refinement — a correct GCI computed on one that is not is not a discretisation
  uncertainty.
- **Ribbed-tube wall spacing used the wrong friction factor.** `u_τ` was computed from Webb's
  *total* friction factor, which is dominated by form drag on the rib faces rather than shear on
  the inter-rib floor; at e/D = 0.04, p/e = 10, Re = 2e4 that inflates `u_τ` by 3.0×, so a
  requested y⁺ = 40 wall-function mesh actually landed near y⁺ = 13, inside the buffer layer. The
  smooth-tube value is now used as the defensible lower bound and **both** bounds are recorded, so
  the reported y⁺ carries its uncertainty instead of a false point value.

### Honest verdicts

- **The physics critique is now a gate, not an annotation.** `report` computed `critique.verdict`
  and then never consulted it: a run the critique had *rejected* still printed `Status: success`
  whenever validation happened to pass, and `nuagent run` exited 0 for `completed_with_issues` —
  which is by definition `validation.passed == False`. Status is now `failed` when the run failed
  **or** the critique rejected it, `success` only when validation passed, and the CLI exits 0 only
  for `success` (2 for `completed_with_issues`, 1 otherwise), so no script can treat an unvalidated
  run as a good one.
- **Positive eval tasks must actually validate.** `task_success` accepted
  `status in ("success", "completed_with_issues")` without requiring `validated`, so a task whose
  QoIs landed in the expected range while validation failed and the critique rejected it still
  scored a success — the exact failure this suite exists to detect. Ordinary tasks now require
  `status == "success"`, `validated`, and a non-`reject` verdict.

- **Convergence is now three states, not one.** `criterion_met` (residual target reached) is the
  live-stop signal the monitor uses; `converged` additionally requires `completed` *and* a zero
  exit status, which the `monitor` node now enforces. Previously a run killed by the OOM killer or
  the scheduler, whose last written residuals happened to sit under target, parsed as converged and
  flowed through to `success`; the process return code was never consulted anywhere in the graph.
  `_FATAL_RE` also now matches `MPI_ABORT`, `Killed`, `std::bad_alloc`, `slurmstepd: error` and
  `DUE TO TIME LIMIT`.
- **Case reuse can no longer re-report old numbers under a new commit.** `spec_hash` now includes
  `generator_fingerprint()` — the NuAgent version plus a digest of every shipped Jinja template —
  and `reusable_case` refuses a case whose previous run did not converge. Editing a template and
  re-running used to adopt the stale directory and synthesise `rc=0` for it.
- **`require_asymptotic` and `reference_valid` are no longer write-only.** Both were documented
  fields with zero consumers anywhere in the repository. `require_asymptotic` now fails the run
  when the family is non-asymptotic or not systematic; a PASS against a correlation used outside
  its stated validity range is now a critique warning and is marked in the report table.
- **Validation tolerance is bounded** at 0.5. It was `gt=0` and otherwise unbounded, so a planner
  could write `tolerance: 99.0` and obtain `Status: success`, green PASS cells and exit code 0.
- **Provenance stops asserting what it does not know.** `git.dirty` was `bool(None) == False` — a
  positive claim of a clean tree made from no information — and is now tri-state; the commit is
  recorded only when the located repository really is the NuAgent checkout (`rev-parse` walks
  upward, so an installed copy would otherwise stamp results with an unrelated repo's HEAD). The
  input-digest set had an `and`/`or` precedence bug that excluded the grid levels and ensemble
  members whose values produce the GCI and the model-form band.

### Safety

- **Shell injection into the generated `job.sbatch` is closed.** `slurm_partition`,
  `slurm_account` and `docker_image` were unvalidated free-text fields of `SimulationSpec` — which
  `LLMPolicy.plan` produces — interpolated unescaped into `#SBATCH` lines; a newline terminated the
  comment and the remainder became an executed shell line on a cluster. All three are now
  charset-restricted at the schema boundary, `NUAGENT_SLURM_MODULES` / `NUAGENT_SLURM_EXTRA` are
  rejected at point of use if they carry shell metacharacters, and the SLURM Jinja environment uses
  `StrictUndefined` like the OpenFOAM one.
- **The approval gate covers the whole workflow.** Grid-refinement levels and closure-ensemble
  members called the executor directly, so one "yes" could become up to 16 concurrent cluster
  submissions. The gate now discloses the full job budget (attempts + levels + members, with core
  minutes) and every child submission honours it.

### Qualification

- **Three negative controls, which the agent must refuse.** A success rate measured only on tasks
  that are supposed to succeed cannot detect a wrong answer. Added: a TDS spectrum with no traps
  and an unreachable fully-developed target (both must be **blocked by pre-flight**), and k-ω SST
  on a p/e = 10 ribbed passage — which converges cleanly and is still wrong — where validation must
  **FAIL** and the critique verdict must be `reject`. `nuagent eval` grades these in the opposite
  direction and labels them in the table.
- **Eval task 04 was itself physically impossible** — Re = 800 in water validated against the fully
  developed `48/11` in a 40 D pipe whose thermal entry length is ~233 D — and scored `+0.50 % PASS`
  because the mock generates its QoI from the same correlation the validator uses. The task is
  fixed; the defective version is kept permanently as negative control 09.
- **Pre-flight blocks an unreachable fully-developed target**: when the entry length exceeds the
  whole domain and the case is validated against a fully-developed correlation, no amount of mesh
  refinement can fix it, so the run is stopped before meshing.
- **The README no longer quotes a validation rate from the mock backend.** The mock is seeded from
  the same correlations it is scored against, so its observed order is 2.000 by construction; that
  is now stated, and the eval headline is a *completion* metric.

### Repository

- **`.github/workflows/ci.yml` was invalid YAML** — a `${{ ... }}` expression inside a flow mapping —
  so GitHub rejected the entire workflow and **no CI job in this repository had ever run**. Fixed;
  the badge can now mean something.
- `numpy>=2.0` (the code calls `np.trapezoid`, added in NumPy 2.0, while the pin allowed 1.24).
- Version, `CITATION.cff` and the CLI banner are consistent at 0.1.4, and the citation title and
  package description now match the README's domain-neutral tagline.
- 14 mypy errors fixed, including an unguarded regex match in the `polyMesh/faces` reader that
  turned a binary-format mesh into an obscure `AttributeError`. `types-PyYAML` added to the dev
  extras. mypy is still not clean under full third-party type resolution and is still not in CI;
  see the note in `pyproject.toml`.
- Test fixtures that encoded the same unreachable-entry-length defect as task 04 now use a
  Prandtl-1 fluid or a longer pipe.
- New `tests/test_release_gates.py`: regression tests for the gates whose absence let a
  result be reported without being earned — a rejected critique must force `failed`, an
  ordinary eval task must validate before it scores, the suite must contain negative
  controls, the CI workflow must parse *and* trigger on the repository's actual branch, and
  `CITATION.cff` must not carry a release date while the CHANGELOG says unreleased.
  109 test functions / 114 runs, 110 passing and 4 solver-dependent skips.

### Known limitations (not closed in 0.1.4)

Sobol analysis imputes failed model evaluations with the sample mean and does not report them;
emcee convergence is not checked (`get_autocorr_time(tol=0)`, no thinning, no ESS) and the shipped
TDS example is not converged; the liquid-metal fluid presets have no liquid-metal Nusselt
correlation; the two-grid GCI branch reports an assumed `p = 2` under a column headed "observed
order"; report writing is not encoding-safe on Windows. See the audit memo for the full list.
