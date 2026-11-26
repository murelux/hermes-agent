"""Behavioral tests for Photon sidecar install and launch under opt-in Bun vs default Node."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from hermes_cli import js_runtime
from plugins.platforms.photon import adapter as photon_adapter
from plugins.platforms.photon import cli as photon_cli
from plugins.platforms.photon import sidecar_paths


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _enable_bun_opt_in(monkeypatch, fake_bun: Path) -> None:
    import pm

    monkeypatch.setattr(pm, "ensure", lambda pkg, **kw: SimpleNamespace(env={"PATH": str(fake_bun.parent)}))
    monkeypatch.setattr(pm, "installed_package", lambda pkg: SimpleNamespace(binary=fake_bun) if pkg == "bun" else None)
    monkeypatch.setattr(js_runtime, "use_bun_js_runtime", lambda: True)


def test_photon_sidecar_reinstall_uses_bun_frozen_lockfile_and_patch_when_opted_in(monkeypatch, tmp_path):
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    (sidecar / "package.json").write_text('{"name":"photon-sidecar"}\n', encoding="utf-8")
    (sidecar / "bun.lock").write_text("{}\n", encoding="utf-8")
    (sidecar / "patch-spectrum-mixed-attachments.mjs").write_text("", encoding="utf-8")
    fake_bun = _make_executable(tmp_path / "bin" / "bun")

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        (sidecar / "node_modules").mkdir(exist_ok=True)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(photon_adapter, "_sidecar_dir", lambda: sidecar)
    monkeypatch.setattr(photon_adapter.subprocess, "run", fake_run)
    _enable_bun_opt_in(monkeypatch, fake_bun)

    photon_adapter._reinstall_sidecar_deps()

    assert calls[0] == [str(fake_bun), "install", "--frozen-lockfile"]
    assert calls[1][0] == str(fake_bun)
    assert calls[1][1].endswith("patch-spectrum-mixed-attachments.mjs")
    assert (sidecar / "node_modules" / sidecar_paths._BUN_INSTALL_STAMP).is_file()


def test_photon_sidecar_cli_install_uses_npm_ci_by_default(monkeypatch, tmp_path):
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    (sidecar / "package.json").write_text('{"name":"photon-sidecar"}\n', encoding="utf-8")
    fake_npm = _make_executable(tmp_path / "bin" / "npm")

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(photon_cli, "_sidecar_dir", lambda: sidecar)
    monkeypatch.setattr(photon_cli, "_npm_error_log", lambda: tmp_path / "npm.err")
    monkeypatch.setattr(photon_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(js_runtime, "use_bun_js_runtime", lambda: False)
    monkeypatch.setattr(js_runtime, "find_node_executable", lambda name: str(fake_npm) if name == "npm" else None)

    assert photon_cli._install_sidecar() == 0
    assert calls == [[str(fake_npm), "ci"]]


def test_photon_lock_staleness_checks_bun_lock_when_opted_in(monkeypatch, tmp_path):
    sidecar = tmp_path / "sidecar"
    (sidecar / "node_modules").mkdir(parents=True)
    bun_lock = sidecar / "bun.lock"
    stamp = sidecar / "node_modules" / sidecar_paths._BUN_INSTALL_STAMP
    bun_lock.write_text("{}\n", encoding="utf-8")
    stamp.write_text("bun\n", encoding="utf-8")

    monkeypatch.setattr(js_runtime, "use_bun_js_runtime", lambda: True)

    os.utime(bun_lock, (100, 100))
    os.utime(stamp, (200, 200))
    assert sidecar_paths._lock_newer_than_install(sidecar) is False

    os.utime(bun_lock, (300, 300))
    assert sidecar_paths._lock_newer_than_install(sidecar) is True


def test_photon_bun_lock_is_committed_and_mirrored():
    assert "bun.lock" in sidecar_paths._MIRROR_FILES
    assert (sidecar_paths.SOURCE_SIDECAR_DIR / "bun.lock").is_file()
