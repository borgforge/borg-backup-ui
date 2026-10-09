"""Private workflow regressions using local files, fake GitHub data and real Git."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin"))
import security_workflow as sw
import release_workflow as rw

ADVISORY = "GHSA-h4gr-4cm5-92gr"
FORK = f"{sw.PUBLIC_REPO}-{ADVISORY.lower()}"
VERSION = "2026.09.24.1500"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Create an isolated Git checkout with no real network credentials needed."""
    root = tmp_path / "repo"
    root.mkdir()
    for args in (("init", "-b", "main"), ("config", "user.name", "Test"),
                 ("config", "user.email", "test@example.invalid")):
        sw.git(root, *args)
    (root / "borg_backup_ui.py").write_text('APP_VERSION = "old"\n')
    (root / "borg-backup-ui.plg").write_text((ROOT / "borg-backup-ui.plg").read_text())
    (root / "releases").mkdir()
    (root / "release-notes/pending").mkdir(parents=True)
    (root / f"release-notes/pending/{ADVISORY}.md").write_text("### Security\n\n- Fix history access.\n")
    (root / ".gitignore").write_text(".release-tmp/\n")
    sw.git(root, "add", ".")
    sw.git(root, "commit", "-m", "base")
    sw.git(root, "remote", "add", "origin", f"git@github.com:{sw.PUBLIC_REPO}.git")
    sw.git(root, "remote", "add", "security", f"ssh://git@github.com/{FORK}.git")
    monkeypatch.setattr(sw, "gh_json", lambda endpoint: {"login": "borg-codex-bot"} if endpoint == "user" else {
        "ghsa_id": ADVISORY, "state": "draft", "private_fork": {"full_name": FORK, "private": True}})
    return root


def context(repo):
    return sw.init_context(repo, ADVISORY, "security", "main")


def test_context_binds_actual_advisory_and_both_remote_urls(repo):
    result = context(repo)
    assert result["repository"] == FORK
    assert sw.load_context(repo) == result
    sw.git(repo, "remote", "set-url", "--push", "security", f"git@github.com:{sw.PUBLIC_REPO}.git")
    with pytest.raises(RuntimeError, match="only the advisory"):
        sw.validate_context(repo, result)


@pytest.mark.parametrize("change", ["public", "wrong-fork", "published", "wrong-user", "missing-fork", "api-denied"])
def test_context_rejects_unverified_private_target(repo, monkeypatch, change):
    def api(endpoint):
        if change == "api-denied":
            raise RuntimeError("API unavailable")
        if endpoint == "user":
            return {"login": "TheTwist76" if change == "wrong-user" else "borg-codex-bot"}
        fork = {"full_name": "elsewhere/repo" if change == "wrong-fork" else FORK,
                "private": change != "public"}
        return {"ghsa_id": ADVISORY, "state": "published" if change == "published" else "draft",
                "private_fork": None if change == "missing-fork" else fork}
    monkeypatch.setattr(sw, "gh_json", api)
    with pytest.raises(RuntimeError):
        context(repo)
    assert not sw.local_path(repo, "security-context.json").exists()


@pytest.mark.parametrize("url", ["https://token@github.com/a/b.git", "ssh://git@evil.example/a/b.git", "/local/repo.git"])
def test_private_remote_rejects_credentials_and_wrong_host(url):
    with pytest.raises(RuntimeError):
        sw.github_repository(url)


def test_guard_blocks_all_public_entrypoints_before_side_effects(repo):
    context(repo)
    (repo / "plugin").mkdir()
    for name in ("security_workflow.py", "release_workflow.py", "deploy-test.sh", "promote-release.sh",
                 "publish-test-snapshot.sh", "mr-preflight.sh", "deploy.sh"):
        shutil.copy2(ROOT / "plugin" / name, repo / "plugin" / name)
    for name, args in (("deploy-test.sh", [VERSION]), ("promote-release.sh", [VERSION]),
                       ("mr-preflight.sh", []), ("deploy.sh", ["example.invalid"]),
                       ("publish-test-snapshot.sh", [])):
        result = subprocess.run(["bash", str(repo / "plugin" / name), *args], cwd=repo,
                                capture_output=True, text=True)
        assert result.returncode != 0
        assert "public deployment blocked" in result.stderr
    assert not (repo / ".release-tmp").exists()


def test_guard_works_without_context_and_across_worktrees(repo, tmp_path):
    sw.guard_public(repo)
    sw.git(repo, "switch", "-c", "codex/security-ghsa-h4gr-4cm5-92gr")
    with pytest.raises(RuntimeError):
        sw.guard_public(repo)
    context(repo)
    other = tmp_path / "linked"
    sw.git(repo, "worktree", "add", "-b", "codex/other", str(other))
    with pytest.raises(RuntimeError):
        sw.guard_public(other)


def test_remote_tip_must_match_before_tests_run(repo, monkeypatch):
    ctx = context(repo)
    sw.git(repo, "switch", "-c", "codex/fix")
    real_git = sw.git
    monkeypatch.setattr(sw, "git", lambda root, *args: "" if args[0] == "fetch" else
                        "wrong-sha\trefs/heads/codex/fix" if args[0] == "ls-remote" else real_git(root, *args))
    with pytest.raises(RuntimeError, match="pushed exactly"):
        sw.check_source(repo, ctx)


def test_preflight_rejects_failure_and_changed_source(repo, monkeypatch):
    ctx = context(repo)
    source = {"context": ctx, "head_sha": "a" * 40, "branch": "codex/fix", "base_sha": "b" * 40,
              "source_digest": "c" * 64}
    monkeypatch.setattr(sw, "check_source", lambda *_: source)
    def failed_run(*args, **kwargs):
        kwargs["stdout"].write("test failed\n")
        return subprocess.CompletedProcess(args, 1)
    monkeypatch.setattr(sw.subprocess, "run", failed_run)
    # Avoid real Git in local_path after replacing subprocess.run.
    monkeypatch.setattr(sw, "local_path", lambda _root, name: repo / ".git" / "borg-backup-ui" / name)
    with pytest.raises(RuntimeError, match="tests failed"):
        sw.preflight(repo)
    assert not sw.local_path(repo, "security-preflight.json").exists()
    def successful_run(*args, **kwargs):
        kwargs["stdout"].write("1 passed\n")
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(sw.subprocess, "run", successful_run)
    calls = iter([source, {**source, "head_sha": "d" * 40}])
    monkeypatch.setattr(sw, "check_source", lambda *_: next(calls))
    with pytest.raises(RuntimeError, match="changed during"):
        sw.preflight(repo)
    assert not sw.local_path(repo, "security-preflight.json").exists()


def test_attestation_rejects_changed_commit_or_report(repo, monkeypatch):
    ctx = context(repo)
    report = repo / ".release-tmp/tests.log"
    report.parent.mkdir()
    report.write_text("1 passed\n")
    state = {"context": ctx, "head_sha": "a" * 40, "branch": "codex/fix", "base_sha": "b" * 40,
             "source_digest": "c" * 64}
    attest = {**state, "result": "passed", "syntax": "passed", "report_path": ".release-tmp/tests.log",
              "report_sha256": sw.sha256(report)}
    sw.write_json(sw.local_path(repo, "security-preflight.json"), attest)
    monkeypatch.setattr(sw, "check_source", lambda *_: state)
    assert sw.verify_attestation(repo) == attest
    state["head_sha"] = "d" * 40
    with pytest.raises(RuntimeError, match="stale"):
        sw.verify_attestation(repo)
    state["head_sha"] = "a" * 40
    report.write_text("edited")
    with pytest.raises(RuntimeError, match="report"):
        sw.verify_attestation(repo)


def test_successful_preflight_attests_exact_source_and_report(repo, monkeypatch):
    ctx = context(repo)
    state = {"context": ctx, "head_sha": "a" * 40, "branch": "codex/fix", "base_sha": "b" * 40,
             "source_digest": "c" * 64}
    monkeypatch.setattr(sw, "check_source", lambda *_: state)
    monkeypatch.setattr(sw, "local_path", lambda _root, name: repo / ".git" / "borg-backup-ui" / name)
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        kwargs["stdout"].write("10 passed, 2 skipped\n")
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(sw.subprocess, "run", run)
    attest = sw.preflight(repo)
    assert len(commands) == 1 and "pytest" in commands[0]
    assert sw.verify_attestation(repo) == attest
    assert (repo / attest["report_path"]).read_text() == "10 passed, 2 skipped\n"


def test_build_stops_before_output_when_preflight_is_invalid(repo, monkeypatch):
    def reject(*_):
        raise RuntimeError("stale")
    monkeypatch.setattr(sw, "verify_attestation", reject)
    with pytest.raises(RuntimeError, match="stale"):
        sw.build(repo, VERSION)
    assert not (repo / ".release-tmp").exists()


def write_test_package(path, provenance):
    """Produce a small real package satisfying production archive verification."""
    bundle = io.BytesIO()
    with tarfile.open(fileobj=bundle, mode="w:xz") as archive:
        item = tarfile.TarInfo("apprise/__init__.py")
        archive.addfile(item, io.BytesIO(b""))
    payload = bundle.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    prefix = f"boot/config/plugins/{rw.NAME}/"
    data = {name: b"fixture" for name in rw.EXPECTED_PACKAGE_MEMBERS}
    data[prefix + "borg_backup_ui.py"] = f'APP_VERSION = "{VERSION}"\n'.encode()
    data[rw.PROVENANCE_MEMBER] = json.dumps(provenance).encode()
    meta = {"bundle": "apprise-test.tar.xz", "sha256": digest, "version": "test"}
    data[prefix + "runtime/vendor-bundles/apprise-vendor.json"] = json.dumps(meta, indent=2).encode()
    data[prefix + "runtime/vendor-bundles/apprise-test.tar.xz"] = payload
    with tarfile.open(path, "w:xz") as archive:
        for name, content in data.items():
            info = tarfile.TarInfo(name)
            info.mode = 0o644
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


@pytest.fixture
def candidate(repo, monkeypatch):
    """Run the actual private bundle assembly with only the heavy builder replaced."""
    ctx = context(repo)
    report = repo / ".release-tmp/tests.log"
    report.parent.mkdir()
    report.write_text("1 passed\n")
    head = sw.git(repo, "rev-parse", "HEAD")
    attest = {"context": ctx, "head_sha": head, "base_sha": head, "source_digest": rw.source_digest(repo, head),
              "result": "passed", "syntax": "passed", "report_path": ".release-tmp/tests.log",
              "report_sha256": sw.sha256(report)}
    commands = []
    real_run = subprocess.run
    def fake_builder(command, **kwargs):
        commands.append(command)
        assert command[0] == "bash" and command[1].endswith("/build-candidate.sh")
        work = Path(command[-1])
        source = work / "source"
        source.mkdir()
        for name in ("borg_backup_ui.py", "borg-backup-ui.plg"):
            shutil.copy2(repo / name, source / name)
        shutil.copytree(repo / "release-notes", source / "release-notes")
        provenance = rw.prepare_build_tree(source, VERSION, head, head, attest["source_digest"], "2026-09-24T00:00:00Z")
        (work / "releases").mkdir()
        write_test_package(work / f"releases/{rw.NAME}-{VERSION}.txz", provenance)
        return subprocess.CompletedProcess(command, 0)
    # local_path and Git are not invoked by build once the attestation has been verified.
    with monkeypatch.context() as patch:
        patch.setattr(sw, "verify_attestation", lambda *_: attest)
        patch.setattr(sw.subprocess, "run", fake_builder)
        directory = sw.build(repo, VERSION)
    assert len(commands) == 1  # No git push, gh, tests, or network publication by the build.
    assert subprocess.run is real_run
    return directory


def test_candidate_and_local_release_keep_identical_package(repo, candidate):
    before = sw.verify_candidate(candidate, VERSION)
    output = sw.prepare_release(repo, candidate, VERSION)
    name = f"{rw.NAME}-{VERSION}.txz"
    assert sw.sha256(output / "releases" / name) == before["files"][name]
    assert rw.manifest_md5(output / f"{rw.NAME}.plg") == rw.file_md5(candidate / name)
    assert not (output / f"release-notes/pending/{ADVISORY}.md").exists()
    assert (repo / f"release-notes/pending/{ADVISORY}.md").exists()
    assert sw.git(repo, "status", "--porcelain") == ""


def test_tested_candidate_is_never_overwritten(repo, candidate, monkeypatch):
    data = sw.verify_candidate(candidate)
    monkeypatch.setattr(sw, "verify_attestation", lambda *_: data["attestation"])
    with pytest.raises(RuntimeError, match="already exists"):
        sw.build(repo, VERSION)
    assert sw.verify_candidate(candidate) == data


@pytest.mark.parametrize("filename", [f"{rw.NAME}-{VERSION}.txz", "release-template.plg", f"{rw.NAME}.plg",
                                      "tests.log", "release-notes.md", "SHA256SUMS"])
def test_candidate_rejects_changed_artifacts(candidate, filename):
    with (candidate / filename).open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(RuntimeError):
        sw.verify_candidate(candidate)


def test_candidate_rejects_wrong_version_and_path_in_metadata(candidate):
    with pytest.raises(RuntimeError, match="version"):
        sw.verify_candidate(candidate, "2026.09.24.1501")
    path = candidate / "candidate.json"
    data = json.loads(path.read_text())
    data["files"]["../outside.txt"] = "a" * 64
    sw.write_json(path, data)
    with pytest.raises(RuntimeError, match="file list"):
        sw.verify_candidate(candidate)


def test_publication_needs_matching_explicit_advisory(repo, candidate):
    with pytest.raises(RuntimeError, match="must match"):
        sw.authorize_publication(repo, candidate, "GHSA-2222-2222-2222")
    sw.authorize_publication(repo, candidate, ADVISORY)
    sw.git(repo, "remote", "set-url", "origin", f"git@github.com:{FORK}.git")
    with pytest.raises(RuntimeError, match="parent repository"):
        sw.authorize_publication(repo, candidate, ADVISORY)


def test_context_cannot_be_finished_before_disclosure(repo, monkeypatch):
    context(repo)
    with pytest.raises(RuntimeError, match="until the advisory is published"):
        sw.finish_context(repo, ADVISORY)
    monkeypatch.setattr(sw, "gh_json", lambda _: {"ghsa_id": ADVISORY, "state": "published"})
    sw.finish_context(repo, ADVISORY)
    sw.guard_public(repo)
    assert sw.local_path(repo, f"security-completed-{ADVISORY}.json").exists()


def test_private_manifest_refuses_missing_and_bad_package_without_download(candidate, tmp_path):
    text = (candidate / f"{rw.NAME}.plg").read_text()
    assert 'pluginURL="' not in text
    block = text.split(rw.PACKAGE_INSTALL_BEGIN)[1].split(rw.PACKAGE_INSTALL_END)[0]
    script = block.split("<INLINE>")[1].split("</INLINE>")[0]
    script = script.replace("&version;", VERSION).replace("&pkgurl;", "").replace("&name;", rw.NAME)
    script = script.replace("/boot/config/plugins", str(tmp_path / "boot"))
    script = script.replace('PACKAGE_INSTALL_SCRIPT="/tmp/', 'PACKAGE_INSTALL_SCRIPT="' + str(tmp_path) + '/')
    assert "curl " not in script and "wget " not in script
    for content, marker in ((None, "must be copied locally"), (b"wrong", "SHA-256 mismatch")):
        target = tmp_path / "boot" / rw.NAME / f"{rw.NAME}-{VERSION}.txz"
        if content is not None:
            target.write_bytes(content)
        result = subprocess.run(["bash"], input=script, text=True, capture_output=True)
        assert result.returncode != 0
        assert marker in result.stdout


def test_private_installer_install_repeat_and_boot_repair(candidate, tmp_path):
    """Run generated installer in a sandbox, simulating only Slackware upgradepkg."""
    text = (candidate / f"{rw.NAME}.plg").read_text()
    block = text.split(rw.PACKAGE_INSTALL_BEGIN)[1].split(rw.PACKAGE_INSTALL_END)[0]
    script = block.split("<INLINE>")[1].split("</INLINE>")[0]
    script = script.replace("&version;", VERSION).replace("&pkgurl;", "").replace("&name;", rw.NAME)
    machine = tmp_path / "machine"
    machine.mkdir()
    for prefix in ("/boot/config/plugins", "/etc/rc.d", "/var/log/packages", "/tmp"):
        (machine / prefix.lstrip("/")).mkdir(parents=True, exist_ok=True)
        script = script.replace(prefix, str(machine / prefix.lstrip("/")))
    script = script.replace('tar -xf "${PACKAGE_FILE}" -C /', 'tar -xf "${PACKAGE_FILE}" -C ' + str(machine))
    package = f"{rw.NAME}-{VERSION}.txz"
    plugin = machine / "boot/config/plugins" / rw.NAME
    plugin.mkdir()
    shutil.copy2(candidate / package, plugin / package)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    upgrade = bindir / "upgradepkg"
    count = tmp_path / "upgrades"
    upgrade.write_text(f'''#!/bin/bash
set -e
echo called >> '{count}'
tar -xf "$2" -C '{machine}'
touch '{machine}/var/log/packages/{rw.NAME}-{VERSION}'
''')
    upgrade.chmod(0o755)
    env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ["PATH"])
    def install():
        result = subprocess.run(["bash"], input=script, text=True, capture_output=True, env=env)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'downloads are disabled' not in result.stdout
    install()
    assert (plugin / "runtime/vendor/apprise/__init__.py").exists()
    install()
    assert count.read_text().splitlines() == ["called"]
    # /etc is volatile on Unraid. Simulate reboot with payload on flash retained.
    (machine / "etc/rc.d/rc.borg_backup_ui").unlink()
    install()
    assert (machine / "etc/rc.d/rc.borg_backup_ui").exists()
    assert count.read_text().splitlines() == ["called"]
