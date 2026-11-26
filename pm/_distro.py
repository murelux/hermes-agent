"""Stdlib-only Linux Debian-family detection for PM and runtime selection.

Kept inside ``pm/`` with stdlib-only imports so bootstrap stages (before any
application or third-party dependencies exist) and ``hermes_platform`` share
one canonical Debian-family check.
"""

from __future__ import annotations

import functools
import os
import platform
import sys

# Matches the apt/Debian distro family across pm/libatomic.py and scripts/install.sh.
DEBIAN_FAMILY_IDS: frozenset[str] = frozenset(
    {"debian", "ubuntu", "linuxmint", "pop", "raspbian", "kali", "elementary"}
)


def _is_termux_env() -> bool:
    prefix = os.environ.get("PREFIX", "")
    return bool(os.environ.get("TERMUX_VERSION") or "com.termux/files/usr" in prefix)


def _parse_os_release_file(path: os.PathLike[str] | str) -> dict[str, str]:
    fields: dict[str, str] = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            fields[key.strip()] = val.strip().strip('"').strip("'")
    return fields


def os_release_tokens(path: os.PathLike[str] | str | None = None) -> frozenset[str]:
    """Lowercased ``ID`` and ``ID_LIKE`` tokens from ``/etc/os-release`` (or *path*)."""
    if path is not None:
        try:
            fields = _parse_os_release_file(path)
        except OSError:
            return frozenset()
    else:
        if not sys.platform.startswith("linux"):
            return frozenset()
        try:
            fields = platform.freedesktop_os_release()
        except OSError:
            return frozenset()
    blob = f"{fields.get('ID', '')} {fields.get('ID_LIKE', '')}".lower()
    return frozenset(blob.replace(",", " ").split())


@functools.cache
def is_debian_family() -> bool:
    """True only on Linux Debian-family hosts (never macOS, Windows, Termux, Fedora, Alpine)."""
    if not sys.platform.startswith("linux") or _is_termux_env():
        return False
    return bool(os_release_tokens() & DEBIAN_FAMILY_IDS)


def debian_bun_enabled() -> bool:
    """True when this host should use PM's Bun JS runtime instead of Node/npm/pnpm.

    Strictly gated to Linux Debian-family hosts unless the operator opts back
    into Node with ``HERMES_JS_RUNTIME=node``.
    """
    if not is_debian_family():
        return False
    # health: allow HX002 -- emergency runtime escape hatch read during stdlib-only PM bootstrap before config.yaml exists
    return (os.environ.get("HERMES_JS_RUNTIME") or "").strip().lower() != "node"
