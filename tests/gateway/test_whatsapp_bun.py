"""Behavioral tests for WhatsApp bridge install and spawn under Bun (Debian) vs Node."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hermes_cli import js_runtime, main_platform_setup
from hermes_cli.web_routers import messaging
from plugins.platforms.whatsapp import adapter as wa_adapter


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_whatsapp_bridge_deps_use_bun_on_debian_and_npm_on_node(monkeypatch, tmp_path):
    bridge_dir = tmp_path / "whatsapp-bridge"
    bridge_dir.mkdir()
    (bridge_dir / "package.json").write_text('{"name":"wa-bridge","dependencies":{}}\n', encoding="utf-8")
    fake_bun = _make_executable(tmp_path / "bin" / "bun")
    fake_npm = _make_executable(tmp_path / "bin" / "npm")

    commands: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        commands.append(list(cmd))
        (bridge_dir / "node_modules").mkdir(exist_ok=True)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(wa_adapter.subprocess, "run", fake_run)
    monkeypatch.delenv("HERMES_JS_RUNTIME", raising=False)
    monkeypatch.setenv("HERMES_BUN", str(fake_bun))
    monkeypatch.setattr(js_runtime, "is_debian_family", lambda: True)

    adapter = SimpleNamespace(name="whatsapp", _set_fatal_error=lambda *args, **kwargs: None)
    assert wa_adapter.WhatsAppAdapter._ensure_bridge_deps(adapter, bridge_dir) is True
    assert commands[-1][0] == str(fake_bun)
    assert commands[-1][1] == "install"

    # Non-Debian / Node fallback uses npm install.
    (bridge_dir / "node_modules" / ".hermes-pkg-hash").unlink(missing_ok=True)
    (bridge_dir / "node_modules").rmdir()
    monkeypatch.setenv("HERMES_JS_RUNTIME", "node")
    monkeypatch.setattr(js_runtime, "find_node_executable", lambda name: str(fake_npm) if name == "npm" else None)

    assert wa_adapter.WhatsAppAdapter._ensure_bridge_deps(adapter, bridge_dir) is True
    assert commands[-1][0] == str(fake_npm)
    assert commands[-1][1] == "install"


def test_whatsapp_platform_setup_tracks_bun_package_hash(monkeypatch, tmp_path):
    bridge_dir = tmp_path / "whatsapp-bridge"
    bridge_dir.mkdir()
    pkg = bridge_dir / "package.json"
    pkg.write_text('{"name":"wa-bridge","version":"1.0.0"}\n', encoding="utf-8")
    fake_bun = _make_executable(tmp_path / "bin" / "bun")

    def fake_run(cmd, **kwargs):
        (bridge_dir / "node_modules").mkdir(exist_ok=True)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(main_platform_setup.subprocess, "run", fake_run)
    monkeypatch.delenv("HERMES_JS_RUNTIME", raising=False)
    monkeypatch.setenv("HERMES_BUN", str(fake_bun))
    monkeypatch.setattr(js_runtime, "is_debian_family", lambda: True)

    assert main_platform_setup._whatsapp_bridge_dependencies_current(bridge_dir) is False
    assert main_platform_setup._whatsapp_install_bridge(bridge_dir) is True
    assert main_platform_setup._whatsapp_bridge_dependencies_current(bridge_dir) is True

    # Modifying package.json invalidates the Bun hash stamp.
    pkg.write_text('{"name":"wa-bridge","version":"1.0.1"}\n', encoding="utf-8")
    assert main_platform_setup._whatsapp_bridge_dependencies_current(bridge_dir) is False


def test_whatsapp_dashboard_pairing_spawns_bun_on_debian(monkeypatch, tmp_path):
    from gateway.platforms import whatsapp_common

    bridge_dir = tmp_path / "whatsapp-bridge"
    bridge_dir.mkdir()
    bridge_script = bridge_dir / "bridge.js"
    bridge_script.write_text("", encoding="utf-8")
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    fake_bun = _make_executable(tmp_path / "bin" / "bun")

    spawned: list[list[str]] = []

    def fake_spawn_owned(cmd, **kwargs):
        spawned.append(list(cmd))
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(whatsapp_common, "resolve_whatsapp_bridge_dir", lambda: bridge_dir)
    monkeypatch.setattr(messaging, "_ensure_whatsapp_bridge_dependencies", lambda d: None)
    monkeypatch.setattr(messaging, "spawn_owned", fake_spawn_owned)
    monkeypatch.delenv("HERMES_JS_RUNTIME", raising=False)
    monkeypatch.setenv("HERMES_BUN", str(fake_bun))
    monkeypatch.setattr(js_runtime, "is_debian_family", lambda: True)

    messaging._spawn_whatsapp_pairing_process(session_dir, "bot")
    assert spawned[-1][:2] == [str(fake_bun), str(bridge_script)]
    assert "--pair-only" in spawned[-1]
