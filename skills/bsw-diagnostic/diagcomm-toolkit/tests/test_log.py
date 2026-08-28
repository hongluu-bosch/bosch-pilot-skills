"""Tests for ``scripts/_log.py``.

Since 1.7+ the helper is a tiny stderr emitter (``info`` / ``warn`` /
``err``) rather than a wrapper around ``logging.basicConfig`` -- the
pipeline stays framework-free and every Step prints with a stable
``[doors]`` prefix that downstream agents grep on.

These tests pin the contract the rest of the toolkit relies on:
  * each level emits to **stderr** (never stdout) so progress chatter
    doesn't get parsed as machine output;
  * the prefix tag distinguishes INFO / WARN / ERR so log scrapers can
    filter without parsing message bodies;
  * ``%``-style varargs formatting works (``info("hello %s", name)``)
    -- callers rely on this in pipeline.py.
"""
from __future__ import annotations

import _log


def test_info_writes_prefixed_line_to_stderr(capfd):
    _log.info("hello world")
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == "[doors] hello world\n"


def test_warn_writes_prefixed_line_to_stderr(capfd):
    _log.warn("non-fatal: %s", "skipped")
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == "[doors][WARN] non-fatal: skipped\n"


def test_err_writes_prefixed_line_to_stderr(capfd):
    _log.err("fatal: %s", "crash")
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == "[doors][ERR ] fatal: crash\n"


def test_info_supports_percent_style_args(capfd):
    _log.info("count=%d kind=%s", 7, "hits")
    captured = capfd.readouterr()
    assert captured.err == "[doors] count=7 kind=hits\n"


def test_no_args_emits_message_verbatim(capfd):
    # No args path must NOT try to format -- callers occasionally pass
    # raw strings containing literal ``%`` (e.g. progress percentages)
    # and we don't want to crash on a missing arg.
    _log.info("100% done")
    captured = capfd.readouterr()
    assert captured.err == "[doors] 100% done\n"


def test_levels_share_the_same_stream(capfd):
    _log.info("a")
    _log.warn("b")
    _log.err("c")
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "[doors] a\n"
        "[doors][WARN] b\n"
        "[doors][ERR ] c\n"
    )
