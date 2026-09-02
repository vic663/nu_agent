# Contributing

## Development setup

```bash
pip install -e ".[all]"
pre-commit install   # optional; CI runs ruff + pytest
ruff check src tests && ruff format --check src tests
pytest -q                        # solver-free tests (OpenFOAM/FESTIM tests skip automatically)
pytest -m openfoam -q            # with OpenFOAM on PATH (or NUAGENT_FOAM_BASHRC set)
pytest -m festim -q              # inside the FESTIM container / conda env
nuagent eval evals/tasks         # agent qualification suite on the mock backend
```

## Adding a case type

1. Add a Pydantic model to the `CaseSpec` union in `src/nuagent/spec.py` (with field descriptions —
   they are the LLM's prompt).
2. Add a template set under `src/nuagent/backends/openfoam/templates/<name>/` or a builder in
   `backends/festim/run_festim.py`; extend `render_context` / `_params`.
3. Add a QoI extractor and, if needed, analytical references in `src/nuagent/agent/vv.py` and
   correlations in `src/nuagent/physics/`.
4. Add an example spec in `examples/`, an eval task in `evals/tasks/`, and tests.

## Conventions

- Every physical quantity in SI; document units in field descriptions.
- Nothing in `backends/` or `executors/` may import an LLM library.
- Anything the diagnostician may change must appear in `ADJUSTABLE_NUMERICS` (bounded) and in `Adjustments`.
- Reports must be reproducible from `result.json` + `decisions.jsonl` (`nuagent report <run_dir>`).
