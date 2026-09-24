#!/usr/bin/env python3
"""Private advisory preflight, local test packages and release preparation.

GitHub reads use the caller's authenticated gh process; Git uses its explicit
remote configuration. No command in this module pushes, creates PRs or publishes
an advisory. Context and test attestations live in Git's local common directory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET

import release_workflow as rw

PUBLIC_REPO = "borgforge/borg-backup-ui"
MODE = "security-private"
GHSA_RE = r"GHSA-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}"
VERSION_RE = r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]{4}"


def git(repo: Path, *args: str) -> str:
    """Run Git in the selected checkout, raising on failure without shell parsing."""
    return str(rw.run_git(repo, *args)).strip()


def local_path(repo: Path, name: str) -> Path:
    """Return repository-wide metadata shared by linked worktrees."""
    common = Path(git(repo, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = repo / common
    return common.resolve() / "borg-backup-ui" / name


def write_json(path: Path, value: dict) -> None:
    """Atomically store private metadata; callers must validate its contents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".security-")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sha256(path: Path) -> str:
    """Hash a local file in bounded chunks."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def gh_json(endpoint: str) -> dict:
    """Read GitHub JSON without exposing credentials or raw API error bodies."""
    result = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("GitHub API read failed; private context cannot be verified")
    return json.loads(result.stdout)


def github_repository(url: str) -> str:
    """Accept credential-free GitHub HTTPS or canonical SSH repository URLs."""
    match = re.fullmatch(
        r"(?:git@github\.com:|ssh://git@github\.com/|https://github\.com/)"
        r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?", url,
    )
    if not match:
        raise RuntimeError("Expected a credential-free canonical github.com remote")
    return match.group(1)


def validate_context(repo: Path, context: dict) -> dict:
    """Verify bot, draft advisory, private fork identity and both remote URLs."""
    advisory = str(context.get("advisory", ""))
    if context.get("mode") != MODE or not re.fullmatch(GHSA_RE, advisory):
        raise RuntimeError("Invalid private security context")
    remote = str(context.get("remote", ""))
    base = str(context.get("base_branch", ""))
    if remote not in git(repo, "remote").splitlines() or remote.startswith("-"):
        raise RuntimeError("Explicit existing private remote required")
    if not base or base.startswith("-"):
        raise RuntimeError("Explicit base branch required")
    git(repo, "check-ref-format", "refs/heads/" + base)
    if gh_json("user").get("login") != "borg-codex-bot":
        raise RuntimeError("GitHub identity must be borg-codex-bot")
    data = gh_json(f"repos/{PUBLIC_REPO}/security-advisories/{advisory}")
    fork = data.get("private_fork") or {}
    expected = f"{PUBLIC_REPO}-{advisory.lower()}"
    if (data.get("ghsa_id") != advisory or data.get("state") != "draft"
            or fork.get("private") is not True or fork.get("full_name") != expected):
        raise RuntimeError("Advisory must identify the expected private draft fork")
    for option in ([], ["--push"]):
        urls = git(repo, "remote", "get-url", *option, "--all", remote).splitlines()
        if len(urls) != 1 or github_repository(urls[0]) != expected:
            raise RuntimeError("Fetch and push remote must target only the advisory's private fork")
    return {"mode": MODE, "advisory": advisory, "remote": remote,
            "base_branch": base, "repository": expected}


def load_context(repo: Path) -> dict:
    """Load the explicit private context, failing closed when missing."""
    path = local_path(repo, "security-context.json")
    if not path.is_file():
        raise RuntimeError("Run security_workflow.py init with an advisory and private remote first")
    return json.loads(path.read_text())


def init_context(repo: Path, advisory: str, remote: str, base: str) -> dict:
    """Verify and persist the advisory context; never silently replace another one."""
    context = validate_context(repo, {"mode": MODE, "advisory": advisory,
                                     "remote": remote, "base_branch": base})
    path = local_path(repo, "security-context.json")
    if path.exists() and json.loads(path.read_text()) != context:
        raise RuntimeError("Another security context is active; finish it before switching")
    write_json(path, context)
    return context


def check_source(repo: Path, context: dict) -> dict:
    """Fetch and verify clean implementation source at an exact private branch tip."""
    verified = validate_context(repo, context)
    if verified != context:
        raise RuntimeError("Private context changed")
    rw.require_clean(repo)
    branch = git(repo, "branch", "--show-current")
    if not branch or branch in {context["base_branch"], "main", "master", "test-channel"}:
        raise RuntimeError("Private preflight requires an implementation branch")
    remote, base = context["remote"], context["base_branch"]
    git(repo, "fetch", remote, f"refs/heads/{base}:refs/remotes/{remote}/{base}")
    head = git(repo, "rev-parse", "HEAD")
    remote_lines = git(repo, "ls-remote", "--heads", remote, f"refs/heads/{branch}").splitlines()
    if len(remote_lines) != 1 or remote_lines[0].split()[0] != head:
        raise RuntimeError("Commit must be pushed exactly to the private remote before preflight/build")
    base_ref = f"refs/remotes/{remote}/{base}"
    if not git(repo, "diff", "--name-only", f"{base_ref}...HEAD"):
        raise RuntimeError("Implementation has no delta against the private base")
    rw.verify_implementation_delta(repo, base_ref)
    return {"context": context, "head_sha": head, "branch": branch,
            "base_sha": git(repo, "rev-parse", base_ref), "source_digest": rw.source_digest(repo, head)}


def preflight(repo: Path) -> dict:
    """Run syntax/full tests once, then attest unchanged private source and report."""
    context = load_context(repo)
    before = check_source(repo, context)
    root = repo / ".release-tmp" / "security" / context["advisory"]
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    run = Path(tempfile.mkdtemp(prefix="preflight-", dir=root))
    for pattern in ("borg_backup_ui.py", "api/*.py", "runtime/lib/*.py", "runtime/scripts/*.py", "plugin/*.py"):
        for path in repo.glob(pattern):
            compile(path.read_bytes(), str(path), "exec")
    env = dict(os.environ, TMPDIR=str(run))
    report = run / "pytest.log"
    with report.open("w") as handle:
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-r", "a",
                                 "--basetemp", str(run / "pytest")], cwd=repo, env=env,
                                stdout=handle, stderr=subprocess.STDOUT)
    print(report.read_text(), flush=True)
    if result.returncode:
        raise RuntimeError(f"Private tests failed; see {report}")
    if check_source(repo, context) != before:
        raise RuntimeError("Source/context changed during preflight")
    payload = {**before, "schema_version": 1, "result": "passed", "syntax": "passed",
               "created_at": datetime.now(timezone.utc).isoformat(),
               "report_path": str(report.relative_to(repo)), "report_sha256": sha256(report)}
    write_json(local_path(repo, "security-preflight.json"), payload)
    return payload


def verify_attestation(repo: Path) -> dict:
    """Require current private source plus the unmodified successful test record."""
    actual = check_source(repo, load_context(repo))
    path = local_path(repo, "security-preflight.json")
    if not path.is_file():
        raise RuntimeError("Private preflight missing; run mr-preflight.sh --security")
    saved = json.loads(path.read_text())
    if saved.get("result") != "passed" or saved.get("syntax") != "passed" or any(
        saved.get(key) != value for key, value in actual.items()
    ):
        raise RuntimeError("Private preflight is stale")
    report = (repo / saved["report_path"]).resolve()
    if not report.is_relative_to(repo / ".release-tmp") or sha256(report) != saved["report_sha256"]:
        raise RuntimeError("Private test report is missing or changed")
    return saved


def guard_public(repo: Path) -> None:
    """Block ordinary public deploys for a marked checkout or advisory branch."""
    branch = git(repo, "branch", "--show-current")
    remote = git(repo, "config", "--get", f"branch.{branch}.remote") if branch and subprocess.run(
        ["git", "-C", str(repo), "config", "--get", f"branch.{branch}.remote"], capture_output=True
    ).returncode == 0 else ""
    url = git(repo, "remote", "get-url", remote) if remote and remote != "." else ""
    if (local_path(repo, "security-context.json").exists()
            or "ghsa-" in branch.lower() or "-ghsa-" in url.lower()):
        raise RuntimeError("Private security work: public deployment blocked; use the private workflow")


def private_manifest(template: str, md5: str, digest: str) -> str:
    """Derive a no-download manifest retaining normal plugin install/boot hooks."""
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Invalid package SHA-256")
    text = rw.rewrite_package_installer(template, md5)
    text = re.sub(r'<!ENTITY (pluginURL|pkgurl)\s+"[^"]*">', r'<!ENTITY \1 "">', text)
    text = re.sub(r'\s+pluginURL="[^"]*"', '', text, count=1)
    text = re.sub(r'download_package\(\) \{.*?^\}', '''download_package() {
  echo "ERROR: Private test package must be copied locally; downloads are disabled."
  return 1
}''', text, count=1, flags=re.S | re.M)
    text = re.sub(r'ensure_package_file\(\) \{.*?^\}', '''ensure_package_file() {
  if [ ! -f "${PACKAGE_FILE}" ]; then
    download_package
    return 1
  fi
  if [ "$(file_sha256 "${PACKAGE_FILE}")" != "''' + digest + '''" ]; then
    echo "ERROR: Private test package SHA-256 mismatch."
    return 1
  fi
}''', text, count=1, flags=re.S | re.M)
    # Validate the package even on reinstallation paths which would otherwise
    # trust an installed marker without reading the package again.
    text = text.replace('mkdir -p "${PLUGIN_DIR}"\n\nif package_registered;',
                        'mkdir -p "${PLUGIN_DIR}"\nensure_package_file\n\nif package_registered;', 1)
    ET.fromstring(text)
    return text


def validate_version(version: str) -> None:
    """Reject invalid versions before constructing any output path."""
    if not re.fullmatch(VERSION_RE, version):
        raise ValueError("Expected YYYY.MM.DD.HHMM version")


def build(repo: Path, version: str) -> Path:
    """Build and verify a durable local candidate; never push or upload it."""
    validate_version(version)
    attestation = verify_attestation(repo)
    root = repo / ".release-tmp" / "security" / attestation["context"]["advisory"]
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = root / version
    if destination.exists():
        raise RuntimeError("Candidate version already exists; never overwrite a tested candidate")
    with tempfile.TemporaryDirectory(prefix="build-", dir=root) as temporary:
        work = Path(temporary)
        subprocess.run(["bash", str(repo / "plugin/build-candidate.sh"), version,
                        attestation["head_sha"], attestation["base_sha"], attestation["source_digest"],
                        str(work)], cwd=repo, check=True)
        candidate = work / "candidate"
        candidate.mkdir(mode=0o700)
        name = f"{rw.NAME}-{version}.txz"
        package = candidate / name
        shutil.copy2(work / "releases" / name, package)
        template = rw.rewrite_package_installer(
            (work / "source" / f"{rw.NAME}.plg").read_text(), rw.file_md5(package))
        (candidate / "release-template.plg").write_text(template)
        (candidate / f"{rw.NAME}.plg").write_text(private_manifest(template, rw.file_md5(package), sha256(package)))
        shutil.copy2(work / "source/build-provenance.json", candidate / "build-provenance.json")
        shutil.copy2(repo / attestation["report_path"], candidate / "tests.log")
        notes, _, _ = rw.rendered_release_notes(work / "source")
        (candidate / "release-notes.md").write_text(notes + "\n")
        (candidate / "INSTALL.md").write_text(
            "# Confidential local Unraid test\n\n"
            "Verify SHA256SUMS after private transfer. Keep these files private.\n\n"
            f"Copy {name} to /boot/config/plugins/{rw.NAME}/{name}.\n"
            f"Copy {rw.NAME}.plg to /boot/config/plugins/{rw.NAME}.plg, replacing the installed plugin manifest.\n"
            f"Then run: plugin install /boot/config/plugins/{rw.NAME}.plg\n\n"
            "The package must remain there for subsequent boots. The private manifest has no update URL.\n"
            "Do not install release-template.plg during confidential testing.\n"
            "After the coordinated stable release, install the official stable manifest explicitly; "
            "the tested package/version can be retained. No automatic downgrade or GitHub token is used.\n"
        )
        hashes = {p.name: sha256(p) for p in sorted(candidate.iterdir())}
        write_json(candidate / "candidate.json", {"schema_version": 1, "mode": MODE,
                   "version": version, "attestation": attestation, "files": hashes})
        hashes["candidate.json"] = sha256(candidate / "candidate.json")
        (candidate / "SHA256SUMS").write_text("".join(f"{value}  {name}\n" for name, value in sorted(hashes.items())))
        verify_candidate(candidate)
        if verify_attestation(repo) != attestation:
            raise RuntimeError("Attested source changed while building")
        candidate.rename(destination)
    return destination


def verify_candidate(directory: Path, version: str | None = None) -> dict:
    """Validate local bundle hashes, source provenance, notes and both manifests.

    This detects modification relative to locally trusted metadata, not an
    adversarially replaced entire bundle; transfer it over an authenticated path.
    """
    data = json.loads((directory / "candidate.json").read_text())
    validate_version(data["version"])
    if data.get("schema_version") != 1 or data.get("mode") != MODE or (version is not None and version != data["version"]):
        raise RuntimeError("Wrong private candidate mode/version")
    attest = data["attestation"]
    if attest.get("result") != "passed" or attest.get("syntax") != "passed" or attest.get("context", {}).get("mode") != MODE:
        raise RuntimeError("Candidate has no successful private preflight")
    if not re.fullmatch(GHSA_RE, attest["context"].get("advisory", "")):
        raise RuntimeError("Invalid candidate advisory")
    if any(not re.fullmatch(r"[a-f0-9]{40}", str(attest.get(key, ""))) for key in ("head_sha", "base_sha")):
        raise RuntimeError("Invalid candidate source revision")
    if not re.fullmatch(r"[a-f0-9]{64}", str(attest.get("source_digest", ""))):
        raise RuntimeError("Invalid candidate source digest")
    name = f"{rw.NAME}-{data['version']}.txz"
    required = {name, f"{rw.NAME}.plg", "release-template.plg", "build-provenance.json",
                "tests.log", "release-notes.md", "INSTALL.md"}
    if set(data["files"]) != required:
        raise RuntimeError("Private bundle has an unexpected file list")
    for filename, digest in data["files"].items():
        if (directory / filename).is_symlink() or sha256(directory / filename) != digest:
            raise RuntimeError(f"Candidate file changed: {filename}")
    if sha256(directory / "tests.log") != attest["report_sha256"]:
        raise RuntimeError("Test report does not match preflight")
    package = directory / name
    provenance = rw.package_provenance(package)
    for key, expected in (("version", data["version"]), ("source_commit", attest["head_sha"]),
                          ("source_base_sha", attest["base_sha"]), ("source_digest", attest["source_digest"])):
        if provenance.get(key) != expected:
            raise RuntimeError(f"Candidate provenance mismatch: {key}")
    if json.loads((directory / "build-provenance.json").read_text()) != provenance:
        raise RuntimeError("External and packaged provenance differ")
    notes = (directory / "release-notes.md").read_text().strip()
    if hashlib.sha256(notes.encode()).hexdigest() != provenance["release_notes_sha256"]:
        raise RuntimeError("Candidate release notes changed")
    template_path = directory / "release-template.plg"
    template = template_path.read_text()
    ET.fromstring(template)
    if rw.manifest_version(template_path) != data["version"] or rw.manifest_md5(template_path) != rw.file_md5(package):
        raise RuntimeError("Candidate manifest/package mismatch")
    if (directory / f"{rw.NAME}.plg").read_text() != private_manifest(template, rw.file_md5(package), sha256(package)):
        raise RuntimeError("Private manifest is not the verified local-only variant")
    match = re.search(rf"###{re.escape(data['version'])}###\n(.*?)(?=\n###[^#\n]+###\n|\n\]\]>)", template, re.S)
    if not match or match.group(1).strip() != notes:
        raise RuntimeError("Manifest and candidate release notes differ")
    checksums = {**data["files"], "candidate.json": sha256(directory / "candidate.json")}
    expected_sums = "".join(f"{value}  {name}\n" for name, value in sorted(checksums.items()))
    if (directory / "SHA256SUMS").read_text() != expected_sums:
        raise RuntimeError("Checksum list changed")
    return data


def prepare_release(repo: Path, candidate: Path, version: str) -> Path:
    """Export a local release preview with unchanged package bytes; never publish."""
    data = verify_candidate(candidate, version)
    attest = data["attestation"]
    revision = attest["head_sha"]
    if rw.source_digest(repo, revision) != attest["source_digest"]:
        raise RuntimeError("Candidate source is not available or differs locally")
    root = repo / ".release-tmp" / "security" / attest["context"]["advisory"]
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    output = Path(tempfile.mkdtemp(prefix=f"release-{version}-", dir=root))
    with tempfile.TemporaryFile(dir=output) as archive:
        subprocess.run(["git", "-C", str(repo), "archive", revision], stdout=archive, check=True)
        archive.seek(0)
        subprocess.run(["tar", "-x", "-C", str(output)], stdin=archive, check=True)
    package = f"{rw.NAME}-{version}.txz"
    (output / "releases").mkdir(exist_ok=True)
    shutil.copy2(candidate / package, output / "releases" / package)
    rw.promote_artifacts(output, candidate / "release-template.plg", version,
                         rw.file_md5(candidate / package), rw.package_provenance(candidate / package))
    for old in sorted((output / "releases").glob(f"{rw.NAME}-*.txz"))[:-5]:
        old.unlink()
    if sha256(output / "releases" / package) != data["files"][package]:
        raise RuntimeError("Release preview changed the tested package")
    rw.verify_release_artifacts(output, revision, source_repo=repo)
    return output


def authorize_publication(repo: Path, candidate: Path, advisory: str) -> None:
    """Validate explicit publication context; this is not a user-approval prompt.

    Maintainers invoke the publishing command only after coordinated approval.
    The promotion script additionally requires tested source on public main.
    """
    data = verify_candidate(candidate)
    context = data["attestation"]["context"]
    if context["advisory"] != advisory or load_context(repo) != context:
        raise RuntimeError("Explicit publication advisory must match the local context and candidate")
    validate_context(repo, context)
    for option in ([], ["--push"]):
        urls = git(repo, "remote", "get-url", *option, "--all", "origin").splitlines()
        if len(urls) != 1 or github_repository(urls[0]) != PUBLIC_REPO:
            raise RuntimeError("Public promotion must target the expected parent repository")


def finish_context(repo: Path, advisory: str) -> None:
    """Archive local private metadata only after the matching advisory is published."""
    context = load_context(repo)
    if context.get("advisory") != advisory or not re.fullmatch(GHSA_RE, advisory):
        raise RuntimeError("Advisory does not match the active private context")
    data = gh_json(f"repos/{PUBLIC_REPO}/security-advisories/{advisory}")
    if data.get("ghsa_id") != advisory or data.get("state") != "published":
        raise RuntimeError("Keep the private guard until the advisory is published")
    archive = local_path(repo, f"security-completed-{advisory}.json")
    write_json(archive, context)
    local_path(repo, "security-context.json").unlink()


def main() -> int:
    """Dispatch private operations; errors fail closed without publishing."""
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    sub = parser.add_subparsers(dest="command", required=True)
    item = sub.add_parser("init")
    item.add_argument("--advisory", required=True)
    item.add_argument("--remote", required=True)
    item.add_argument("--base", default="main")
    for command in ("preflight", "status", "guard-public"):
        sub.add_parser(command)
    item = sub.add_parser("build")
    item.add_argument("version")
    item = sub.add_parser("authorize-publication")
    item.add_argument("--candidate", required=True)
    item.add_argument("--advisory", required=True)
    item = sub.add_parser("finish")
    item.add_argument("--advisory", required=True)
    for command in ("verify", "prepare-release"):
        item = sub.add_parser(command)
        item.add_argument("--candidate", required=True)
        item.add_argument("--version")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    try:
        if args.command == "init":
            value = init_context(repo, args.advisory, args.remote, args.base)
        elif args.command == "preflight":
            value = preflight(repo)
        elif args.command == "build":
            value = str(build(repo, args.version))
        elif args.command == "verify":
            value = verify_candidate(Path(args.candidate).resolve(), args.version)
        elif args.command == "prepare-release":
            candidate = Path(args.candidate).resolve()
            data = verify_candidate(candidate, args.version)
            value = str(prepare_release(repo, candidate, data["version"]))
        elif args.command == "guard-public":
            guard_public(repo)
            return 0
        elif args.command == "authorize-publication":
            authorize_publication(repo, Path(args.candidate).resolve(), args.advisory)
            value = "Explicit security publication context verified"
        elif args.command == "finish":
            finish_context(repo, args.advisory)
            value = "Published advisory context archived locally"
        else:
            value = load_context(repo)
        print(json.dumps(value, indent=2))
        return 0
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError, ET.ParseError, tarfile.TarError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
