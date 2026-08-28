"""Unit tests for ``scripts.config`` Pydantic schema + loader.

Schema version under test: **2.2**. Pre-release skill, so the
validator only accepts the current :data:`SCHEMA_VERSION` — every
prior shape (1.0 / 1.1 / 2.0 / 2.1) hard-fails at load. The
``per_product`` whitelist (6 PT keys × 6 path keys) is enforced so
typos fail loud at config load.

``options`` is an empty placeholder. ``output_mode`` (project tree
is sole sink for Phase 2/3) and ``backup_before_write`` /
``backup_keep`` (rolling backup mechanism not supported) are not
accepted. The class is kept only so an ``extra='forbid'`` guard
rejects stale ``options.*`` keys at load.

``load_project_config(path)`` honours the missing / empty / bad
JSON / valid JSON behaviour matrix documented in
``scripts/config/loader.py``. Round-trip via ``save_project_config``
is also covered so an agent can edit a config in memory and
persist without losing fidelity.
"""

from __future__ import annotations

import json

import pytest

from config import (
    SCHEMA_VERSION,
    ProjectConfig,
    load_project_config,
    save_project_config,
)
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Defaults / empty construction
# ---------------------------------------------------------------------------


def test_project_config_no_args_is_valid_safe_posture():
    """ProjectConfig() (no args) is a valid 'no-mirror' posture.

    Schema 2.2 keeps the three-block top level
    (schema_version / paths / options). The no-args posture has
    no per-PT overrides and an empty options block.
    """
    config = ProjectConfig()
    assert config.schema_version == SCHEMA_VERSION == "2.2"
    # v1.27.0: ProjectOptions has no fields; model_dump should be {}.
    assert config.options.model_dump() == {}
    assert config.paths.base_dir == ""
    assert config.paths.arxml_file == ""
    assert config.paths.per_product == {}
    # v1.28.0: paths.input_did_json defaults to "" (no questionnaire
    # recorded yet). The state machine populates it during the
    # QUESTIONNAIRE_READY → write-config transition; an empty value
    # here lets the no-args posture stay valid.
    assert config.paths.input_did_json == ""


def test_project_config_top_level_fields_are_only_three():
    """Pin the top-level shape: only schema_version / paths /
    options. Adding a new top-level block back should be a
    deliberate API change visible in this test."""
    fields = set(ProjectConfig.model_fields.keys())
    assert fields == {"schema_version", "paths", "options"}


# ---------------------------------------------------------------------------
# Pre-release schema pin: every prior shape hard-fails at load
# ---------------------------------------------------------------------------


def test_legacy_project_block_raises():
    """Any v1.0 / v1.1 config that still carries a ``project`` block
    must fail loudly — no migrator (pre-release skill)."""
    with pytest.raises(ValidationError) as excinfo:
        ProjectConfig.model_validate({
            "schema_version": SCHEMA_VERSION,
            "project": {"name": "demo"},
        })
    assert "project" in str(excinfo.value).lower()


def test_legacy_product_type_mapping_raises():
    """The five-product mapping is hard-coded into
    ``implementation.paths._DEFAULT_PRODUCT_TYPE_MAP``; no
    config-level override."""
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({
            "schema_version": SCHEMA_VERSION,
            "product_type_mapping": {"ESP": "esp10"},
        })


def test_legacy_paths_project_root_raises():
    """``paths.project_root`` was a duplicate; gone."""
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({
            "schema_version": SCHEMA_VERSION,
            "paths": {"project_root": "Fe_Super"},
        })


def test_legacy_options_output_mode_raises():
    """``options.output_mode`` is not a supported field (the project
    tree is the sole Phase 2/3 sink). Any stale config that still
    carries it must fail loud at load so the operator updates their
    workspace."""
    with pytest.raises(ValidationError) as excinfo:
        ProjectConfig.model_validate({
            "schema_version": SCHEMA_VERSION,
            "options": {"output_mode": "project"},
        })
    msg = str(excinfo.value).lower()
    assert "output_mode" in msg or "extra" in msg


def test_legacy_options_backup_before_write_raises():
    """``options.backup_before_write`` is not supported. The
    skip-on-conflict semantics never overwrite existing content,
    so a rolling-backup safety net is not needed."""
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({
            "schema_version": SCHEMA_VERSION,
            "options": {"backup_before_write": True},
        })


def test_legacy_options_backup_keep_raises():
    """``options.backup_keep`` is not supported; same rationale as
    ``backup_before_write``."""
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({
            "schema_version": SCHEMA_VERSION,
            "options": {"backup_keep": 5},
        })


def test_legacy_options_overwrite_existing_raises():
    """Legacy compatibility flag with no consumer; not accepted."""
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({
            "schema_version": SCHEMA_VERSION,
            "options": {"overwrite_existing": True},
        })


def test_legacy_options_generate_comments_raises():
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({
            "schema_version": SCHEMA_VERSION,
            "options": {"generate_comments": True},
        })


def test_legacy_options_validate_before_generate_raises():
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({
            "schema_version": SCHEMA_VERSION,
            "options": {"validate_before_generate": True},
        })


def test_old_schema_version_1_1_raises_with_init_project_pointer():
    """schema_version 1.x must hard-fail with a message that
    points operators at ``--init-project``."""
    with pytest.raises(ValidationError) as excinfo:
        ProjectConfig.model_validate({"schema_version": "1.1"})
    msg = str(excinfo.value)
    assert "1.1" in msg
    assert "init-project" in msg or "schema_version" in msg


def test_old_schema_version_2_0_raises():
    """Pre-release skill: prior 2.0 / 2.1 shapes are rejected —
    no migration shim. The error message must surface the bad
    version + the current one."""
    with pytest.raises(ValidationError) as excinfo:
        ProjectConfig.model_validate({"schema_version": "2.0"})
    msg = str(excinfo.value)
    assert "2.0" in msg
    assert SCHEMA_VERSION in msg


def test_old_schema_version_2_1_raises():
    """Schema 2.1 is rejected. Stale workspaces that still carry the
    retired ``output_mode`` / ``backup_*`` knobs fail loud at load
    so the operator re-inits."""
    with pytest.raises(ValidationError) as excinfo:
        ProjectConfig.model_validate({"schema_version": "2.1"})
    msg = str(excinfo.value)
    assert "2.1" in msg
    assert SCHEMA_VERSION in msg


# ---------------------------------------------------------------------------
# extra="forbid" surfacing typos
# ---------------------------------------------------------------------------


def test_typo_in_top_level_key_raises():
    """Top-level typos (e.g. ``optoins``) must fail validation."""
    bad = {
        "schema_version": SCHEMA_VERSION,
        "optoins": {},  # typo
    }
    with pytest.raises(ValidationError) as excinfo:
        ProjectConfig.model_validate(bad)
    assert "optoins" in str(excinfo.value).lower() or "extra" in str(excinfo.value).lower()


def test_typo_under_paths_raises():
    """A typo under ``paths`` (e.g. ``arxlm_file``) must fail."""
    bad = {"schema_version": SCHEMA_VERSION, "paths": {"arxlm_file": "foo.arxml"}}
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(bad)


def test_any_key_under_options_raises():
    """v1.27.0: ``options`` is empty by design — any inner key
    (typo or stale knob) must trip the ``extra='forbid'`` guard."""
    bad = {"schema_version": SCHEMA_VERSION, "options": {"newfangled_knob": 10}}
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(bad)


# ---------------------------------------------------------------------------
# Constraint-level validation (schema_version pin)
# ---------------------------------------------------------------------------


def test_unknown_schema_version_raises():
    """Unknown future versions fail loudly until a migrator is added."""
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({"schema_version": "9.99"})


# ---------------------------------------------------------------------------
# Round-trip + loader I/O
# ---------------------------------------------------------------------------


@pytest.fixture
def canonical_project_config_dict() -> dict:
    """The exact dict shape ``--init-project`` emits as of v1.27.0."""
    return {
        "schema_version": SCHEMA_VERSION,
        "paths": {
            "base_dir": "/workspace",
            "pdm_file": "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/cfg/RBDCOM_Customer.pdm",
            "config_h": "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/api/RBAPLCUST_Config.h",
            "config_elements_h": "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/api/RBAPLCUST_ConfigElements.h",
            "config_settings_h": "Fe_Super/rb/as/rbcn/{product_type_lower}/dcompr/cfg/RBDCOM_ConfigSettings.h",
            "c_output_subdir": "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/src/{product_type_upper}",
            "arxml_file": "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/cfg/{product_type_upper}/Dcm_CusDiag_Services_EcucValues_{product_type_suffix}.arxml",
        },
        "options": {},
    }


def test_canonical_dict_loads_cleanly(canonical_project_config_dict):
    """The shape ``--init-project`` writes must validate cleanly."""
    config = ProjectConfig.model_validate(canonical_project_config_dict)
    assert config.schema_version == SCHEMA_VERSION
    assert config.paths.arxml_file.endswith(
        "Dcm_CusDiag_Services_EcucValues_{product_type_suffix}.arxml"
    )
    # options is empty in v1.27.0; the canonical config carries
    # an empty dict and round-trips cleanly.
    assert config.options.model_dump() == {}


def test_roundtrip_via_save_then_load(tmp_path, canonical_project_config_dict):
    """save → load must be lossless for the canonical shape."""
    config = ProjectConfig.model_validate(canonical_project_config_dict)
    target = tmp_path / "project.json"
    save_project_config(target, config)
    reloaded = load_project_config(target)
    assert reloaded.model_dump() == config.model_dump()


def test_save_uses_two_space_indent_and_trailing_newline(tmp_path):
    """Diff hygiene: indent=2, sort_keys=True, trailing newline.

    The serialised ``schema_version`` is the current
    :data:`SCHEMA_VERSION` (``"2.2"`` as of v1.27.0).
    """
    config = ProjectConfig()
    target = tmp_path / "project.json"
    save_project_config(target, config)
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    parsed = json.loads(text)
    assert parsed["schema_version"] == SCHEMA_VERSION
    # sort_keys=True implies top-level keys appear alphabetically.
    assert list(parsed.keys()) == sorted(parsed.keys())


# ---------------------------------------------------------------------------
# Schema 2.2: paths.per_product overrides (unchanged from 2.1)
# ---------------------------------------------------------------------------


def test_per_product_empty_dict_is_default():
    """Absent ``per_product`` block defaults to ``{}`` so existing
    callers don't need to pre-flatten the field."""
    cfg = ProjectConfig.model_validate({
        "schema_version": SCHEMA_VERSION,
        "paths": {"base_dir": "/ws"},
    })
    assert cfg.paths.per_product == {}


def test_per_product_accepts_null_skip_sentinel():
    """``null`` value pins this (PT, key) as ``SKIP``: no Bosch
    mirror. The schema must accept it cleanly."""
    cfg = ProjectConfig.model_validate({
        "schema_version": SCHEMA_VERSION,
        "paths": {
            "per_product": {
                "ESPCL": {"arxml_file": None},
                "Common": {"config_settings_h": None},
            },
        },
    })
    assert cfg.paths.per_product["ESPCL"]["arxml_file"] is None
    assert cfg.paths.per_product["Common"]["config_settings_h"] is None


def test_per_product_accepts_string_override():
    """Non-empty string pins this (PT, key) to a literal Bosch
    mirror destination, bypassing the placeholder template."""
    override = "Fe_Super/rb/as/rbcn/ipb/dcompr/cfg/RBDCOM_ConfigSettings_IPB.h"
    cfg = ProjectConfig.model_validate({
        "schema_version": SCHEMA_VERSION,
        "paths": {
            "per_product": {
                "IPB": {"config_settings_h": override},
            },
        },
    })
    assert cfg.paths.per_product["IPB"]["config_settings_h"] == override


def test_per_product_unknown_pt_key_raises():
    """Outer key must be in the recognised whitelist (DPB / ESP /
    ESPCL / IPB / RBU / Common) — typo fails loud at load."""
    with pytest.raises(ValidationError) as excinfo:
        ProjectConfig.model_validate({
            "schema_version": SCHEMA_VERSION,
            "paths": {"per_product": {"DPC": {"arxml_file": None}}},
        })
    msg = str(excinfo.value)
    assert "DPC" in msg


def test_per_product_lowercase_pt_key_raises():
    """Outer key spelling is canonical: ``Common`` (title-case),
    ``ESP`` (upper-case). ``common`` / ``esp`` must fail."""
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({
            "schema_version": SCHEMA_VERSION,
            "paths": {"per_product": {"common": {"arxml_file": None}}},
        })


def test_per_product_unknown_inner_key_raises():
    """Inner key must be one of the six recognised path keys.
    ``base_dir`` is intentionally excluded — typo or attempted
    per-product base_dir override both fail."""
    with pytest.raises(ValidationError) as excinfo:
        ProjectConfig.model_validate({
            "schema_version": SCHEMA_VERSION,
            "paths": {"per_product": {"ESP": {"base_dir": "/x"}}},
        })
    assert "base_dir" in str(excinfo.value)


def test_per_product_empty_string_override_raises():
    """Empty string is ambiguous (skip vs. override-to-nowhere).
    The schema forces operators to be explicit: ``null`` for skip,
    non-empty string for override."""
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({
            "schema_version": SCHEMA_VERSION,
            "paths": {"per_product": {"ESP": {"arxml_file": ""}}},
        })


def test_per_product_int_override_raises():
    """Inner value must be ``null`` or ``str``; other types raise."""
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({
            "schema_version": SCHEMA_VERSION,
            "paths": {"per_product": {"ESP": {"arxml_file": 42}}},
        })


def test_per_product_roundtrips_through_save_load(tmp_path):
    """v1.22.0 round-trip: a config with ``per_product`` overrides
    must save and reload identically."""
    target = tmp_path / "with_overrides.json"
    cfg_in = ProjectConfig.model_validate({
        "schema_version": SCHEMA_VERSION,
        "paths": {
            "base_dir": "/ws",
            "per_product": {
                "ESPCL": {"arxml_file": None},
                "IPB": {"config_settings_h": "/abs/RBDCOM_ConfigSettings_IPB.h"},
                "Common": {"config_settings_h": None},
            },
        },
    })
    save_project_config(target, cfg_in)
    cfg_out = load_project_config(target)
    assert cfg_out.paths.per_product == cfg_in.paths.per_product


def test_load_returns_defaults_on_missing_file(tmp_path):
    """Missing ``config/project.json`` is a valid posture, not an error."""
    config = load_project_config(tmp_path / "absent.json")
    assert isinstance(config, ProjectConfig)
    assert config.options.model_dump() == {}


def test_load_returns_defaults_on_empty_file(tmp_path):
    """Empty file (zero bytes / whitespace only) loads as defaults."""
    target = tmp_path / "empty.json"
    target.write_text("   \n", encoding="utf-8")
    config = load_project_config(target)
    assert isinstance(config, ProjectConfig)


def test_load_raises_value_error_on_bad_json(tmp_path):
    """Invalid JSON → :class:`ValueError` with line/col info."""
    target = tmp_path / "bad.json"
    target.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_project_config(target)
    msg = str(excinfo.value)
    assert "bad.json" in msg
    assert "line" in msg and "column" in msg


def test_load_raises_validation_error_on_bad_shape(tmp_path):
    """Valid JSON with disallowed extras → :class:`ValidationError`."""
    target = tmp_path / "bad_shape.json"
    target.write_text(
        json.dumps({
            "schema_version": SCHEMA_VERSION,
            # v1.27.0: options is now extra='forbid' empty; any
            # stale knob is a load-time failure.
            "options": {"output_mode": "outputs"},
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_project_config(target)


def test_load_raises_validation_error_on_old_schema_version(tmp_path):
    """Pre-release skill: a stored ``schema_version: "2.0"`` (or any
    other prior shape) must hard-fail at load — no migration shim."""
    target = tmp_path / "old.json"
    target.write_text(
        json.dumps({
            "schema_version": "2.0",
            "paths": {"base_dir": "/x"},
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as excinfo:
        load_project_config(target)
    msg = str(excinfo.value)
    assert "2.0" in msg
