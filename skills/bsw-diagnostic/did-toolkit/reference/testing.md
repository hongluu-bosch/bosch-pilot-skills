# Testing & CI Reference

Test suite layout, normalization policy, golden-file workflow, and CI/CD recipes. Read this when adding a test, updating golden fixtures, or debugging a pytest failure.

The skill ships with a full pytest suite under `tests/` that covers every helper, every generator, and several end-to-end pipeline scenarios against a tiny synthetic DID fixture. Golden-file comparisons use moderate normalization (timestamps replaced with a sentinel, trailing whitespace stripped, blank-line runs collapsed) so behavior drift is caught without false positives on cosmetic changes.

## Layout

```
tests/
├── conftest.py                       # --update-goldens, shared fixtures,
│                                     #   review_fscs stdout sandbox
├── requirements-dev.txt              # pytest, pytest-cov, freezegun
├── helpers/normalize.py              # moderate text normalization
├── fixtures/
│   ├── tiny_did.json                 # ~5 DIDs covering R/RW, EEPROM/RAM,
│   │                                 #   enum/numeric, min==max edge case
│   ├── tiny_project.json             # minimal project.json
│   ├── expected_fscs_22.txt          # reference FSCS 22 for parser tests
│   └── expected_fscs_2e.txt          # reference FSCS 2E for parser tests
├── unit/                             # one test module per script / concern
│   ├── test_naming_helpers.py        # RBAPLCUST_/RBFS_DCOM_/NVM_ID_DCOM_/DID_ range
│   ├── test_parse_helpers.py         # parse_enum_values / parse_numeric_range
│   ├── test_code_generators.py       # PDM / config / settings / elements / range / read / write
│   ├── test_path_resolution.py       # _product_type_lower + _resolve_path placeholders
│   ├── test_merge_header.py          # _extract / _find_insert / _merge_header_content idempotence
│   ├── test_pipeline_argparse.py     # dry_run forwarding + retired-kwarg guard rails
│   ├── test_fscs_generator.py        # build_fscs_document helpers + FSCSGenerator.generate smoke
│   ├── test_fscs_adapter.py          # load_fscs + to_review_dicts
│   ├── test_review_fscs.py           # FSCSReviewer compliance/consistency checks
│   ├── test_review_arxml.py          # ARXML reviewer (coverage/identifiers/data-size) against golden tree
│   ├── test_review_impl.py           # Implementation reviewer (C/PDM/headers/ranges) against golden tree
│   ├── test_collision.py             # DID name collision → hex-disambiguated filenames
│   ├── test_templating.py            # Jinja2 env contract + StrictUndefined guard
│   ├── test_did_input_model.py       # pydantic DIDInput fail-fast contract
│   ├── test_package_split.py         # generate_implementation.py shim ↔ package identity
│   ├── test_arxml_merge.py           # pure merge_arxml / extract_dcmdsp_short_names logic
│   └── test_arxml_generator.py       # ARXMLGenerator helpers + smoke against golden tree
├── integration/
│   ├── test_arxml_project_mirror.py  # Phase 2 project-tree merge + skip-on-conflict
│   ├── test_per_product_skip.py      # paths.per_product = null skip semantics
│   ├── test_fscs_dual_write.py       # FSCS write paths + CSV round-trip
│   └── test_doors_state_machine_rounds.py  # DOORS INSERT / UPDATE / NOOP / STALE rounds
└── golden/phase_all/                 # committed reference output tree (stable anchor name; read by the unit reviewer tests above)
```

## Running

```bash
# Install dev dependencies (once)
python -m pip install -r tests/requirements-dev.txt

# Full run: unit + integration + coverage
python -m pytest --cov=scripts --cov-report=term-missing

# Fast unit-only smoke check
python -m pytest tests/unit -q

# Regenerate golden files after an intentional generator change, then
# eyeball the diff against the prior committed goldens before committing.
# The reviewer + generator unit tests both diff against tests/golden/phase_all/.
python -m pytest tests/unit/test_arxml_generator.py tests/unit/test_review_arxml.py tests/unit/test_review_impl.py --update-goldens
```

## Normalization Policy

`tests/helpers/normalize.py` implements the moderate policy:

- `Generated[ on]: <timestamp>` lines (C/header comments, Python prints) and Chinese `生成时间: <timestamp>` lines (review report) are replaced with a stable sentinel.
- CRLF is normalized to LF; trailing whitespace stripped on every line.
- Runs of 3+ newlines collapse to a single blank line.
- Every source comment (`/*DE|...*/`, doxygen, `//`, `#`) is preserved so accidental drift in downstream-contract comments still fails tests.

Integration tests use `freezegun` to pin `datetime.now()` to `2026-04-20 12:00:00` so timestamps are deterministic even before normalization kicks in.

## Golden Update Workflow

1. Make the intentional generator change (e.g. tweak a macro name).
2. Run `python -m pytest tests/unit/test_arxml_generator.py tests/unit/test_review_arxml.py tests/unit/test_review_impl.py --update-goldens`.
3. `git diff tests/golden/phase_all/` and confirm every change is intentional. Revert if anything unexpected shows up.
4. Run `python -m pytest` once more without `--update-goldens` to confirm the suite passes against the new goldens, then commit fixtures + golden tree together with the generator change.

## CI/CD Recipes

Example pipeline step:

```yaml
generate-dids:
  script:
    # There is no --phase all — run each phase as its own command.
    # There is no --product-type flag either; Phase 2/3 fan out
    # across every product carried by a `used` DID in fscs.json,
    # writing per-product artefacts under
    # outputs/{arxml,implementation}/<PT>/. Restrict the build set
    # by editing fscs_edit.xlsx::Product_Type then re-importing.
    - python scripts/pipeline.py --phase fscs
    - python scripts/pipeline.py --phase xlsx-import
    - python scripts/pipeline.py --phase arxml
    - python scripts/pipeline.py --phase implementation
    - git add outputs/
    - git commit -m "Auto-generate DID configurations"
```

Recommended test stage:

```yaml
test-did-toolkit:
  script:
    - python -m pip install -r tests/requirements-dev.txt
    - python -m pytest --cov=scripts --cov-report=term-missing
```
