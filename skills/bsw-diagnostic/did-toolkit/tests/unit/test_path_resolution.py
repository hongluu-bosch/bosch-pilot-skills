"""Unit tests for product_type_lower / resolve_path placeholder rules.

These helpers decide where Phase 3 mirrors generated artefacts into the
real Bosch code tree. Regressions here would silently misroute writes,
so we pin both the mapping precedence and the placeholder substitution
rules — including the v1.21.0 ``Common`` wildcard rules and the
``{product_type_suffix}`` placeholder.

History:

* v1.19.0 cull dropped ``config['product_type_mapping']`` (config-level
  override) and ``{customer_name}`` (placeholder).
* v1.21.0 fan-out reshaped Common handling: a build-target of
  ``Common`` collapses ``{product_type}`` /
  ``{product_type_lower}`` / ``{product_type_upper}`` to the literal
  ``Common`` (matching the Bosch tree's ``cfg/Common/`` /
  ``src/Common/`` directories), and a new
  ``{product_type_suffix}`` placeholder maps Common → ``SingleCANID``
  (so a single ``arxml_file`` template covers both
  ``Dcm_CusDiag_Services_EcucValues_<PT>.arxml`` and
  ``Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from generate_implementation import ImplementationGenerator
from implementation.paths import (
    COMMON_TOKEN,
    MirrorResolution,
    product_type_arxml_folder,
    product_type_suffix,
    product_type_upper,
    resolve_mirror_path,
    resolve_path,
)


@pytest.fixture
def gen() -> ImplementationGenerator:
    return ImplementationGenerator(config={})


class TestProductTypeLower:
    def test_canonical_five_products(self, gen):
        assert gen._product_type_lower("ESP") == "esp10"
        assert gen._product_type_lower("DPB") == "dpb"
        assert gen._product_type_lower("ESPCL") == "esp10cl"
        assert gen._product_type_lower("IPB") == "ipb"
        assert gen._product_type_lower("RBU") == "rbu"

    def test_unknown_product_type_lowercases(self, gen):
        assert gen._product_type_lower("XYZ") == "xyz"

    def test_empty_returns_empty(self, gen):
        assert gen._product_type_lower("") == ""

    def test_config_supplied_mapping_no_longer_overrides(self):
        """v1.19.0 cull pin: the runtime ``product_type_mapping``
        override mechanism was removed. Even if a (forbidden)
        config snuck the field in, the helper must still return
        the hard-coded canonical value."""
        gen = ImplementationGenerator(config={
            "product_type_mapping": {"ESP": "custom_esp"},
        })
        assert gen._product_type_lower("ESP") == "esp10"

    def test_common_wildcard_collapses_to_titlecase_literal(self, gen):
        """v1.21.0 pin: a ``Common`` build target must lower-resolve
        to the title-case literal ``'Common'`` so ``cfg/Common/``
        path segments match Bosch's actual directory naming
        (``cfg/COMMON/`` / ``cfg/common/`` would not exist)."""
        assert gen._product_type_lower("Common") == COMMON_TOKEN
        assert gen._product_type_lower("common") == COMMON_TOKEN
        assert gen._product_type_lower("COMMON") == COMMON_TOKEN


class TestProductTypeUpper:
    """v1.21.0 helper covering the upper-case + Common short-circuit."""

    def test_canonical_five_products(self):
        assert product_type_upper("ESP") == "ESP"
        assert product_type_upper("dpb") == "DPB"
        assert product_type_upper("Espcl") == "ESPCL"

    def test_empty_returns_empty(self):
        assert product_type_upper("") == ""

    def test_common_collapses_to_titlecase_literal(self):
        assert product_type_upper("Common") == COMMON_TOKEN
        assert product_type_upper("common") == COMMON_TOKEN
        assert product_type_upper("COMMON") == COMMON_TOKEN


class TestProductTypeSuffix:
    """v1.21.0 ``{product_type_suffix}`` placeholder helper."""

    def test_real_products_match_uppercase(self):
        # For every per-product build, the ARXML filename suffix is
        # the upper-case short name — same as ``{product_type_upper}``.
        for pt in ("DPB", "ESP", "ESPCL", "IPB", "RBU"):
            assert product_type_suffix(pt) == pt

    def test_real_products_case_insensitive(self):
        # Operators sometimes write ``dpb`` / ``Esp`` in the CSV.
        # The suffix must still be canonical upper-case.
        assert product_type_suffix("dpb") == "DPB"
        assert product_type_suffix("Esp") == "ESP"

    def test_common_maps_to_singlecanid(self):
        # Bosch's ``cfg/Common/Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml``
        # naming is the load-bearing reason this placeholder exists.
        assert product_type_suffix("Common") == "SingleCANID"
        assert product_type_suffix("common") == "SingleCANID"
        assert product_type_suffix("COMMON") == "SingleCANID"

    def test_empty_returns_empty(self):
        assert product_type_suffix("") == ""


class TestProductTypeArxmlFolder:
    """v1.24.0 ``{product_type_arxml_folder}`` placeholder helper.

    The Phase-2 ESPCL → ESP path alias collapses ESPCL's folder
    name to ``ESP`` so its ARXML lands in ``cfg/ESP/`` next to ESP's
    own. Every other PT keeps the upper-case canonical short name
    (matching the ``{product_type_upper}`` placeholder for Phase 3).
    """

    def test_alias_source_collapses_to_target(self):
        assert product_type_arxml_folder("ESPCL") == "ESP"

    def test_alias_source_case_insensitive(self):
        for spelling in ("ESPCL", "espcl", "EspCl"):
            assert product_type_arxml_folder(spelling) == "ESP"

    def test_non_alias_matches_upper(self):
        for pt in ("DPB", "ESP", "IPB", "RBU"):
            assert product_type_arxml_folder(pt) == pt

    def test_lower_input_canonicalises(self):
        assert product_type_arxml_folder("dpb") == "DPB"
        assert product_type_arxml_folder("rbu") == "RBU"

    def test_common_titlecase(self):
        assert product_type_arxml_folder("Common") == COMMON_TOKEN
        assert product_type_arxml_folder("common") == COMMON_TOKEN

    def test_empty_returns_empty(self):
        assert product_type_arxml_folder("") == ""


class TestResolvePath:
    def test_substitutes_product_type_lower_alias(self, gen):
        out = gen._resolve_path(
            "Fe_Super/rb/as/rbcn/{product_type_lower}/cfg", product_type="ESP"
        )
        assert out == Path("Fe_Super/rb/as/rbcn/esp10/cfg")

    def test_substitutes_product_type_alias(self, gen):
        out = gen._resolve_path(
            "cfg/{product_type}/settings.h", product_type="DPB"
        )
        assert out == Path("cfg/dpb/settings.h")

    def test_substitutes_product_type_upper(self, gen):
        out = gen._resolve_path(
            "src/{product_type_upper}/file.c", product_type="dpb"
        )
        assert out == Path("src/DPB/file.c")

    def test_substitutes_product_type_suffix_for_real_product(self, gen):
        # New v1.21.0 placeholder: real products ⇒ same as upper.
        out = gen._resolve_path(
            "cfg/{product_type_upper}/Dcm_CusDiag_Services_EcucValues_{product_type_suffix}.arxml",
            product_type="DPB",
        )
        assert out == Path(
            "cfg/DPB/Dcm_CusDiag_Services_EcucValues_DPB.arxml"
        )

    def test_substitutes_product_type_arxml_folder_for_alias_source(self, gen):
        # v1.24.0 path-alias placeholder: ESPCL collapses to ESP so
        # the resulting Bosch path lands in ``cfg/ESP/``, with the
        # ``{product_type_suffix}`` keeping the per-PT
        # ``..._ESPCL.arxml`` filename so ESP's own ARXML isn't
        # overwritten.
        out = gen._resolve_path(
            "cfg/{product_type_arxml_folder}/"
            "Dcm_CusDiag_Services_EcucValues_{product_type_suffix}.arxml",
            product_type="ESPCL",
        )
        assert out == Path(
            "cfg/ESP/Dcm_CusDiag_Services_EcucValues_ESPCL.arxml"
        )

    def test_substitutes_product_type_arxml_folder_for_non_alias(self, gen):
        # Non-alias PT: behaves exactly like ``{product_type_upper}``.
        out = gen._resolve_path(
            "cfg/{product_type_arxml_folder}/x.arxml", product_type="DPB",
        )
        assert out == Path("cfg/DPB/x.arxml")

    def test_substitutes_product_type_arxml_folder_for_common(self, gen):
        out = gen._resolve_path(
            "cfg/{product_type_arxml_folder}/x.arxml", product_type="Common",
        )
        assert out == Path("cfg/Common/x.arxml")

    def test_no_product_type_leaves_product_placeholders(self, gen):
        # Without product_type, product placeholders should remain so
        # the caller notices something was missing.
        out = gen._resolve_path("{product_type}/x")
        assert str(out) in ("{product_type}/x", "{product_type}\\x")

    def test_customer_name_placeholder_no_longer_substituted(self, gen):
        """v1.19.0 cull pin: ``{customer_name}`` is no longer a
        recognised placeholder. The literal token must survive
        verbatim into the resolved path so a stale template is
        visibly broken instead of silently resolving to ``""``."""
        out = gen._resolve_path("{customer_name}/x", product_type="DPB")
        assert str(out) in ("{customer_name}/x", "{customer_name}\\x")


class TestResolvePathCommonWildcard:
    """v1.21.0 — Common build-target end-to-end placeholder rules.

    Pinning the ``cfg/Common/`` + ``SingleCANID`` filename layout
    that Bosch's actual tree uses, so a Common fan-out produces
    paths that overlay the existing Bosch artefacts on mirror.
    """

    def test_common_collapses_path_segment_placeholders_to_literal(self):
        out = resolve_path(
            None,
            "src/{product_type_upper}/file.c",
            product_type="Common",
        )
        assert out == Path("src/Common/file.c")

    def test_common_collapses_lower_alias_to_literal(self):
        # ``{product_type_lower}`` is meant for short-form (``esp10``),
        # but under Common we still want title-case ``Common`` so a
        # ``cfg/{product_type_lower}/...`` template stays correct.
        out = resolve_path(
            None,
            "cfg/{product_type_lower}/CanTp_CusDiag_EcucValues.arxml",
            product_type="Common",
        )
        assert out == Path("cfg/Common/CanTp_CusDiag_EcucValues.arxml")

    def test_common_collapses_short_alias_to_literal(self):
        out = resolve_path(
            None, "cfg/{product_type}/x", product_type="Common"
        )
        assert out == Path("cfg/Common/x")

    def test_common_arxml_filename_suffix(self):
        # The combined-template scenario the placeholder was added for:
        # path segment + filename suffix in one go.
        out = resolve_path(
            None,
            "cfg/{product_type_upper}/Dcm_CusDiag_Services_EcucValues_{product_type_suffix}.arxml",
            product_type="Common",
        )
        assert out == Path(
            "cfg/Common/Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml"
        )

    def test_common_case_insensitive_input_still_titlecase_output(self):
        # CSV operators may type ``common`` / ``COMMON``; the resolved
        # path must always be title-case.
        for spelling in ("common", "COMMON", "CoMmOn"):
            out = resolve_path(
                None, "src/{product_type_upper}/", product_type=spelling
            )
            assert out == Path("src/Common/")

    def test_literal_path_with_no_placeholders_passes_through(self):
        # An operator who hand-edited paths.* to a fully-resolved path
        # (no placeholders) must still be honoured verbatim.
        out = resolve_path(
            None,
            "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/cfg/Common/foo.arxml",
            product_type="Common",
        )
        assert out == Path(
            "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/cfg/Common/foo.arxml"
        )


# ---------------------------------------------------------------------------
# v1.22.0: resolve_mirror_path — per_product overrides + skip sentinel
# ---------------------------------------------------------------------------


class TestResolveMirrorPathTemplateFallback:
    """Without ``per_product`` overrides, the resolver behaves
    exactly like v1.21.0: expand the top-level template."""

    def _config(self, **paths) -> dict:
        return {"paths": {**paths}}

    def test_template_expanded_when_no_per_product(self):
        cfg = self._config(
            arxml_file="cfg/{product_type_upper}/Dcm_..._EcucValues_{product_type_suffix}.arxml",
        )
        out, verdict = resolve_mirror_path(cfg, "arxml_file", "DPB")
        assert verdict is MirrorResolution.TEMPLATE
        assert out == Path("cfg/DPB/Dcm_..._EcucValues_DPB.arxml")

    def test_unset_when_template_empty(self):
        cfg = self._config(arxml_file="")
        out, verdict = resolve_mirror_path(cfg, "arxml_file", "DPB")
        assert verdict is MirrorResolution.UNSET
        assert out is None

    def test_unset_when_paths_block_missing(self):
        out, verdict = resolve_mirror_path({}, "arxml_file", "DPB")
        assert verdict is MirrorResolution.UNSET
        assert out is None

    def test_unset_when_config_is_none(self):
        out, verdict = resolve_mirror_path(None, "arxml_file", "DPB")
        assert verdict is MirrorResolution.UNSET
        assert out is None

    def test_template_for_common_uses_singlecanid_suffix(self):
        cfg = self._config(
            arxml_file="cfg/{product_type_upper}/Dcm_..._EcucValues_{product_type_suffix}.arxml",
        )
        out, verdict = resolve_mirror_path(cfg, "arxml_file", "Common")
        assert verdict is MirrorResolution.TEMPLATE
        assert out == Path("cfg/Common/Dcm_..._EcucValues_SingleCANID.arxml")


class TestResolveMirrorPathSkipSentinel:
    """``paths.per_product.<PT>.<key> = null`` returns SKIP and ``None``
    so the caller can short-circuit before touching ``base_dir``."""

    def test_explicit_null_for_arxml_file_returns_skip(self):
        cfg = {
            "paths": {
                "arxml_file": "cfg/{product_type_upper}/foo.arxml",
                "per_product": {"ESPCL": {"arxml_file": None}},
            },
        }
        out, verdict = resolve_mirror_path(cfg, "arxml_file", "ESPCL")
        assert verdict is MirrorResolution.SKIP
        assert out is None

    def test_skip_takes_priority_over_template(self):
        # Even when the top-level template would have produced a
        # perfectly valid path, an explicit per_product null wins.
        cfg = {
            "paths": {
                "arxml_file": "cfg/{product_type_upper}/foo.arxml",
                "per_product": {"DPB": {"arxml_file": None}},
            },
        }
        out, verdict = resolve_mirror_path(cfg, "arxml_file", "DPB")
        assert verdict is MirrorResolution.SKIP
        assert out is None

    def test_skip_only_affects_named_pt_and_key(self):
        # ``per_product.ESPCL.arxml_file = null`` must NOT skip
        # ESPCL's other keys nor any other PT's arxml_file.
        cfg = {
            "paths": {
                "arxml_file": "cfg/{product_type_upper}/foo.arxml",
                "config_settings_h": "cfg/{product_type_lower}/RBDCOM_ConfigSettings.h",
                "per_product": {"ESPCL": {"arxml_file": None}},
            },
        }
        # DPB unaffected
        _, dpb_verdict = resolve_mirror_path(cfg, "arxml_file", "DPB")
        assert dpb_verdict is MirrorResolution.TEMPLATE
        # ESPCL config_settings_h unaffected (template still expands)
        _, espcl_settings = resolve_mirror_path(cfg, "config_settings_h", "ESPCL")
        assert espcl_settings is MirrorResolution.TEMPLATE


class TestResolveMirrorPathOverride:
    """Non-empty string under ``per_product`` redirects the mirror to
    a literal path, bypassing the placeholder template entirely."""

    def test_string_override_returns_override_verdict(self):
        cfg = {
            "paths": {
                "config_settings_h": "{product_type_lower}/dcompr/cfg/RBDCOM_ConfigSettings.h",
                "per_product": {
                    "IPB": {
                        "config_settings_h": "ipb/dcompr/cfg/RBDCOM_ConfigSettings_IPB.h",
                    },
                },
            },
        }
        out, verdict = resolve_mirror_path(cfg, "config_settings_h", "IPB")
        assert verdict is MirrorResolution.OVERRIDE
        assert out == Path("ipb/dcompr/cfg/RBDCOM_ConfigSettings_IPB.h")

    def test_override_with_no_placeholders_passes_through_verbatim(self):
        cfg = {
            "paths": {
                "config_settings_h": "ANY/{product_type_lower}/foo.h",
                "per_product": {
                    "IPB": {"config_settings_h": "/abs/path/no_placeholders.h"},
                },
            },
        }
        out, _ = resolve_mirror_path(cfg, "config_settings_h", "IPB")
        # Literal — placeholders inside per_product values are NOT expanded.
        assert out == Path("/abs/path/no_placeholders.h")


class TestResolveMirrorPathCanonicalisation:
    """``per_product`` keys are canonicalised: ``"common"`` /
    ``"COMMON"`` / ``"Common"`` all match a ``Common`` entry."""

    def test_lower_case_pt_input_finds_common_entry(self):
        cfg = {
            "paths": {
                "config_settings_h": "{product_type_lower}/foo.h",
                "per_product": {"Common": {"config_settings_h": None}},
            },
        }
        # Operator wrote "common" (lower) but per_product key is "Common"
        # (canonical title-case). The resolver still finds the entry.
        _, verdict = resolve_mirror_path(cfg, "config_settings_h", "common")
        assert verdict is MirrorResolution.SKIP

    def test_upper_case_pt_input_finds_canonical_entry(self):
        cfg = {
            "paths": {
                "arxml_file": "cfg/{product_type_upper}/foo.arxml",
                "per_product": {"DPB": {"arxml_file": None}},
            },
        }
        _, verdict = resolve_mirror_path(cfg, "arxml_file", "dpb")
        assert verdict is MirrorResolution.SKIP
