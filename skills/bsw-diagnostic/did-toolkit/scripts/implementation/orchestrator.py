"""High-level orchestrator that wires all the split helpers together.

Structural contract:

1. **Project tree is the sole sink.** Phase 3 writes directly into
   the Bosch project tree resolved via ``paths.base_dir`` +
   ``paths.c_output_subdir`` / etc. ``.DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/``
   keeps only reports (``validation_report.txt`` etc.). Phase 3
   hard-aborts when ``paths.base_dir`` (or the relevant per-key
   template) is missing — running Phase 3 without a Bosch target is a
   workspace-misconfiguration, not a degraded mode.
2. **Skip-on-conflict.** ``.c`` files use skip-if-exists. Headers
   (Config.h / ConfigSettings.h / ConfigElements.h) dedup at the
   macro level (existing ``#define`` lines are preserved; only new
   macros are spliced in). PDM merges keep existing entries; new
   entries are appended. Nothing is ever overwritten, so there is
   no rolling-backup mechanism — the pre-existing file IS the backup.
3. **Inline agent TODO blocks.** Each non-EEPROM ``.c`` stub carries
   the agent-fill prompt inline (see
   :func:`scripts.implementation.generators._build_inline_todo_block`),
   so Phase 3 can frame + fill in one continuous agent turn.

The public method surface (``generate`` / ``generate_from_dids``)
stays the same modulo the dropped ``output_mode`` kwarg so external
callers that don't pass it churn-free.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import DIDImplementationInfo
from .naming import (
    FS_MACRO_PREFIX,
    NVM_ID_PREFIX,
    capitalize_first,
    clean_name,
    get_fs_macro,
    get_func_name,
    get_nvm_id,
    get_range_macro_name,
)
from .parsers import (
    parse_enum_values,
    parse_numeric_range,
)
from fscs import load_fscs, to_did_implementation_infos
from .paths import (
    MirrorResolution,
    product_type_lower,
    resolve_mirror_path,
    resolve_path,
)
from .safety import guarded_project_write
from . import generators as gen


class ImplementationGenerator:
    """Generate implementation artifacts from FSCS.

    State owned by this class:

    * ``config``            -- project.json as a dict (optional)
    * ``fs_prefix``/``nvm_prefix``/``writecycles`` -- Bosch-flavored knobs

    Everything else delegates to pure module-level helpers so they can be
    reused / tested in isolation. The method surface mirrors the legacy
    flat file so no caller code has to change.
    """

    FS_MACRO_PREFIX = FS_MACRO_PREFIX
    NVM_ID_PREFIX = NVM_ID_PREFIX
    WRITECYCLES_DEFAULT = 1000

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.fs_prefix = self.FS_MACRO_PREFIX
        self.nvm_prefix = self.NVM_ID_PREFIX
        self.writecycles = self.WRITECYCLES_DEFAULT

    # ------------------------------- Naming --------------------------------

    def _clean_name(self, name: str) -> str:
        return clean_name(name)

    def _capitalize_first(self, name: str) -> str:
        return capitalize_first(name)

    def _get_fs_macro(self, did_name: str) -> str:
        return get_fs_macro(did_name, fs_prefix=self.fs_prefix)

    def _get_nvm_id(self, nvm_item: str) -> str:
        return get_nvm_id(nvm_item)

    def _get_range_macro_name(self, did_hex: str, suffix: str) -> str:
        return get_range_macro_name(did_hex, suffix)

    def _get_func_name(self, did: DIDImplementationInfo) -> str:
        return get_func_name(did)

    # ----------------- Value-range parsers (pure helpers) ------------------

    def _parse_enum_values(self, value_range: str) -> List[str]:
        return parse_enum_values(value_range)

    def _parse_numeric_range(self, value_range: str) -> Tuple[str, str]:
        return parse_numeric_range(value_range)

    # --------------------------- FSCS loading ------------------------------

    def load_dids(
        self,
        fscs_json_path: Path,
    ) -> Tuple[List[DIDImplementationInfo], List[Dict]]:
        """Load Phase 3 inputs from the authoritative ``fscs.json``."""
        document = load_fscs(fscs_json=fscs_json_path)
        return to_did_implementation_infos(document)

    # ----------------------------- Generators ------------------------------

    def generate_pdm_entry(self, did: DIDImplementationInfo) -> str:
        return gen.generate_pdm_entry(did, writecycles=self.writecycles,
                                      fs_prefix=self.fs_prefix)

    def generate_config_macro(self, did: DIDImplementationInfo) -> str:
        return gen.generate_config_macro(did, fs_prefix=self.fs_prefix)

    def generate_config_settings_macro(self, did: DIDImplementationInfo) -> str:
        return gen.generate_config_settings_macro(did, fs_prefix=self.fs_prefix)

    def generate_element_defs(self, did: DIDImplementationInfo) -> str:
        return gen.generate_element_defs(did, fs_prefix=self.fs_prefix)

    def generate_range_macros(self, did: DIDImplementationInfo) -> str:
        return gen.generate_range_macros(did)

    def _generate_enum_conditions(self, did: DIDImplementationInfo) -> str:
        return gen.generate_enum_conditions(did)

    def _build_read_func_body(self, did: DIDImplementationInfo, fs_macro: str,
                              func_name_only: str) -> str:
        return gen._build_read_func_body(did, fs_macro, func_name_only)

    def generate_read_code(self, did: DIDImplementationInfo) -> str:
        return gen.generate_read_code(did, fs_prefix=self.fs_prefix)

    def generate_did_header(self, did: DIDImplementationInfo) -> str:
        return gen.generate_did_header(did)

    def _build_write_func_body(self, did: DIDImplementationInfo, fs_macro: str,
                               nvm_id: str, mode: str) -> str:
        return gen._build_write_func_body(did, fs_macro, nvm_id, mode)

    def _build_write_value_range_block(self, did: DIDImplementationInfo,
                                       mode: str) -> str:
        return gen._build_write_value_range_block(did, mode)

    def generate_write_code(self, did: DIDImplementationInfo) -> str:
        return gen.generate_write_code(did, fs_prefix=self.fs_prefix)

    # ----------------------------- Safety ----------------------------------

    def _guarded_project_write(self, path: Path, content: str,
                               dry_run: bool, action: str) -> bool:
        return guarded_project_write(path, content, dry_run, action)

    # ------------------------------- Paths ---------------------------------

    def _product_type_lower(self, product_type: str) -> str:
        return product_type_lower(self.config, product_type)

    def _resolve_path(self, path_template: str,
                      product_type: Optional[str] = None) -> Path:
        return resolve_path(self.config, path_template, product_type=product_type)

    # ------------------------- Header merge helpers ------------------------

    def _extract_existing_macros(self, content: str) -> set:
        """Extract ``#define`` names already present in a header file."""
        return set(re.findall(r'#define\s+(\w+)', content))

    def _find_insert_position(self, content: str) -> int:
        """Find where to splice new macros: right before the closing ``#endif``."""
        lines = content.split('\n')
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip().startswith('#endif'):
                return sum(len(lines[j]) + 1 for j in range(i))
        return len(content)

    def _merge_header_content(self, existing_content: str, new_content: str,
                              existing_macros: Optional[set] = None) -> tuple:
        """Merge new macros into existing header content. Returns
        ``(merged, inserted_count, skipped_count)``."""
        if existing_macros is None:
            existing_macros = self._extract_existing_macros(existing_content)

        new_lines: List[str] = []
        skipped_count = 0
        for line in new_content.split('\n'):
            match = re.match(r'#define\s+(\w+)', line)
            if match:
                if match.group(1) not in existing_macros:
                    new_lines.append(line)
                else:
                    skipped_count += 1
            else:
                new_lines.append(line)

        if not new_lines:
            return existing_content, 0, skipped_count

        insert_pos = self._find_insert_position(existing_content)
        filtered_content = '\n'.join(new_lines)
        merged = (existing_content[:insert_pos]
                  + '\n' + filtered_content + '\n'
                  + existing_content[insert_pos:])
        inserted_count = len(
            [l for l in new_lines if l.strip().startswith('#define')]
        )
        return merged, inserted_count, skipped_count

    # ---------------------- Main generation pipeline -----------------------

    def generate_from_dids(self, dids: List[DIDImplementationInfo],
                           output_dir: Path,
                           product_type: Optional[str] = None,
                           dry_run: bool = False) -> Dict[str, Any]:
        """Generate all implementation artifacts from a list of DID info.

        Output contract:

        * ``output_dir`` is the **reports root**
          (``.DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/``) — only the
          validation / generation reports land there, no source files.
        * Generated ``.c`` / headers / PDM are written **only** to the
          Bosch project tree resolved via ``paths.*`` for ``product_type``.
        * Hard-fails (raises ``RuntimeError``) when ``paths.base_dir``
          is missing / non-existent OR when every per-product mirror key
          is skipped (nothing to write).
        * Skip-on-conflict: existing ``.c`` files are kept, headers
          gain only new ``#define`` lines, PDM appends. Skip events
          are surfaced in the returned stats so the caller can roll
          them into ``generation_report.txt``.
        """
        print(f"Processing {len(dids)} DIDs for implementation generation")
        if product_type:
            print(f"Product Type: {product_type}")
        if dry_run:
            print("Dry Run:      ON (project-tree writes will be skipped)")

        # ``output_dir`` is the *report* anchor — only validation /
        # generation reports land here in v1.27.0. The legacy local
        # mirror subdirs (c_code / headers / pdms) are no longer
        # created.
        output_dir.mkdir(parents=True, exist_ok=True)

        base_dir = self.config.get('paths', {}).get('base_dir', '') \
            if isinstance(self.config, dict) else ''
        base_dir_path = Path(base_dir) if base_dir else None
        base_dir_exists = bool(base_dir_path and base_dir_path.exists())

        if not product_type:
            raise RuntimeError(
                "Phase 3 v1.27.0 requires a product_type to resolve "
                "the Bosch-tree mirror paths; got None. The fan-out "
                "loop in pipeline.run_phase3 always passes one — this "
                "code path indicates a broken caller."
            )
        if not base_dir_path:
            raise RuntimeError(
                "Phase 3 v1.27.0 writes directly into the Bosch project "
                "tree but paths.base_dir is empty in project.json. "
                "Set it to the absolute path of the project container "
                "(the directory holding the Bosch BSW tree) or re-run "
                "`pipeline.py --init-project` to scaffold a fresh "
                "config."
            )
        if not base_dir_exists:
            raise RuntimeError(
                f"Phase 3 v1.27.0: paths.base_dir does not exist on "
                f"disk: {base_dir!r}. Fix the path in "
                ".DCOM_AI/DID_Toolkit_PRJ/config/project.json (or re-init the workspace)."
            )

        # Resolve the six per-key mirror destinations through the
        # v1.22.0 ``paths.per_product`` overrides + skip sentinel.
        actual_paths: Dict[str, Path] = {}
        skip_keys: set = set()
        _MIRROR_KEY_ALIAS = {
            'pdm_file': 'pdm',
            'config_h': 'config_h',
            'config_elements_h': 'config_elements_h',
            'config_settings_h': 'config_settings_h',
            'c_output_subdir': 'c_output_dir',
        }
        for schema_key, alias in _MIRROR_KEY_ALIAS.items():
            resolved, verdict = resolve_mirror_path(
                self.config, schema_key, product_type,
            )
            if verdict is MirrorResolution.SKIP:
                skip_keys.add(schema_key)
                print(
                    f"[SKIP] paths.per_product.{product_type}.{schema_key}"
                    f" = null — no Bosch target for this artefact."
                )
                continue
            if verdict is MirrorResolution.UNSET:
                # Template absent / empty — treat the same as SKIP for
                # this artefact (the operator may not have a Bosch
                # target for it). Phase 3 keeps going with whatever IS
                # resolved.
                skip_keys.add(schema_key)
                print(
                    f"[SKIP] paths.{schema_key} is empty in project.json — "
                    f"no Bosch target configured for {product_type}."
                )
                continue
            if resolved is not None:
                actual_paths[alias] = base_dir_path / resolved
        print(f"[PROJECT TREE] base_dir = {base_dir_path}")

        # Track skip events for the generation report.
        report: Dict[str, List[str]] = {
            'c_skipped_existing': [],
            'pdm_skipped_existing': [],
            'header_macros_skipped': [],
        }

        # ---------- PDM entries ----------
        pdm_entries = []
        eeprom_dids = [d for d in dids if d.storage_pos.upper() == 'EEPROM']
        for did in eeprom_dids:
            entry = self.generate_pdm_entry(did)
            if entry:
                pdm_entries.append(entry)

        pdm_content = '\n'.join(pdm_entries)
        if 'pdm_file' in skip_keys:
            print(f"[SKIP] PDM entries for {product_type} (no Bosch target).")
        elif 'pdm' in actual_paths:
            try:
                actual_pdm_path = actual_paths['pdm']
                if not dry_run:
                    actual_pdm_path.parent.mkdir(parents=True, exist_ok=True)
                if actual_pdm_path.exists():
                    # Skip-on-conflict: append only new entries (existing
                    # text is preserved verbatim — no merge / overwrite).
                    existing = actual_pdm_path.read_text(encoding='utf-8')
                    if pdm_content.strip() and pdm_content.strip() not in existing:
                        merged = existing.rstrip() + '\n\n' + pdm_content
                        if self._guarded_project_write(
                                actual_pdm_path, merged, dry_run, 'append PDM'):
                            print(f"[APPENDED] PDM entries to: {actual_pdm_path}")
                    else:
                        report['pdm_skipped_existing'].append(str(actual_pdm_path))
                        print(f"[SKIPPED] PDM entries already present: "
                              f"{actual_pdm_path}")
                else:
                    if self._guarded_project_write(
                            actual_pdm_path, pdm_content, dry_run, 'create PDM'):
                        print(f"[CREATED] PDM file: {actual_pdm_path}")
            except Exception as e:
                print(f"[ERROR] Failed to write PDM to project tree: {e}")

        # ---------- Header entries ----------
        config_entries: List[str] = []
        config_settings_entries: List[str] = []
        element_entries: List[str] = []
        range_entries: List[str] = []

        for did in dids:
            config_entries.append(self.generate_config_macro(did))
            config_settings_entries.append(self.generate_config_settings_macro(did))
            element_entries.append(self.generate_element_defs(did))
            range_macro = self.generate_range_macros(did)
            if range_macro:
                range_entries.append(range_macro)

        config_content = '\n'.join(config_entries)
        if 'config_h' in skip_keys:
            print(f"[SKIP] Config.h macros for {product_type} (no Bosch target).")
        elif 'config_h' in actual_paths:
            inserted, skipped = self._merge_or_create(
                actual_paths['config_h'], config_content,
                dry_run, label='Config macros',
            )
            if skipped:
                report['header_macros_skipped'].append(
                    f"Config.h: {skipped} macros already defined"
                )

        config_settings_content = '\n'.join(config_settings_entries)
        if 'config_settings_h' in skip_keys:
            print(f"[SKIP] ConfigSettings.h macros for {product_type} "
                  f"(no Bosch target).")
        elif 'config_settings_h' in actual_paths:
            inserted, skipped = self._merge_or_create(
                actual_paths['config_settings_h'], config_settings_content,
                dry_run, label='ConfigSettings',
            )
            if skipped:
                report['header_macros_skipped'].append(
                    f"ConfigSettings.h: {skipped} macros already defined"
                )

        elements_content = '\n'.join(element_entries)
        if 'config_elements_h' in skip_keys:
            print(f"[SKIP] ConfigElements.h macros for {product_type} "
                  f"(no Bosch target).")
        elif 'config_elements_h' in actual_paths:
            inserted, skipped = self._merge_or_create(
                actual_paths['config_elements_h'], elements_content,
                dry_run, label='Element defs',
            )
            if skipped:
                report['header_macros_skipped'].append(
                    f"ConfigElements.h: {skipped} macros already defined"
                )

        # ---------- C source files (RDBI/WDBI) ----------
        read_count = 0
        write_count = 0
        skipped_c_files: List[str] = []

        if 'c_output_subdir' in skip_keys:
            print(f"[SKIP] C sources for {product_type} (no Bosch target).")
            c_target_dir = None
        else:
            c_target_dir = actual_paths.get('c_output_dir')

        # Pre-scan for cleaned-name collisions: two DIDs that clean down
        # to the same identifier would otherwise overwrite each other's
        # .c file. We fall back to a hex-disambiguated stem for the
        # colliding subset. ``did_hex`` is guaranteed unique upstream.
        _name_counts: Dict[str, int] = {}
        for _did in dids:
            _cleaned = capitalize_first(clean_name(_did.did_name))
            _name_counts[_cleaned] = _name_counts.get(_cleaned, 0) + 1
        colliding_names = {name for name, n in _name_counts.items() if n > 1}
        if colliding_names:
            print(f"[COLLISION] {len(colliding_names)} cleaned DID name(s) "
                  f"collide across multiple DIDs; falling back to "
                  f"hex-disambiguated filenames: {sorted(colliding_names)}")

        for did in dids:
            func_name_only = capitalize_first(clean_name(did.did_name))
            did_hex_stripped = did.did_hex.replace('0x', '').upper()
            if func_name_only in colliding_names:
                filename_stem = f"{did_hex_stripped}_{func_name_only}"
            else:
                filename_stem = func_name_only

            # ---------- Per-DID header (.h) for HardCode DIDs ----------
            pos = (did.storage_pos or "").upper()
            if pos in ("ROM", "FLASH"):
                header_content = self.generate_did_header(did)
                if header_content:
                    # Derive api/ path from c_output_dir:
                    #   src/<PT>/  →  api/
                    if c_target_dir is not None:
                        api_dir = c_target_dir.parent.parent / "api"
                        header_filename = f"RBAPLCUST_RDBI_{filename_stem}.h"
                        actual_header_path = api_dir / header_filename
                        try:
                            if not dry_run:
                                api_dir.mkdir(parents=True, exist_ok=True)
                            if actual_header_path.exists():
                                print(
                                    f"[SKIPPED] DID header already exists: "
                                    f"{actual_header_path}"
                                )
                            else:
                                if self._guarded_project_write(
                                        actual_header_path, header_content,
                                        dry_run, 'create DID header'):
                                    print(
                                        f"[CREATED] DID header: "
                                        f"{actual_header_path}"
                                    )
                        except Exception as e:
                            print(
                                f"[ERROR] Failed to write DID header to "
                                f"project tree: {e}"
                            )

            read_code = self.generate_read_code(did)
            read_filename = f"RBAPLCUST_RDBI_{filename_stem}.c"

            if c_target_dir is not None:
                actual_read_path = c_target_dir / read_filename
                try:
                    if not dry_run:
                        c_target_dir.mkdir(parents=True, exist_ok=True)
                    if actual_read_path.exists():
                        skipped_c_files.append(str(actual_read_path))
                        report['c_skipped_existing'].append(str(actual_read_path))
                        print(f"[SKIPPED] C file already exists: {actual_read_path}")
                    else:
                        if self._guarded_project_write(
                                actual_read_path, read_code, dry_run,
                                'create RDBI C file'):
                            read_count += 1
                            print(f"[CREATED] C file: {actual_read_path}")
                except Exception as e:
                    print(f"[ERROR] Failed to write C file to project tree: {e}")

            if did.rw_state == 'RW':
                write_code = self.generate_write_code(did)
                if write_code and c_target_dir is not None:
                    write_filename = f"RBAPLCUST_WDBI_{filename_stem}.c"
                    actual_write_path = c_target_dir / write_filename
                    try:
                        if actual_write_path.exists():
                            skipped_c_files.append(str(actual_write_path))
                            report['c_skipped_existing'].append(str(actual_write_path))
                            print(f"[SKIPPED] C file already exists: {actual_write_path}")
                        else:
                            if self._guarded_project_write(
                                    actual_write_path, write_code, dry_run,
                                    'create WDBI C file'):
                                write_count += 1
                                print(f"[CREATED] C file: {actual_write_path}")
                    except Exception as e:
                        print(f"[ERROR] Failed to write C file to project tree: {e}")

        if c_target_dir is not None:
            print(f"C target directory: {c_target_dir} "
                  f"({read_count} created read, {write_count} created write, "
                  f"{len(skipped_c_files)} skipped)")

        # range_macros aren't written to a separate header in v1.27.0
        # (they were always a debug aid that landed in the local
        # ``outputs/.../headers/header_range_macros.txt`` mirror, which
        # we no longer produce). They remain accessible via the per-DID
        # generator entry points for ad-hoc tooling.

        return {
            'total': len(dids),
            'eeprom': len(eeprom_dids),
            'read_functions': read_count,
            'write_functions': write_count,
            'c_skipped_existing': len(skipped_c_files),
            # Full list (paths) of project-tree .c files we left
            # untouched, so the pipeline footer can surface a count
            # to the operator. ``skip_report`` keeps the same data
            # but in a generation-report shape.
            'skipped_c_files': list(skipped_c_files),
            'output_dir': str(output_dir),
            'skip_report': report,
        }

    def _merge_or_create(self, target: Path, new_content: str,
                         dry_run: bool, label: str) -> Tuple[int, int]:
        """Shared branch for ``config_h`` / ``config_settings_h`` / ``config_elements_h``.

        Existing files are merged at the macro level (existing
        ``#define`` lines win; only new macros are spliced in);
        missing files are created. Nothing is ever overwritten.

        Returns ``(inserted, skipped)`` so the orchestrator can roll
        skip counts into ``generation_report.txt``.
        """
        try:
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                existing = target.read_text(encoding='utf-8')
                merged, inserted, skipped = self._merge_header_content(
                    existing, new_content)
                if inserted > 0:
                    if self._guarded_project_write(
                            target, merged, dry_run, f'merge {label}'):
                        print(f"[MERGED] {label} to: {target} "
                              f"({inserted} inserted, {skipped} skipped)")
                else:
                    print(f"[SKIPPED] {label} to: {target} "
                          f"(0 inserted, {skipped} already defined)")
                return inserted, skipped
            if self._guarded_project_write(
                    target, new_content, dry_run, f'create {label}'):
                print(f"[CREATED] {label.split()[0]}: {target}")
            inserted = len(re.findall(r'#define\s+\w+', new_content))
            return inserted, 0
        except Exception as e:
            print(f"[ERROR] Failed to write {label} to project tree: {e}")
            return 0, 0

    def generate_validation_report(self, report: List[Dict], output_path: Path):
        """Write the per-DID validation summary to
        ``<output_path>/validation_report.txt``."""
        lines: List[str] = []
        lines.append("=" * 80)
        lines.append("Implementation Generation Validation Report")
        lines.append("=" * 80)
        lines.append("")

        success_count = sum(1 for r in report if r['status'] == 'SUCCESS')
        skip_count = sum(1 for r in report if r['status'] == 'SKIPPED')
        error_count = sum(1 for r in report if r['status'] == 'ERROR')

        lines.append(f"Total DIDs: {len(report)}")
        lines.append(f"SUCCESS: {success_count}")
        lines.append(f"SKIPPED: {skip_count}")
        lines.append(f"ERROR: {error_count}")
        lines.append("")

        lines.append("DID Processing Summary:")
        lines.append("-" * 80)
        for entry in report:
            status_symbol = ("[OK]" if entry['status'] == 'SUCCESS'
                             else "[SKIP]" if entry['status'] == 'SKIPPED'
                             else "[ERR]")
            lines.append(
                f"{status_symbol} {entry['did_hex']} - "
                f"{entry['did_name'][:50]:<50} [{entry['status']}]"
            )

        lines.append("")

        if skip_count > 0 or error_count > 0:
            lines.append("Failed DIDs Details:")
            lines.append("-" * 80)
            for entry in report:
                if entry['status'] != 'SUCCESS':
                    lines.append(f"\n{entry['did_hex']} - {entry['did_name']}")
                    lines.append(f"Status: {entry['status']}")
                    for error in entry['errors']:
                        lines.append(f"  - {error}")

        report_path = output_path / 'validation_report.txt'
        report_path.write_text('\n'.join(lines), encoding='utf-8')
        print(f"\nValidation report saved to: {report_path}")

    def _write_generation_report(
        self, dids: List[DIDImplementationInfo], stats: Dict[str, Any],
        output_path: Path,
    ) -> Path:
        """Write the v1.27.0 generation report.

        Captures:

        * per-DID fill-in disposition (filled vs TODO-stub) — the
          contract the agent honours after the framework lands;
        * project-tree skip events (.c already exists; header macros
          already defined; PDM entries already present).

        Returns the report path. Written alongside
        ``validation_report.txt`` under
        ``.DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/``.
        """
        from .generators import classify_storage, _looks_like_default_behaviour

        lines: List[str] = []
        lines.append("=" * 80)
        lines.append("Phase 3 Implementation Generation Report")
        lines.append("=" * 80)
        lines.append("")

        agent_filled: List[str] = []
        agent_todo: List[str] = []
        eeprom_full: List[str] = []
        for did in dids:
            cls = classify_storage(did)
            if cls.klass == "NVM":
                eeprom_full.append(did.did_hex)
                continue
            has_22 = not _looks_like_default_behaviour(did.behavior_22)
            has_2e = not _looks_like_default_behaviour(did.behavior_2e)
            actionable = has_22 or (did.rw_state == "RW" and has_2e)
            if actionable:
                agent_filled.append(
                    f"{did.did_hex} {did.did_name} "
                    f"({cls.klass}, pattern={cls.ram_subpattern or '-'})"
                )
            else:
                agent_todo.append(
                    f"{did.did_hex} {did.did_name} "
                    f"({cls.klass}, behavior empty/default)"
                )

        lines.append(f"EEPROM DIDs (full body generated)     : {len(eeprom_full)}")
        lines.append(f"Non-EEPROM DIDs with real behavior    : "
                     f"{len(agent_filled)}  (agent fills these in same turn)")
        lines.append(f"Non-EEPROM DIDs with empty behavior   : "
                     f"{len(agent_todo)}  (TODO(agent) stubs kept in .c)")
        lines.append("")

        if agent_filled:
            lines.append("[FILL] Agent should fill in the following non-EEPROM DIDs:")
            for line in agent_filled:
                lines.append(f"  - {line}")
            lines.append("")
        if agent_todo:
            lines.append("[STUB] The following non-EEPROM DIDs keep their TODO stubs")
            lines.append("       (operator must populate FSCS behavior text upstream):")
            for line in agent_todo:
                lines.append(f"  - {line}")
            lines.append("")

        skip_report = stats.get('skip_report', {})
        c_skipped = skip_report.get('c_skipped_existing', [])
        pdm_skipped = skip_report.get('pdm_skipped_existing', [])
        header_skipped = skip_report.get('header_macros_skipped', [])

        if c_skipped or pdm_skipped or header_skipped:
            lines.append("Project-tree skip events (existing content preserved):")
            for path in c_skipped:
                lines.append(f"  - [.c exists] {path}")
            for path in pdm_skipped:
                lines.append(f"  - [PDM already populated] {path}")
            for note in header_skipped:
                lines.append(f"  - [header] {note}")
            lines.append("")
        else:
            lines.append("Project-tree skip events: (none — every artefact was fresh)")
            lines.append("")

        report_path = output_path / 'generation_report.txt'
        report_path.write_text('\n'.join(lines), encoding='utf-8')
        print(f"Generation report saved to: {report_path}")
        return report_path

    def generate(self, output_dir: Path,
                 *,
                 fscs_json_path: Path,
                 product_type: Optional[str] = None,
                 dry_run: bool = False) -> Dict[str, Any]:
        """End-to-end: load ``fscs.json`` and produce all Phase 3 artifacts.

        Contract:
        * ``output_dir`` is the **report sink only**
          (``.DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/``); generated
          source files land in the Bosch project tree resolved via
          ``paths.*``.
        * The agent fills in non-EEPROM ``TODO(agent)`` blocks
          inline based on the FSCS Behavior text embedded directly
          in each ``.c`` stub.
        """
        print("=" * 70)
        print("Implementation Code Generator")
        print("=" * 70)
        print()

        self.product_type = product_type

        valid_dids, validation_report = self.load_dids(
            fscs_json_path=fscs_json_path,
        )

        self.generate_validation_report(validation_report, output_dir)

        if not valid_dids:
            print("\n[WARNING] No valid DIDs to process!")
            empty_stats = {
                'total': 0,
                'eeprom': 0,
                'read_functions': 0,
                'write_functions': 0,
                'c_skipped_existing': 0,
                'skipped_c_files': [],
                'agent_fill_targets': [],
                'agent_stub_targets': [],
                'output_dir': str(output_dir),
                'validation_report': validation_report,
                'skip_report': {
                    'c_skipped_existing': [],
                    'pdm_skipped_existing': [],
                    'header_macros_skipped': [],
                },
            }
            self._write_generation_report(valid_dids, empty_stats, output_dir)
            return empty_stats

        stats = self.generate_from_dids(
            valid_dids, output_dir,
            product_type=product_type,
            dry_run=dry_run,
        )
        stats['validation_report'] = validation_report

        self._write_generation_report(valid_dids, stats, output_dir)

        # v1.27.0: one continuous Phase 3 turn — surface the agent
        # fill-in obligation alongside the generator stats so the
        # caller's footer can chain straight into agent action
        # without [AGENT STOP].
        from .generators import classify_storage, _looks_like_default_behaviour
        fill_targets = []
        stub_targets = []
        for d in valid_dids:
            if classify_storage(d).klass == "NVM":
                continue
            has_22 = not _looks_like_default_behaviour(d.behavior_22)
            has_2e = not _looks_like_default_behaviour(d.behavior_2e)
            if has_22 or (d.rw_state == "RW" and has_2e):
                fill_targets.append(d.did_hex)
            else:
                stub_targets.append(d.did_hex)
        stats['agent_fill_targets'] = fill_targets
        stats['agent_stub_targets'] = stub_targets

        if fill_targets or stub_targets:
            print(
                f"\n[AGENT TODO] {len(fill_targets)} non-EEPROM DID(s) with "
                f"real FSCS behavior require inline fill-in this turn; "
                f"{len(stub_targets)} kept as TODO stubs (behavior empty/default)."
            )
        return stats
