"""Tests for resolve_whatsapp_bridge_dir() — read-only install tree handling.

Regression coverage for #49561: in the Docker image the install tree
(/opt/hermes/scripts/whatsapp-bridge) is read-only, so `npm install` fails
with EACCES. The resolver must detect the read-only install dir and mirror the
bridge source into a writable HERMES_HOME location instead.
"""
import importlib
import stat
from pathlib import Path

import pytest

from gateway.platforms import whatsapp_common


def _seed_install_tree(install_bridge: Path) -> None:
    """Create a minimal fake bridge source tree."""
    install_bridge.mkdir(parents=True, exist_ok=True)
    (install_bridge / "bridge.js").write_text("// bridge\n")
    (install_bridge / "package.json").write_text('{"name": "whatsapp-bridge"}\n')
    nested = install_bridge / "lib"
    nested.mkdir(exist_ok=True)
    (nested / "helper.js").write_text("// helper\n")


def test_writable_install_returns_install_dir(tmp_path, monkeypatch):
    """When the install tree is writable, the resolver returns it unchanged."""
    install_root = tmp_path / "install"
    install_bridge = install_root / "scripts" / "whatsapp-bridge"
    _seed_install_tree(install_bridge)

    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()

    # Point the resolver's two anchors at our temp dirs.
    monkeypatch.setattr(
        whatsapp_common, "__file__",
        str(install_root / "gateway" / "platforms" / "whatsapp_common.py"),
    )
    monkeypatch.setattr(
        "hermes_constants.get_hermes_home", lambda: hermes_home
    )

    resolved = whatsapp_common.resolve_whatsapp_bridge_dir()
    assert resolved == install_bridge
    # Nothing mirrored into HERMES_HOME.
    assert not (hermes_home / "scripts" / "whatsapp-bridge").exists()


def test_readonly_install_mirrors_to_hermes_home(tmp_path, monkeypatch):
    """A read-only install tree is mirrored into a writable HERMES_HOME."""
    install_root = tmp_path / "install"
    install_bridge = install_root / "scripts" / "whatsapp-bridge"
    _seed_install_tree(install_bridge)

    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()

    monkeypatch.setattr(
        whatsapp_common, "__file__",
        str(install_root / "gateway" / "platforms" / "whatsapp_common.py"),
    )
    monkeypatch.setattr(
        "hermes_constants.get_hermes_home", lambda: hermes_home
    )

    # Simulate a read-only install tree. chmod(0o555) is unreliable under
    # root (CI/Docker bypass permission bits), so force the write probe to
    # fail by raising on the .write_test touch for the install dir only.
    _real_touch = Path.touch

    def _fake_touch(self, *a, **kw):
        if self.name == ".write_test" and install_bridge in self.parents:
            raise PermissionError("read-only install tree")
        return _real_touch(self, *a, **kw)

    monkeypatch.setattr(Path, "touch", _fake_touch)

    resolved = whatsapp_common.resolve_whatsapp_bridge_dir()

    expected = hermes_home / "scripts" / "whatsapp-bridge"
    assert resolved == expected
    # Source was mirrored, not symlinked.
    assert (expected / "bridge.js").read_text() == "// bridge\n"
    assert (expected / "package.json").exists()


def test_readonly_install_reuses_existing_mirror(tmp_path, monkeypatch):
    """If the HERMES_HOME mirror already exists, return it without re-copying."""
    install_root = tmp_path / "install"
    install_bridge = install_root / "scripts" / "whatsapp-bridge"
    _seed_install_tree(install_bridge)

    hermes_home = tmp_path / "hermes_home"
    mirror = hermes_home / "scripts" / "whatsapp-bridge"
    mirror.mkdir(parents=True)
    # A sentinel file proves the resolver returned the EXISTING mirror
    # rather than wiping/recopying it.
    (mirror / "node_modules").mkdir()
    (mirror / "node_modules" / "sentinel").write_text("keep me\n")

    monkeypatch.setattr(
        whatsapp_common, "__file__",
        str(install_root / "gateway" / "platforms" / "whatsapp_common.py"),
    )
    monkeypatch.setattr(
        "hermes_constants.get_hermes_home", lambda: hermes_home
    )

    _real_touch = Path.touch

    def _fake_touch(self, *a, **kw):
        if self.name == ".write_test" and install_bridge in self.parents:
            raise PermissionError("read-only install tree")
        return _real_touch(self, *a, **kw)

    monkeypatch.setattr(Path, "touch", _fake_touch)

    resolved = whatsapp_common.resolve_whatsapp_bridge_dir()

    assert resolved == mirror
    # Existing node_modules left intact (no destructive re-copy).
    assert (mirror / "node_modules" / "sentinel").read_text() == "keep me\n"


@pytest.fixture
def readonly_tree():
    """chmod a tree to 0o555 and restore it afterwards.

    Restoration matters: a read-only directory left behind in tmp_path breaks
    pytest's own cleanup for non-root users.
    """
    stripped: list[Path] = []

    def _apply(root: Path) -> None:
        for path in [root, *root.rglob("*")]:
            stripped.append(path)
            path.chmod(path.stat().st_mode & ~0o222)

    yield _apply

    for path in reversed(stripped):
        try:
            path.chmod(path.stat().st_mode | 0o200)
        except OSError:
            pass


def _force_readonly_probe(monkeypatch, install_bridge: Path) -> None:
    """Make the resolver's write probe fail for the install dir only.

    chmod(0o555) alone is not enough: root bypasses permission bits, so under
    CI/Docker the probe would succeed and the test would never reach the
    mirroring path it is meant to cover.
    """
    _real_touch = Path.touch

    def _fake_touch(self, *a, **kw):
        if self.name == ".write_test" and install_bridge in self.parents:
            raise PermissionError("read-only install tree")
        return _real_touch(self, *a, **kw)

    monkeypatch.setattr(Path, "touch", _fake_touch)


def _point_resolver_at(monkeypatch, install_root: Path, hermes_home: Path) -> None:
    monkeypatch.setattr(
        whatsapp_common, "__file__",
        str(install_root / "gateway" / "platforms" / "whatsapp_common.py"),
    )
    monkeypatch.setattr("hermes_constants.get_hermes_home", lambda: hermes_home)


def test_fresh_mirror_of_readonly_source_is_writable(
    tmp_path, monkeypatch, readonly_tree
):
    """The mirror must be writable even though the source it was copied from is not.

    Regression: shutil.copytree preserves the source mode, and the Docker image
    ships the bridge at 555 (`chmod -R a-w /opt/hermes`), so the mirror was born
    read-only and npm install failed with
    `EACCES: permission denied, mkdir '.../node_modules'` — the very error the
    mirror exists to avoid. Reproduced in the `huebner` container on 2026-08-28.
    """
    install_root = tmp_path / "install"
    install_bridge = install_root / "scripts" / "whatsapp-bridge"
    _seed_install_tree(install_bridge)
    readonly_tree(install_bridge)

    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()

    _point_resolver_at(monkeypatch, install_root, hermes_home)
    _force_readonly_probe(monkeypatch, install_bridge)

    mirror = whatsapp_common.resolve_whatsapp_bridge_dir()
    assert mirror == hermes_home / "scripts" / "whatsapp-bridge"

    # Mode bits, which hold even when running as root.
    assert mirror.stat().st_mode & stat.S_IWUSR
    assert (mirror / "package.json").stat().st_mode & stat.S_IWUSR
    assert (mirror / "lib").stat().st_mode & stat.S_IWUSR
    assert (mirror / "lib" / "helper.js").stat().st_mode & stat.S_IWUSR

    # And the real thing npm install does first.
    (mirror / "node_modules").mkdir()


def test_existing_readonly_mirror_is_healed(tmp_path, monkeypatch, readonly_tree):
    """A mirror left read-only by the old code is repaired, not returned as-is.

    Production containers already have one of these on disk, so fixing only the
    copytree path would leave them broken forever: the resolver short-circuits
    on `hermes_home_bridge.exists()` and never re-copies.
    """
    install_root = tmp_path / "install"
    install_bridge = install_root / "scripts" / "whatsapp-bridge"
    _seed_install_tree(install_bridge)

    hermes_home = tmp_path / "hermes_home"
    mirror = hermes_home / "scripts" / "whatsapp-bridge"
    mirror.mkdir(parents=True)
    (mirror / "bridge.js").write_text("// bridge\n")
    (mirror / "package.json").write_text('{"name": "whatsapp-bridge"}\n')
    readonly_tree(mirror)

    _point_resolver_at(monkeypatch, install_root, hermes_home)
    _force_readonly_probe(monkeypatch, install_bridge)

    resolved = whatsapp_common.resolve_whatsapp_bridge_dir()

    assert resolved == mirror
    assert mirror.stat().st_mode & stat.S_IWUSR
    assert (mirror / "package.json").stat().st_mode & stat.S_IWUSR
    (mirror / "node_modules").mkdir()


def test_existing_mirror_node_modules_left_untouched(
    tmp_path, monkeypatch, readonly_tree
):
    """Healing an existing mirror skips node_modules.

    npm creates that tree under its own umask (already writable), and walking
    Baileys' dependency tree on every gateway start would cost tens of thousands
    of syscalls for no benefit.
    """
    install_root = tmp_path / "install"
    install_bridge = install_root / "scripts" / "whatsapp-bridge"
    _seed_install_tree(install_bridge)

    hermes_home = tmp_path / "hermes_home"
    mirror = hermes_home / "scripts" / "whatsapp-bridge"
    mirror.mkdir(parents=True)
    (mirror / "package.json").write_text('{"name": "whatsapp-bridge"}\n')
    vendored = mirror / "node_modules" / "baileys"
    vendored.mkdir(parents=True)
    pinned = vendored / "index.js"
    pinned.write_text("// vendored\n")
    pinned.chmod(0o444)
    before = pinned.stat().st_mode

    readonly_tree(mirror / "package.json")

    _point_resolver_at(monkeypatch, install_root, hermes_home)
    _force_readonly_probe(monkeypatch, install_bridge)

    resolved = whatsapp_common.resolve_whatsapp_bridge_dir()

    assert resolved == mirror
    assert mirror.stat().st_mode & stat.S_IWUSR
    assert pinned.stat().st_mode == before
    assert pinned.read_text() == "// vendored\n"
