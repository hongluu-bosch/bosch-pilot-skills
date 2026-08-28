"""Unit tests for _extract_existing_macros / _find_insert_position /
_merge_header_content.

Phase 3 merges new Feature-Switch macros into existing BSW header files.
Two invariants matter most:
  * Idempotency: re-merging the same content must not introduce duplicates.
  * Insert position: new defines land before the file's closing ``#endif``
    guard, not after it.
"""

from __future__ import annotations

import pytest

from generate_implementation import ImplementationGenerator


@pytest.fixture
def gen() -> ImplementationGenerator:
    return ImplementationGenerator()


HEADER_SKELETON = """\
#ifndef RBAPLCUST_CONFIG_H
#define RBAPLCUST_CONFIG_H

#define RBFS_DCOM_Existing\t\tRBFS_DCOM_Existing_OFF

#endif /* RBAPLCUST_CONFIG_H */
"""

NEW_MACROS = """\
/* ------------------------------------------------------------------------ */
/* RBFS_DCOM_Brand_New                                                     */
/* ------------------------------------------------------------------------ */
#ifndef RBFS_DCOM_Brand_New
#define RBFS_DCOM_Brand_New\t\tRBFS_DCOM_Brand_New_OFF
#endif
"""

DUPLICATE_MACROS = """\
#ifndef RBFS_DCOM_Existing
#define RBFS_DCOM_Existing\t\tRBFS_DCOM_Existing_OFF
#endif
"""


class TestExtractExistingMacros:
    def test_pulls_every_define(self, gen):
        macros = gen._extract_existing_macros(HEADER_SKELETON)
        assert "RBAPLCUST_CONFIG_H" in macros
        assert "RBFS_DCOM_Existing" in macros


class TestFindInsertPosition:
    def test_positions_before_last_endif(self, gen):
        pos = gen._find_insert_position(HEADER_SKELETON)
        assert HEADER_SKELETON[pos:].lstrip().startswith("#endif")

    def test_no_endif_appends_to_end(self, gen):
        content = "just text\nno guard\n"
        pos = gen._find_insert_position(content)
        assert pos == len(content)


class TestMergeHeaderContent:
    def test_inserts_new_macros_before_endif(self, gen):
        merged, inserted, skipped = gen._merge_header_content(
            HEADER_SKELETON, NEW_MACROS
        )
        assert inserted == 1  # one new #define added
        assert skipped == 0
        assert "RBFS_DCOM_Brand_New" in merged
        assert merged.rstrip().endswith("#endif /* RBAPLCUST_CONFIG_H */")

    def test_idempotent_when_macros_already_present(self, gen):
        # Seed the file with both macros, then merge the same content again.
        first, _, _ = gen._merge_header_content(HEADER_SKELETON, NEW_MACROS)
        second, inserted, skipped = gen._merge_header_content(first, NEW_MACROS)
        assert inserted == 0
        assert skipped >= 1  # Brand_New was recognized as already-present
        # No duplicate #defines of the new macro
        assert second.count("#define RBFS_DCOM_Brand_New\t") == 1

    def test_skipped_count_reflects_duplicates(self, gen):
        _, inserted, skipped = gen._merge_header_content(
            HEADER_SKELETON, DUPLICATE_MACROS
        )
        assert inserted == 0
        assert skipped == 1
