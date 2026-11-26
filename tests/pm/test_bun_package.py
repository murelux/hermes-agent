"""Behavioral contracts for the PM-managed Bun package (Debian-family Linux only)."""

from __future__ import annotations

import argparse
import json

import pytest

from pm import Lockfile, _distro, get_package, paths, registry, store
from pm.store import ALL_TARGETS


def test_bun_lockfile_artifacts_match_supported_linux_targets():
    package = get_package("bun")
    lock = Lockfile(paths.lockfile_path())
    version = lock.version("bun")

    assert package.optional is True
    assert package.default is False

    for target in ALL_TARGETS:
        if target in ("linux-x64", "linux-arm64"):
            assert package.missing_reason(target) is None, target
            artifacts = lock.artifacts("bun", target)
            assert [a["url"] for a in artifacts] == package.fetch_urls(version, target)
            assert all(len(a["sha256"]) == 64 for a in artifacts)
        else:
            assert package.missing_reason(target) is not None, target
            assert lock.artifacts("bun", target) == []


@pytest.mark.parametrize("target", ["linux-x64", "linux-arm64"])
def test_debian_source_install_selects_bun_and_omits_node_toolchain(monkeypatch, target):
    monkeypatch.delenv("HERMES_JS_RUNTIME", raising=False)
    monkeypatch.setattr(_distro, "is_debian_family", lambda: True)
    monkeypatch.setattr(store, "current_target", lambda: target)

    names = Lockfile(paths.lockfile_path()).names()
    selected = registry.source_install_packages(names)

    assert "bun" in selected
    assert "node" not in selected
    assert "npm" not in selected
    assert "pnpm" not in selected


@pytest.mark.parametrize("target", ["linux-x64", "linux-arm64"])
def test_debian_fallback_env_restores_node_toolchain(monkeypatch, target):
    monkeypatch.setenv("HERMES_JS_RUNTIME", "node")
    monkeypatch.setattr(_distro, "is_debian_family", lambda: True)
    monkeypatch.setattr(store, "current_target", lambda: target)

    names = Lockfile(paths.lockfile_path()).names()
    selected = registry.source_install_packages(names)

    assert "bun" not in selected
    assert "node" in selected
    assert "npm" in selected
    assert "pnpm" in selected


@pytest.mark.parametrize("target", ["linux-x64", "linux-arm64", "darwin-arm64", "win32-x64", "linux-x64-musl"])
def test_non_debian_hosts_never_pull_bun_in_default_closure(monkeypatch, target):
    monkeypatch.delenv("HERMES_JS_RUNTIME", raising=False)
    monkeypatch.setattr(_distro, "is_debian_family", lambda: False)
    monkeypatch.setattr(store, "current_target", lambda: target)

    names = Lockfile(paths.lockfile_path()).names()
    selected = registry.source_install_packages(names)

    assert "bun" not in selected
    assert "node" in selected


def test_bun_is_not_copied_to_user_facing_shims():
    from pm.user_facing import COPIED

    assert "bun" not in COPIED
    assert "node" in COPIED
    assert "npm" in COPIED


def test_pm_doctor_on_debian_requires_bun_and_treats_node_as_optional(tmp_path, monkeypatch, capsys):
    from pm import cli

    monkeypatch.delenv("HERMES_JS_RUNTIME", raising=False)
    monkeypatch.setattr(_distro, "is_debian_family", lambda: True)

    lock = json.loads(paths.lockfile_path().read_text(encoding="utf-8"))
    lock["packages"] = {name: lock["packages"][name] for name in ("bun", "node", "npm", "pnpm")}
    (tmp_path / "lock.json").write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(cli, "_lockfile", lambda: Lockfile(tmp_path / "lock.json"))
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(cli, "current_target", lambda: "linux-x64")
    monkeypatch.setattr(cli, "_doctor_uv_cache", lambda **_: 0)

    assert cli.cmd_doctor(argparse.Namespace()) == 1
    lines = capsys.readouterr().out.splitlines()
    assert "✗ bun: not installed" in lines
    assert "? node: not installed" in lines
    assert "? npm: not installed" in lines
    assert "? pnpm: not installed" in lines


def test_distro_os_release_tokens_match_debian_family(tmp_path):
    deb = tmp_path / "debian"
    deb.write_text('ID=debian\nVERSION_ID="13"\n', encoding="utf-8")
    assert bool(_distro.os_release_tokens(deb) & _distro.DEBIAN_FAMILY_IDS)

    ubuntu = tmp_path / "ubuntu"
    ubuntu.write_text('ID=ubuntu\nID_LIKE=debian\n', encoding="utf-8")
    assert bool(_distro.os_release_tokens(ubuntu) & _distro.DEBIAN_FAMILY_IDS)

    fedora = tmp_path / "fedora"
    fedora.write_text('ID=fedora\nVERSION_ID=41\n', encoding="utf-8")
    assert not (_distro.os_release_tokens(fedora) & _distro.DEBIAN_FAMILY_IDS)

    alpine = tmp_path / "alpine"
    alpine.write_text('ID=alpine\nVERSION_ID=3.20\n', encoding="utf-8")
    assert not (_distro.os_release_tokens(alpine) & _distro.DEBIAN_FAMILY_IDS)
