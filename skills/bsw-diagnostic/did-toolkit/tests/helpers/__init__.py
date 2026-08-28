"""Shared test helpers for the did-toolkit suite.

The modules here are imported by ``conftest.py`` and individual tests to
normalize generated output and produce readable diff messages. They live
under ``tests/helpers/`` rather than ``tests/`` itself so pytest does not
try to collect them as test files.
"""
