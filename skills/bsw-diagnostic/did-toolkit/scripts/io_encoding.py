"""Force UTF-8 on the process's stdio streams.

Why this exists
---------------

Every CLI in ``scripts/`` emits Chinese text somewhere -- review
reports, DID names (``did_name_zh``), logger warnings, console
summaries, Pydantic error messages for CJK input. All *file* writes in
this toolkit already pass ``encoding='utf-8'`` explicitly, so the
artefacts on disk are fine. The problem is **console** output:

* On Windows, when Python's ``sys.stdout`` is not attached to a TTY
  (anything that redirects / pipes, including PowerShell's ``2>&1``
  capture, ``subprocess.Popen(..., stdout=PIPE)``, CI runners, the
  PSReadLine state-file that Cursor's shell wrapper uses), Python
  falls back to the legacy ANSI code page -- ``cp1252`` in most en-US
  installs, ``cp936`` in zh-CN installs -- and CJK characters become
  ``UnicodeEncodeError`` or ``\\uXXXX`` escape noise in the log
  output.

* The same trap exists on older POSIX setups with ``LANG=C``, though
  modern distros have moved to UTF-8 by default.

``reconfigure_stdio_utf8`` collapses the three common workarounds
(``PYTHONUTF8=1``, ``PYTHONIOENCODING=utf-8:replace``, and manual
``sys.stdout.reconfigure(...)``) into a single idempotent call that
every CLI entry point runs before the first byte is written.

Design choices
--------------

* **Idempotent.** Safe to call from multiple entry points (e.g.
  ``pipeline.py`` launches Phase 2 in-process, which calls
  ``generate_arxml.main``; both invoke this helper). ``reconfigure``
  on an already-UTF-8 stream is a no-op.

* **Fail-soft.** ``sys.stdout`` is sometimes replaced with a non-text
  wrapper (``subprocess.Popen(..., stdout=PIPE)`` on the child side,
  some IDE terminals, pytest's capture machinery). If ``reconfigure``
  isn't available or raises, we swallow the exception -- the worst
  case is the original behaviour and we don't want to break otherwise
  healthy pipelines over a cosmetic logging concern.

* **`errors='replace'`** rather than ``'strict'``: on the rare
  occasion the destination stream genuinely can't take a character,
  we prefer a ``?`` marker over an uncaught ``UnicodeEncodeError``
  deep inside ``logging.StreamHandler``.

* **Imported near the top of every CLI**, right after ``sys`` itself,
  so the reconfigure happens before ``logging.basicConfig`` latches
  onto the stderr encoding.
"""

from __future__ import annotations

import sys


def reconfigure_stdio_utf8() -> None:
    """Switch ``sys.stdout`` / ``sys.stderr`` to UTF-8 (replace) if possible."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            # ``TextIOWrapper.reconfigure`` exists on Python 3.7+. If
            # the stream isn't a TextIOWrapper (e.g. a test-captured
            # ``StringIO`` or a subprocess pipe already in binary mode)
            # we silently skip -- the caller already did the right
            # thing at wrap time.
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # ValueError: stream is detached or already in a
            # non-reconfigurable state.
            # OSError: underlying FD rejected the mode change.
            # Either way, leave the stream as-is.
            pass
