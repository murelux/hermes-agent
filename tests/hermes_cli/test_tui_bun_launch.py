"""Behavioral tests for TUI and Dashboard PTY launches under Bun (Debian) vs Node."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_cli import js_runtime, main_tui_launch


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_prebuilt_tui_launch_uses_bun_without_expose_gc_on_debian(monkeypatch, tmp_path):
    import pm

    tui_dir = tmp_path / "prebuilt-tui"
    entry = tui_dir / "dist" / "entry.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("console.log('ok')\n", encoding="utf-8")
    fake_bun = _make_executable(tmp_path / "store" / "bun" / "bun")
    fake_node = _make_executable(tmp_path / "store" / "node" / "node")

    ensured: list[str] = []

    def fake_ensure(pkg, **kwargs):
        ensured.append(pkg)
        return SimpleNamespace(env={"PATH": str(fake_bun.parent)})

    monkeypatch.setattr(pm, "ensure", fake_ensure)
    monkeypatch.setattr(pm, "installed_package", lambda pkg: SimpleNamespace(binary=fake_bun) if pkg == "bun" else None)
    monkeypatch.delenv("HERMES_JS_RUNTIME", raising=False)
    monkeypatch.delenv("HERMES_BUN", raising=False)
    monkeypatch.setenv("HERMES_NODE", str(fake_node))
    monkeypatch.setenv("HERMES_TUI_DIR", str(tui_dir))
    monkeypatch.setattr(js_runtime, "is_debian_family", lambda: True)

    argv, cwd = main_tui_launch._make_tui_argv(tmp_path / "unused-source", tui_dev=False)

    assert argv == [str(fake_bun), str(entry)]
    assert cwd == tui_dir
    assert "--expose-gc" not in argv
    assert ensured == ["bun"]


def test_prebuilt_tui_launch_keeps_node_and_expose_gc_when_gate_is_false(monkeypatch, tmp_path):
    tui_dir = tmp_path / "prebuilt-tui"
    entry = tui_dir / "dist" / "entry.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("console.log('ok')\n", encoding="utf-8")
    fake_node = _make_executable(tmp_path / "store" / "node" / "node")

    monkeypatch.setenv("HERMES_NODE", str(fake_node))
    monkeypatch.setenv("HERMES_TUI_DIR", str(tui_dir))
    monkeypatch.setattr(js_runtime, "is_debian_family", lambda: False)

    argv, cwd = main_tui_launch._make_tui_argv(tmp_path / "unused-source", tui_dev=False)

    assert argv == [str(fake_node), "--expose-gc", str(entry)]
    assert cwd == tui_dir


def test_launch_tui_omits_v8_max_old_space_size_on_bun_and_sets_it_on_node(monkeypatch, tmp_path):
    fake_bun = _make_executable(tmp_path / "bun")
    fake_node = _make_executable(tmp_path / "node")
    captured_envs: list[dict[str, str]] = []

    def fake_run_tui(argv, cwd, env, notices):
        captured_envs.append(dict(env))
        return 0

    tui_dir = tmp_path / "prebuilt-tui"
    entry = tui_dir / "dist" / "entry.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("", encoding="utf-8")

    monkeypatch.setenv("HERMES_TUI_DIR", str(tui_dir))
    monkeypatch.delenv("NODE_OPTIONS", raising=False)
    monkeypatch.setattr(main_tui_launch, "_resolve_tui_heap_mb", lambda: 1536)
    monkeypatch.setattr(main_tui_launch, "_apply_tui_python_env", lambda env: None)
    monkeypatch.setattr(main_tui_launch, "_run_tui", fake_run_tui)
    monkeypatch.setattr(main_tui_launch, "_print_tui_exit_summary", lambda *args, **kwargs: None)

    # Debian Bun path: NODE_OPTIONS must NOT receive --max-old-space-size.
    monkeypatch.delenv("HERMES_JS_RUNTIME", raising=False)
    monkeypatch.setenv("HERMES_BUN", str(fake_bun))
    monkeypatch.setattr(js_runtime, "is_debian_family", lambda: True)
    with pytest.raises(SystemExit) as exc_bun:
        main_tui_launch._launch_tui(tui_dev=False)
    assert exc_bun.value.code == 0
    assert "--max-old-space-size" not in captured_envs[-1].get("NODE_OPTIONS", "")

    # Node path: NODE_OPTIONS MUST receive --max-old-space-size=1536.
    monkeypatch.setenv("HERMES_JS_RUNTIME", "node")
    monkeypatch.setenv("HERMES_NODE", str(fake_node))
    with pytest.raises(SystemExit) as exc_node:
        main_tui_launch._launch_tui(tui_dev=False)
    assert exc_node.value.code == 0
    assert "--max-old-space-size=1536" in captured_envs[-1].get("NODE_OPTIONS", "")


def test_dashboard_chat_pty_inherits_bun_argv_on_debian(monkeypatch, tmp_path):
    from hermes_cli import web_server_chat

    tui_dir = tmp_path / "prebuilt-tui"
    entry = tui_dir / "dist" / "entry.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("", encoding="utf-8")
    fake_bun = _make_executable(tmp_path / "bun")

    monkeypatch.delenv("HERMES_JS_RUNTIME", raising=False)
    monkeypatch.setenv("HERMES_BUN", str(fake_bun))
    monkeypatch.setenv("HERMES_TUI_DIR", str(tui_dir))
    monkeypatch.setattr(js_runtime, "is_debian_family", lambda: True)

    argv, cwd, _env = web_server_chat._resolve_chat_argv()

    assert argv[0] == str(fake_bun)
    assert str(entry) in argv
    assert "--expose-gc" not in argv
    assert cwd == str(tui_dir)
