from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package_workflow", ROOT / "plugin/release_workflow.py")
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)

APP = "boot/config/plugins/borg-backup-ui"
UI = "usr/local/emhttp/plugins/borg-backup-ui"
RC = "etc/rc.d/rc.borg_backup_ui"
# The maintainer's actual Unraid 7.4.0-beta.2 reference, including non-0755 modes.
SHARED_MODES = {
    ".": 0o755, "boot": 0o700, "boot/config": 0o700,
    "boot/config/plugins": 0o700, "etc": 0o755, "etc/rc.d": 0o777,
    "usr": 0o755, "usr/local": 0o755, "usr/local/emhttp": 0o755,
    "usr/local/emhttp/plugins": 0o755, "mnt": 0o755, "var": 0o755,
}


def select_builder(tmp_path, monkeypatch, builder):
    original_which = shutil.which
    makepkg = None
    if builder == "makepkg":
        # Exercise the makepkg route and preserve its generated metadata/hooks.
        # This fixture is not a replacement for an actual Unraid install test.
        makepkg = tmp_path / "makepkg"
        makepkg.write_text(
            '#!/bin/sh\nset -eu\n'
            '[ "$1 $2 $3 $4" = "-l y -c y" ]\n'
            'printf "#!/bin/sh\\nexit 0\\n" > install/doinst.sh\n'
            'chmod 755 install/doinst.sh\n'
            'tar --create --xz --owner=123 --group=456 --file="$5" .\n'
        )
        makepkg.chmod(0o755)
    monkeypatch.setattr(workflow.shutil, "which", lambda name: (
        str(makepkg) if makepkg else None
    ) if name == "makepkg" else original_which(name))


@pytest.mark.parametrize("builder", ["tar", "makepkg"])
@pytest.mark.parametrize("build_umask", [0o002, 0o022, 0o077])
def test_package_preserves_existing_host_modes_and_payload(tmp_path, monkeypatch, builder, build_umask):
    select_builder(tmp_path, monkeypatch, builder)
    stage = tmp_path / "stage"
    package = tmp_path / "plugin.txz"
    old_umask = os.umask(build_umask)
    try:
        for path in (APP, UI, "etc/rc.d", "install"):
            (stage / path).mkdir(parents=True, exist_ok=True)
        for path in (f"{APP}/config.example", f"{UI}/plugin.page", "install/slack-desc"):
            (stage / path).write_bytes(b"unchanged payload\n")
        (stage / RC).write_text("#!/bin/sh\nexit 0\n")
        (stage / RC).chmod(0o755)
        (stage / APP / "config-link").symlink_to("config.example")
        os.link(stage / APP / "config.example", stage / APP / "config-hardlink")
        workflow.build_package(stage, package)
    finally:
        os.umask(old_umask)

    with tarfile.open(package) as archive:
        members = {m.name.removeprefix("./").rstrip("/"): m for m in archive}
        assert not set(members) & set(SHARED_MODES)
        assert all(m.uid == m.gid == 0 for m in members.values())
        assert members[APP].mode == 0o755
        assert members[UI].mode == 0o755
        assert members[f"{APP}/config.example"].mode == 0o644
        assert members[RC].mode == 0o755
        assert ("install/doinst.sh" in members) == (builder == "makepkg")
        if builder == "makepkg":
            assert archive.extractfile(members["install/doinst.sh"]).read() == b"#!/bin/sh\nexit 0\n"

    host = tmp_path / "host"
    host.mkdir()
    for name, mode in SHARED_MODES.items():
        directory = host / name
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(mode)
    # Also check intentional local customizations, not just stock 0755.
    (host / "usr/local").chmod(0o750)
    before = {name: (p.stat().st_mode, p.stat().st_uid, p.stat().st_gid)
              for name in SHARED_MODES for p in [host / name]}
    subprocess.run(["tar", "--extract", "--xz", "--same-permissions",
                    f"--file={package}", f"--directory={host}"], check=True)
    after = {name: (p.stat().st_mode, p.stat().st_uid, p.stat().st_gid)
             for name in SHARED_MODES for p in [host / name]}
    assert after == before
    for path in ("config.example", "config-link", "config-hardlink"):
        assert (host / APP / path).read_bytes() == b"unchanged payload\n"
    assert (host / RC).stat().st_mode & 0o777 == 0o755
    # Verify delivery on a fresh tree as well as preservation on an existing host.
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    subprocess.run(["tar", "-xJpf", str(package), "-C", str(fresh)], check=True)
    assert (fresh / RC).is_file()
    assert (fresh / APP / "config-link").read_bytes() == b"unchanged payload\n"


@pytest.mark.parametrize("name", [".", "./", "./usr", "etc/rc.d", "boot/config/plugins", "./var"])
def test_artifact_validation_rejects_shared_directories_even_with_0755(tmp_path, name):
    package = tmp_path / "bad.txz"
    with tarfile.open(package, "w:xz") as archive:
        member = tarfile.TarInfo(name)
        member.type = tarfile.DIRTYPE
        member.mode = 0o755
        archive.addfile(member)
    with pytest.raises(RuntimeError, match="shared or unexpected system path"):
        workflow.package_provenance(package)


@pytest.mark.parametrize("kind,mode,uid", [(tarfile.DIRTYPE, 0o775, 0),
                                         (tarfile.REGTYPE, 0o664, 0),
                                         (tarfile.REGTYPE, 0o4755, 0),
                                         (tarfile.REGTYPE, 0o644, 1000)])
def test_artifact_validation_rejects_unsafe_payload_metadata(kind, mode, uid):
    member = tarfile.TarInfo(APP + "/payload")
    member.type, member.mode, member.uid = kind, mode, uid
    with pytest.raises(RuntimeError, match="unsafe permissions|not owned by root"):
        workflow.verify_package_permissions([member])


def test_package_keeps_pax_owner_metadata_from_overriding_root(tmp_path, monkeypatch):
    package = tmp_path / "plugin.txz"
    with tarfile.open(package, "w:xz", format=tarfile.PAX_FORMAT) as archive:
        member = tarfile.TarInfo(APP + "/payload")
        member.mode = 0o664
        member.size = 1
        member.pax_headers = {"uid": "123", "gid": "456", "uname": "builder", "gname": "builder"}
        archive.addfile(member, io.BytesIO(b"x"))
    monkeypatch.setattr(workflow.subprocess, "run", lambda *a, **k: None)
    workflow.build_package(tmp_path, package)
    with tarfile.open(package) as archive:
        member = archive.getmembers()[0]
        assert member.uid == member.gid == 0
        assert member.uname == member.gname == "root"
        assert member.mode == 0o644


def test_failed_package_filter_does_not_replace_input(tmp_path, monkeypatch):
    package = tmp_path / "plugin.txz"
    with tarfile.open(package, "w:xz") as archive:
        archive.addfile(tarfile.TarInfo("etc/unrelated.conf"))
    original = package.read_bytes()
    monkeypatch.setattr(workflow.subprocess, "run", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="shared or unexpected system path"):
        workflow.build_package(tmp_path, package)
    assert package.read_bytes() == original
    assert not list(tmp_path.glob(".package-permissions-*"))
