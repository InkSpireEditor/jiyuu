"""Confirms jiyuu's non-UI modules never import `flet`.

jiyuu's core modules are meant to run with no GUI toolkit available at all, including in CI
and in anything other than the desktop app that might use them later. A module that pulls in
`flet` anywhere along its own chain of imports would silently break that, so each module is
imported alone, in a fresh subprocess, rather than all together in this test's own process —
importing `flet` for one module would otherwise still be present in `sys.modules` by the time
a later module is checked, masking exactly the mistake this test exists to catch.
"""

from __future__ import annotations

import pkgutil
import subprocess
import sys

import jiyuu


def _non_ui_module_names() -> list[str]:
    """Every importable module under `jiyuu`, except `jiyuu.cli` and anything under `jiyuu.ui`."""
    names = ["jiyuu"]
    for module_info in pkgutil.walk_packages(jiyuu.__path__, prefix="jiyuu."):
        if module_info.name == "jiyuu.cli" or module_info.name.startswith("jiyuu.ui"):
            continue
        names.append(module_info.name)
    return names


def test_non_ui_modules_do_not_import_flet() -> None:
    """Each non-UI module, imported by itself, never ends up pulling in `flet`."""
    for name in _non_ui_module_names():
        result = subprocess.run(
            [sys.executable, "-c", f"import {name}; import sys; assert 'flet' not in sys.modules"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{name} imported flet:\n{result.stderr}"
