"""Behavioral tests for opt-in hermes_cli.js_runtime (config.yaml runtime.js_runtime)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hermes_cli import js_runtime


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _write_config(tmp_path: Path, monkeypatch, runtime_value: str | None) -> Path:
    home = tmp_path / "hermes-home"
    home.mkdir(parents=True, exist_ok=True)
    if runtime_value is not None:
        (home / "config.yaml").write_text(f"runtime:\n  js_runtime: {runtime_value}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def test_defaults_to_node_and_activates_bun_only_when_configured_on_supported_host(monkeypatch, tmp_path):
    _write_config(tmp_path, monkeypatch, None)
    monkeypatch.setattr(js_runtime, "bun_supported_on_host", lambda: True)
    assert js_runtime.configured_js_runtime() == "node"
    assert js_runtime.use_bun_js_runtime() is False
    assert js_runtime.runtime_display_name() == "Node.js"

    _write_config(tmp_path, monkeypatch, "bun")
    assert js_runtime.configured_js_runtime() == "bun"
    assert js_runtime.use_bun_js_runtime() is True
    assert js_runtime.runtime_display_name() == "Bun"
    assert "hermes pm install bun" in js_runtime.missing_runtime_hint()
    assert "runtime.js_runtime: node" in js_runtime.missing_runtime_hint()

    # Unsupported target (e.g. macOS/Windows/musl) stays safely on Node even if config asks for bun.
    monkeypatch.setattr(js_runtime, "bun_supported_on_host", lambda: False)
    assert js_runtime.use_bun_js_runtime() is False


def test_script_argv_omits_expose_gc_on_bun_and_keeps_it_on_node(monkeypatch, tmp_path):
    import pm

    fake_bun = _make_executable(tmp_path / "pm-bun" / "bun")
    fake_node = _make_executable(tmp_path / "pm-node" / "node")

    monkeypatch.setattr(pm, "ensure", lambda pkg, **kw: SimpleNamespace(env={"PATH": str(fake_bun.parent)}))
    monkeypatch.setattr(pm, "installed_package", lambda pkg: SimpleNamespace(binary=fake_bun) if pkg == "bun" else None)
    monkeypatch.setattr(js_runtime, "bun_supported_on_host", lambda: True)
    monkeypatch.setenv("HERMES_NODE", str(fake_node))

    _write_config(tmp_path, monkeypatch, "bun")
    bun_argv = js_runtime.script_argv("/app/entry.js", "--flag", expose_gc=True)
    assert bun_argv == [str(fake_bun), "/app/entry.js", "--flag"]
    assert "--expose-gc" not in bun_argv

    _write_config(tmp_path, monkeypatch, "node")
    node_argv = js_runtime.script_argv("/app/entry.js", "--flag", expose_gc=True)
    assert node_argv == [str(fake_node), "--expose-gc", "/app/entry.js", "--flag"]


def test_install_deps_command_uses_bun_when_opted_in_and_npm_by_default(monkeypatch, tmp_path):
    import pm

    fake_bun = _make_executable(tmp_path / "pm-bun" / "bun")
    fake_npm = _make_executable(tmp_path / "pm-npm" / "npm")
    ensured: list[str] = []

    def fake_ensure(pkg, **kwargs):
        ensured.append(pkg)
        return SimpleNamespace(env={"PATH": str(fake_bun.parent if pkg == "bun" else fake_npm.parent)})

    def fake_installed(pkg):
        if pkg == "bun":
            return SimpleNamespace(binary=fake_bun)
        if pkg == "npm":
            return SimpleNamespace(binary=fake_npm)
        return None

    monkeypatch.setattr(pm, "ensure", fake_ensure)
    monkeypatch.setattr(pm, "installed_package", fake_installed)
    monkeypatch.setattr(js_runtime, "bun_supported_on_host", lambda: True)

    _write_config(tmp_path, monkeypatch, "bun")
    cmd_frozen, _ = js_runtime.install_deps_command(frozen=True)
    assert cmd_frozen == [str(fake_bun), "install", "--frozen-lockfile"]
    cmd_plain, _ = js_runtime.install_deps_command(frozen=False, silent=True)
    assert cmd_plain == [str(fake_bun), "install", "--silent"]
    assert ensured == ["bun", "bun"]

    ensured.clear()
    _write_config(tmp_path, monkeypatch, "node")
    monkeypatch.setattr(js_runtime, "find_node_executable", lambda name: str(fake_npm) if name == "npm" else None)
    node_frozen, _ = js_runtime.install_deps_command(frozen=True, no_audit=True)
    assert node_frozen == [str(fake_npm), "ci", "--no-fund", "--no-audit"]
    assert ensured == []


def test_is_js_runtime_process_recognizes_both_bun_and_node():
    assert js_runtime.is_js_runtime_process("bun", "/opt/hermes/tools/bun/bun") is True
    assert js_runtime.is_js_runtime_process("node", "/usr/bin/node") is True
    assert js_runtime.is_js_runtime_process("python3", "/usr/bin/python3") is False
