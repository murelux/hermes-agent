"""JavaScript runtime selection for Hermes-spawned JS processes.

Defaults to PM-managed Node.js on every platform. On Linux x64/arm64, users can
opt into PM-managed Bun by setting ``runtime.js_runtime: bun`` in
``config.yaml`` (``hermes config set runtime.js_runtime bun``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from hermes_constants import find_node_executable, with_hermes_node_path


def _is_executable_file(path: str | None) -> bool:
    if not path:
        return False
    candidate = Path(path)
    return candidate.is_file() and os.access(candidate, os.X_OK)


def configured_js_runtime() -> str:
    """Return configured ``runtime.js_runtime`` (``"bun"`` or ``"node"``; default ``"node"``)."""
    try:
        from hermes_cli.config import cfg_get, load_config_readonly

        raw = cfg_get(load_config_readonly(), "runtime", "js_runtime")
    except (ImportError, OSError, ValueError, RuntimeError):
        return "node"
    value = str(raw or "node").strip().lower()
    return "bun" if value == "bun" else "node"


def bun_supported_on_host() -> bool:
    """True when PM ships a pinned Bun artifact for the current target (Linux x64/arm64)."""
    import pm

    return pm.get_package("bun").missing_reason(pm.current_target()) is None


def use_bun_js_runtime() -> bool:
    """True only when ``runtime.js_runtime`` is ``"bun"`` on a supported Linux target."""
    if configured_js_runtime() != "bun":
        return False
    return bun_supported_on_host()


def runtime_display_name() -> str:
    """Human-readable name of the active JS runtime."""
    return "Bun" if use_bun_js_runtime() else "Node.js"


def missing_runtime_hint() -> str:
    """Actionable install / fallback hint for the active JS runtime."""
    if use_bun_js_runtime():
        return (
            "Install Bun with `hermes pm install bun`, or set `runtime.js_runtime: node` "
            "in config.yaml to fall back to Node.js."
        )
    return (
        "Install Node.js with `hermes pm install node` (or run `hermes doctor` for the "
        "install hint for your OS)."
    )


def find_bun_executable() -> Optional[str]:
    """Read-only lookup for PM's installed ``bun`` binary."""
    import pm

    installed = pm.installed_package("bun")
    if installed is None or installed.binary is None:
        return None
    return str(installed.binary)


def ensure_bun_executable(*, explicit: bool = False) -> tuple[str, dict[str, str]]:
    """Return ``(bun_binary, env)``, provisioning PM's ``bun`` when absent."""
    import pm

    runner = pm.ensure("bun", explicit=explicit)
    installed = pm.installed_package("bun")
    if installed is None or installed.binary is None:
        raise pm.InstallError(
            "bun",
            "Bun binary is missing after preparation",
            "run `hermes pm install bun`, or set `runtime.js_runtime: node` in config.yaml",
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
    """Resolve and provision (if missing) the active JS runtime binary."""
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
