# Minimal example / test fixture

This directory doubles as:

1. the **test fixture** used by `tests/test_integration.py` (via the
   `fixture_project` pytest fixture in `tests/conftest.py`), and
2. a **hand-runnable example** you can use to sanity-check a fresh
   checkout without a real Bosch project tree attached.

Everything under `dcom/` is hand-crafted AUTOSAR ARXML that covers
every locator type + transform in `scripts/mapping.yaml` on a narrow
slice of the real PARAM_MAP.

## Files

| File | Role |
|------|------|
| `values.json` | v2 `DiagComm_values.json` (`$schema` + `project` + `parameters`). |
| `config.json` | v2 sibling `DiagComm_config.json` (`$schema` + `paths` + `options`), pointing `dcom_root` at `./dcom`. |
| `dcom/` | Synthesized AUTOSAR tree (6 arxml files, ~30 PARAM-VALUE nodes total). |

> History: pre-1.5.0 used `config/project.json` + a separate values
> file. 1.5.0–1.12.x merged everything into one unified `values.json`.
> Since 1.13.0 user input is split across **two** sibling files
> (`values.json` = project + parameters, `config.json` = paths + options).
> The fixture mirrors the production v2 layout exactly.

## Standalone usage (outside of pytest)

```bash
# Copy the fixture into a temp workspace
cp -r tests/fixtures/minimal /tmp/diagcomm-demo
cd /tmp/diagcomm-demo

# Bring the skill's inputs and scripts within reach
mkdir inputs assets
cp <skill>/assets/DiagComm_schema.json assets/
cp values.json  inputs/DiagComm_values.json
cp config.json  inputs/DiagComm_config.json
```

In practice the easier path is `pytest -q tests` — which exercises this
fixture automatically under `tmp_path` isolation.

## What the integration test asserts

- `status` returns `OVERALL: READY` on this fixture.
- `validate` succeeds; swapping in a 29-bit CAN ID under
  `CAN_ID_Format=11bit` makes it fail with exit code 2.
- `apply --apply` rewrites the ARXML in place; the new literal values
  are observable at the expected `DEFINITION-REF`-anchored nodes.
- `landing-report` produces `unmatched locators: 0`.
- `fscs` writes a readable one-page snapshot.

## Regenerating / extending the fixture

The fixture is hand-written (not generated from a real project) so that
edits to `mapping.yaml` / `schema.py` can be tested against a known
baseline. If you change the PARAM_MAP, you will likely need to:

1. Add / rename PARAM-VALUE nodes in the relevant `dcom/**/*.arxml`.
2. Update `values.json` if a new field is introduced.
3. Re-run `pytest -q tests` and adjust assertions in
   `tests/test_integration.py` if hit counts / literals change.

Keep the fixture *minimal but realistic* — the goal is to exercise the
full pipeline without carrying around the bulk of a real Bosch
checkout.
