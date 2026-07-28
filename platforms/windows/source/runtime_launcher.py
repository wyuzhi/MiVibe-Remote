"""Build commands that relaunch this application in an internal role."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parent
HUB_SCRIPT = SOURCE_ROOT / "remote_bridge_hub.py"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def application_root() -> Path:
    """Return a stable working directory for source and packaged launches."""

    if is_frozen():
        return Path(sys.executable).resolve().parent
    return SOURCE_ROOT


def role_command(
    role: str,
    arguments: Iterable[object] = (),
    *,
    unbuffered: bool = False,
) -> list[str]:
    """Return a command for an internal worker or settings role.

    A packaged customer build relaunches its own executable. Source-mode runs
    relaunch the hub script with the current interpreter, which keeps local
    development and package behavior on the same dispatch path.
    """

    role_arguments = ["--role", str(role), *(str(value) for value in arguments)]
    if is_frozen():
        return [str(Path(sys.executable).resolve()), *role_arguments]

    command = [str(Path(sys.executable).resolve())]
    if unbuffered:
        command.append("-u")
    command.extend((str(HUB_SCRIPT), *role_arguments))
    return command
