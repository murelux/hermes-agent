"""JavaScript runtime selection for Hermes-spawned JS processes and Debian builds.

Linux Debian-family hosts (debian, ubuntu, linuxmint, pop, raspbian, kali,
elementary) use PM-managed Bun unless ``HERMES_JS_RUNTIME=node`` is set as an
escape hatch. Every other OS/distro (macOS, Windows, Termux, Fedora, Alpine)
keeps the existing Node.js / npm / pnpm contract unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from hermes_constants import find_node_executable, with_hermes_node_path
from hermes_platform.host.facts import is_debian_family


def _is_executable_file(path: str | None) -> bool:
    if not path:
        return False
    candidate = Path(path)
    return candidate.is_file() and os.access(candidate, os.X_OK)


def _env_bun_path() -> str:
    # health: allow HX002 -- runtime binary override matching HERMES_NODE
    return (os.environ.get("HERMES_BUN") or "").strip()


def use_bun_js_runtime() -> bool:
    """True only on Linux Debian-family hosts when ``HERMES_JS_RUNTIME`` is not ``node``."""
    if not is_debian_family():
        return False
    # health: allow HX002 -- emergency runtime fallback read before config.yaml exists
    return (os.environ.get("HERMES_JS_RUNTIME") or "").strip().lower() != "node"


def runtime_display_name() -> str:
    """Human-readable name of the active JS runtime."""
    return "Bun" if use_bun_js_runtime() else "Node.js"


def missing_runtime_hint() -> str:
    """Actionable install / fallback hint for the active JS runtime."""
    if use_bun_js_runtime():
        return (
            "Install Bun with `hermes pm install bun`, or set `HERMES_JS_RUNTIME=node` "
            "to fall back to Node.js."
        )
    return (
        "Install Node.js with `hermes pm install node` (or run `hermes doctor` for the "
        "install hint for your OS)."
    )


def find_bun_executable() -> Optional[str]:
    """Read-only lookup for Bun: explicit ``HERMES_BUN`` override, else PM's installed ``bun``."""
    env_bun = _env_bun_path()
    if env_bun and _is_executable_file(env_bun):
        return env_bun
    import pm

    installed = pm.installed_package("bun")
    if installed is None or installed.binary is None:
        return None
    return str(installed.binary)


def ensure_bun_executable(*, explicit: bool = False) -> tuple[str, dict[str, str]]:
    """Return ``(bun_binary, env)``, provisioning PM's ``bun`` when absent."""
    env_bun = _env_bun_path()
    if env_bun and _is_executable_file(env_bun):
        return env_bun, js_runtime_env()
    import pm

    runner = pm.ensure("bun", explicit=explicit)
    installed = pm.installed_package("bun")
    if installed is None or installed.binary is None:
        raise pm.InstallError(
            "bun",
            "Bun binary is missing after preparation",
            "run `hermes pm install bun`, or set `HERMES_JS_RUNTIME=node` to fall back to Node.js",
        )
    return str(installed.binary), dict(runner.env)


def find_js_runtime(*, node_override: Optional[str] = None) -> Optional[str]:
    """Read-only lookup for the active JS runtime executable (never installs)."""
    if use_bun_js_runtime():
        return find_bun_executable()
    if node_override and node_override.strip():
        return node_override.strip()
    env_node = (os.environ.get("HERMES_NODE") or "").strip()
    if env_node and _is_executable_file(env_node):
        return env_node
    return find_node_executable("node")


def js_runtime_bin(*, explicit: bool = False, node_override: Optional[str] = None) -> str:
    """Resolve and provision (if missing) the active JS runtime binary.

    On Debian-family hosts with Bun enabled, ``HERMES_NODE`` and ``PHOTON_NODE_BIN``
    do not pull execution back to Node; ``HERMES_BUN`` overrides the Bun binary.
    """
    if use_bun_js_runtime():
        bun, _ = ensure_bun_executable(explicit=explicit)
        return bun
    if node_override and node_override.strip():
        return node_override.strip()
    env_node = (os.environ.get("HERMES_NODE") or "").strip()
    if env_node and _is_executable_file(env_node):
        return env_node
    node = find_node_executable("node")
    if node is not None:
        return node
    import pm

    pm.ensure("node", explicit=explicit)
    installed = pm.installed_package("node")
    if installed is None or installed.binary is None:
        raise pm.InstallError("node", "Node.js binary is missing after preparation")
    return str(installed.binary)


def js_runtime_env(base_env: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Compose subprocess environment with the active JS runtime on PATH (no provisioning)."""
    if use_bun_js_runtime():
        import pm

        env = pm.env_for("bun", base_env=base_env)
        env_bun = _env_bun_path()
        if env_bun and _is_executable_file(env_bun):
            bun_dir = str(Path(env_bun).parent)
            existing = env.get("PATH", "")
            if bun_dir not in existing.split(os.pathsep):
                env["PATH"] = f"{bun_dir}{os.pathsep}{existing}" if existing else bun_dir
        # If PM Node is already installed (e.g. for optional MCP/Desktop tools), keep it
        # reachable without provisioning Node on a pure-Bun Debian host.
        if pm.installed_package("node") is not None:
            node_path = pm.env_for("node", base_env={"PATH": ""}).get("PATH", "")
            if node_path:
                existing = env.get("PATH", "")
                env["PATH"] = f"{existing}{os.pathsep}{node_path}" if existing else node_path
        return env
    return with_hermes_node_path(base_env)


def script_argv(
    script: str | Path,
    *args: str,
    expose_gc: bool = False,
    runtime_bin: Optional[str] = None,
    explicit: bool = False,
    node_override: Optional[str] = None,
) -> list[str]:
    """Build argv to execute a JS script under the active runtime.

    Bun omits V8 flags like ``--expose-gc``; Node preserves the existing flags.
    """
    binary = runtime_bin or js_runtime_bin(explicit=explicit, node_override=node_override)
    if use_bun_js_runtime():
        return [binary, str(script), *args]
    flags = ["--expose-gc"] if expose_gc else []
    return [binary, *flags, str(script), *args]


def find_deps_installer() -> Optional[str]:
    """Read-only lookup for the dependency installer binary (``bun`` or ``npm``)."""
    if use_bun_js_runtime():
        return find_bun_executable()
    return find_node_executable("npm")


def install_deps_command(
    *,
    frozen: bool = False,
    silent: bool = False,
    no_audit: bool = False,
    no_progress: bool = False,
    explicit: bool = False,
) -> tuple[list[str], dict[str, str]]:
    """Return ``(argv, env)`` to install JS dependencies for sidecars/bridges."""
    if use_bun_js_runtime():
        bun, env = ensure_bun_executable(explicit=explicit)
        argv = [bun, "install"]
        if frozen:
            argv.append("--frozen-lockfile")
        if silent:
            argv.append("--silent")
        return argv, env

    import pm

    npm = find_node_executable("npm")
    env = with_hermes_node_path()
    if npm is None:
        env = pm.ensure("npm", explicit=explicit).env
        installed = pm.installed_package("npm")
        if installed is None or installed.binary is None:
            raise pm.InstallError("npm", "npm binary is missing after preparation")
        npm = str(installed.binary)
    argv = [npm, "ci" if frozen else "install"]
    if silent:
        argv.append("--silent")
    if no_audit:
        argv.extend(["--no-fund", "--no-audit"])
    if no_progress:
        argv.append("--progress=false")
    return argv, env


def is_js_runtime_process(name: str, cmdline_first: str = "") -> bool:
    """True when a process name or argv[0] identifies a Hermes JS runtime (node or bun)."""
    name_low = (name or "").lower()
    first_low = (cmdline_first or "").lower()
    for token in ("node", "bun"):
        if token in name_low or token in first_low:
            return True
    return False
