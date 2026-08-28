"""Resolve the active project workspace root."""

import pathlib

WORKSPACE_NAME = ".DCOM_AI/19Service_Toolkit_PRJ"
CONFIG_MARKER = "config/project.json"


def resolve_project_root() -> pathlib.Path:
    """Return the workspace path (<project_root>/.DCOM_AI/19Service_Toolkit_PRJ/).

    The project root is always the current working directory (CWD).  It must
    contain a Bosch project tree, detected as either:

      - <cwd>/<platform>/rb/as/
      - <cwd>/rb/as/

    There is no fallback to the skill install directory and no support for
    explicit project-root overrides via CLI or environment variables.
    """
    cwd = pathlib.Path.cwd()

    # Accept either <cwd>/<platform>/rb/as/ or the legacy <cwd>/rb/as/ layout.
    platform_dirs = [d for d in cwd.iterdir() if d.is_dir()]
    has_bosch_tree = any((platform / "rb" / "as").exists() for platform in platform_dirs)

    if not has_bosch_tree and not (cwd / "rb" / "as").exists():
        raise RuntimeError(
            f"Current directory does not look like a project root: {cwd}\n"
            "Expected to find either <platform>/rb/as/ or rb/as/ here. "
            "Please cd to the project root and try again."
        )

    return cwd / ".DCOM_AI" / "19Service_Toolkit_PRJ"


def get_container(workspace: pathlib.Path) -> pathlib.Path:
    """Return the project container (parent of .DCOM_AI)."""
    dcom = workspace.parent
    return dcom.parent
