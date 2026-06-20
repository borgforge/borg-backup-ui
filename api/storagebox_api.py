"""
api/storagebox_api.py - Storagebox/SSH-Key-Setup und Verbindungstest.
"""
from __future__ import annotations

import os
import pty
import select
import shlex
import shutil
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _storagebox_profile(conf: dict, *, storage_profile: Optional[dict] = None) -> dict:
    def _normalize_storagebox_base_path(raw: str) -> str:
        v = str(raw or "").strip()
        if not v:
            return "/./backup"
        if v.startswith("./"):
            return v
        if v.startswith("/./"):
            return v
        if v.startswith("/"):
            return v
        return f"/{v}"

    row = storage_profile if isinstance(storage_profile, dict) else {}
    ssh_key = str(row.get("ssh_key_path", "")).strip() or str(conf.get("BORG_SSH_KEY", "")).strip()
    return {
        "profile_key": str(row.get("key", "")).strip(),
        "profile_name": str(row.get("name", "")).strip(),
        "host": str(row.get("host", conf.get("STORAGEBOX_HOST", ""))).strip(),
        "port": str(row.get("port", conf.get("STORAGEBOX_PORT", "23"))).strip() or "23",
        "user": str(row.get("user", conf.get("STORAGEBOX_USER", ""))).strip(),
        "base_path": _normalize_storagebox_base_path(row.get("base_path", conf.get("STORAGEBOX_BASE_PATH", "/./backup"))),
        "ssh_key": ssh_key,
    }


def _storagebox_is_profile_complete(p: dict) -> bool:
    return bool(p.get("host") and p.get("user") and p.get("base_path"))


def _storagebox_ssh_base_cmd(p: dict, *, batch_mode: bool = True, force_tty: bool = False) -> list[str]:
    cmd = ["ssh", "-p", str(p["port"]), "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new"]
    if batch_mode:
        cmd += ["-o", "BatchMode=yes"]
    else:
        cmd += [
            "-o", "BatchMode=no",
            "-o", "PubkeyAuthentication=no",
            "-o", "KbdInteractiveAuthentication=yes",
            "-o", "PasswordAuthentication=yes",
            "-o", "PreferredAuthentications=keyboard-interactive,password",
            "-o", "NumberOfPasswordPrompts=3",
        ]
    if force_tty:
        cmd += ["-tt"]
    if p.get("ssh_key"):
        cmd += ["-i", str(p["ssh_key"])]
    cmd.append(f'{p["user"]}@{p["host"]}')
    return cmd


def _sanitize_ssh_noise(text: str) -> str:
    raw_lines = str(text or "").splitlines()
    filtered: List[str] = []
    for line in raw_lines:
        l = line.strip()
        low = l.lower()
        if (
            ("hostfile_replace_entries" in low and "operation not permitted" in low)
            or ("update_known_hosts" in low and "operation not permitted" in low)
        ):
            continue
        filtered.append(line)
    return "\n".join(filtered).strip()


def _storagebox_auth_test(p: dict) -> tuple[bool, str]:
    try:
        res = subprocess.run(
            _storagebox_ssh_base_cmd(p) + ["help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        combined = _sanitize_ssh_noise((res.stdout or "") + "\n" + (res.stderr or ""))
        lower = combined.lower()
        auth_error_markers = [
            "permission denied",
            "authentication failed",
            "publickey",
            "too many authentication failures",
            "connection refused",
            "could not resolve hostname",
            "no route to host",
            "connection timed out",
            "connection closed",
            "host key verification failed",
        ]
        if any(m in lower for m in auth_error_markers):
            msg = combined.splitlines()[-1:] or ["SSH authentication failed"]
            return False, msg[0][:240]

        pq_warning = "post-quantum key exchange algorithm" in lower
        if pq_warning:
            return True, "SSH authentication succeeded (note: server PQ-KEX warning)"
        return True, "SSH authentication succeeded"
    except Exception as exc:
        return False, str(exc)


def _storagebox_remote_borg_test(p: dict) -> tuple[bool, str]:
    target = _detect_storage_target_type(p)
    if target.get("target_type") == "storagebox":
        return True, "Borg check skipped for Storage Box (restricted shell)."
    try:
        res = subprocess.run(
            _storagebox_ssh_base_cmd(p) + ["borg --version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        combined = _sanitize_ssh_noise((res.stdout or "") + "\n" + (res.stderr or ""))
        lower = combined.lower()
        if res.returncode == 0:
            first = (combined.splitlines() or ["borg available"])[0]
            return True, first[:240]
        if "command not found" in lower or "borg: not found" in lower:
            return False, "borg is not installed or not in PATH on the target system."
        return False, (combined.splitlines()[-1:] or ["Borg check failed"])[0][:240]
    except Exception as exc:
        return False, str(exc)


def _detect_storage_target_type(p: dict) -> dict:
    """Auto-Erkennung: storagebox | synology | generic."""
    host = str(p.get("host", "")).strip().lower()
    port = str(p.get("port", "")).strip()
    base = str(p.get("base_path", "")).strip()

    if host.endswith(".your-storagebox.de") or (port == "23" and (base.startswith("./") or base.startswith("/./"))):
        return {"target_type": "storagebox", "method": "heuristic", "hint": "Host, port, and base path match the Storage Box pattern"}
    if host.endswith(".synology.me") or host.endswith(".diskstation.me") or base.startswith("/volume"):
        return {"target_type": "synology", "method": "heuristic", "hint": "Host and base path match the Synology pattern"}

    try:
        probe = subprocess.run(
            _storagebox_ssh_base_cmd(p) + ["help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        combined = ((probe.stdout or "") + "\n" + (probe.stderr or "")).lower()
        if "welcome to your storage box" in combined or "restricted shell" in combined:
            return {"target_type": "storagebox", "method": "probe", "hint": "Remote banner indicates a Storage Box restricted shell"}
        if "synology" in combined or "diskstation" in combined:
            return {"target_type": "synology", "method": "probe", "hint": "Remote banner or output indicates Synology"}
    except Exception:
        pass

    return {"target_type": "generic", "method": "heuristic", "hint": "No specific pattern detected"}


def _storage_context(ui_config: dict, profile_key: str = "") -> tuple[dict, dict]:
    from config_api import read_expanded_conf
    from storage_profiles_api import resolve_storage_profile

    conf = read_expanded_conf(ui_config)
    row = resolve_storage_profile(ui_config, profile_key)
    return conf, _storagebox_profile(conf, storage_profile=row)


def get_storagebox_setup_status(ui_config: dict, profile_key: str = "") -> dict:
    _conf, p = _storage_context(ui_config, profile_key)
    key_file = Path(p["ssh_key"]) if p.get("ssh_key") else Path("")
    pub_file = Path(str(key_file) + ".pub") if str(key_file) else Path("")
    key_exists = bool(str(key_file) and key_file.exists())
    pub_exists = bool(str(pub_file) and pub_file.exists())
    profile_complete = _storagebox_is_profile_complete(p)
    target = _detect_storage_target_type(p) if profile_complete else {"target_type": "generic", "method": "none", "hint": "Profile is incomplete"}
    auth_ok, auth_msg = (False, "Profile is incomplete")
    if profile_complete and key_exists:
        auth_ok, auth_msg = _storagebox_auth_test(p)
    return {
        "profile_complete": profile_complete,
        "key_exists": key_exists,
        "pub_exists": pub_exists,
        "auth_ok": auth_ok,
        "message": auth_msg,
        "target_type": target.get("target_type", "generic"),
        "target_detection_method": target.get("method", "none"),
        "target_detection_hint": target.get("hint", ""),
        "profile_key": p.get("profile_key", ""),
        "profile_name": p.get("profile_name", ""),
    }


def storagebox_key_status(ui_config: dict, profile_key: str = "") -> dict:
    _conf, p = _storage_context(ui_config, profile_key)
    key_file = Path(p["ssh_key"]) if p.get("ssh_key") else Path("")
    pub_file = Path(str(key_file) + ".pub") if str(key_file) else Path("")
    return {
        "key_path": str(key_file) if str(key_file) else "",
        "pub_path": str(pub_file) if str(pub_file) else "",
        "key_exists": bool(str(key_file) and key_file.exists()),
        "pub_exists": bool(str(pub_file) and pub_file.exists()),
        "profile_key": p.get("profile_key", ""),
        "profile_name": p.get("profile_name", ""),
    }


def storagebox_key_generate(ui_config: dict, profile_key: str = "") -> dict:
    _conf, p = _storage_context(ui_config, profile_key)
    key_path = Path(p["ssh_key"])
    if not str(key_path):
        raise ValueError("BORG_SSH_KEY is not set")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        return {"generated": False, "message": f"SSH key already exists: {key_path}", "message_code": "storagebox_key_exists", "message_params": {"path": str(key_path)}}
    res = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout or "ssh-keygen failed").strip())
    return {"generated": True, "message": f"SSH key created: {key_path}", "message_code": "storagebox_key_created", "message_params": {"path": str(key_path)}}


def storagebox_key_public(ui_config: dict, profile_key: str = "") -> dict:
    _conf, p = _storage_context(ui_config, profile_key)
    pub_path = Path(str(p["ssh_key"]) + ".pub")
    if not pub_path.exists():
        raise FileNotFoundError(f"Public key not found: {pub_path}")
    text = pub_path.read_text(encoding="utf-8", errors="replace").strip()
    return {"public_key": text, "pub_path": str(pub_path)}


def storagebox_key_deploy(ui_config: dict, password: str, profile_key: str = "") -> dict:
    _conf, p = _storage_context(ui_config, profile_key)
    if not _storagebox_is_profile_complete(p):
        raise ValueError("Storage Box profile is incomplete")
    pub = storagebox_key_public(ui_config, profile_key=profile_key).get("public_key", "")
    if not pub:
        raise ValueError("Public key is empty")
    if not shutil.which("sshpass"):
        raise RuntimeError("sshpass is not installed")
    cmd = ["sshpass", "-p", password] + _storagebox_ssh_base_cmd(p, batch_mode=False) + ["install-ssh-key"]
    res = subprocess.run(cmd, input=pub + "\n", capture_output=True, text=True, timeout=25)
    if res.returncode != 0:
        msg = (res.stderr or res.stdout or "Key deployment failed").strip()
        raise RuntimeError(msg[:320])
    return {"deployed": True, "message": "Public key installed on Storage Box", "message_code": "storagebox_key_deployed"}


def storagebox_connection_test(ui_config: dict, profile_key: str = "") -> dict:
    _conf, p = _storage_context(ui_config, profile_key)
    target = _detect_storage_target_type(p)
    if not _storagebox_is_profile_complete(p):
        raise ValueError("Storage Box profile is incomplete")
    auth_ok, auth_msg = _storagebox_auth_test(p)
    if not auth_ok:
        return {
            "success": False,
            "message": "SSH authentication with the configured key failed.",
            "message_code": "storagebox_ssh_failed",
            "details": auth_msg[:500],
            "target_type": target.get("target_type", "generic"),
            "target_detection_method": target.get("method", "none"),
            "target_detection_hint": target.get("hint", ""),
            "steps": {"ssh_ok": False, "borg_ok": None, "path_exists": None, "path_writable": None},
        }

    borg_ok, borg_msg = _storagebox_remote_borg_test(p)
    if not borg_ok:
        return {
            "success": False,
            "message": "Borg is not available on the target system.",
            "message_code": "storagebox_borg_missing",
            "details": borg_msg[:500],
            "target_type": target.get("target_type", "generic"),
            "target_detection_method": target.get("method", "none"),
            "target_detection_hint": target.get("hint", ""),
            "steps": {"ssh_ok": True, "borg_ok": False, "path_exists": None, "path_writable": None},
        }

    raw_base = str(p["base_path"]).strip()
    if raw_base.startswith("/./"):
        base = raw_base[3:].strip("/") or "."
    elif raw_base.startswith("./"):
        base = raw_base[2:].strip("/") or "."
    else:
        base = raw_base.rstrip("/") or "/"

    exists_cmd = subprocess.run(
        _storagebox_ssh_base_cmd(p) + [f"stat {shlex.quote(base)}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if exists_cmd.returncode != 0:
        detail = _sanitize_ssh_noise(exists_cmd.stderr or exists_cmd.stdout or "Path check failed")
        return {
            "success": False,
            "message": f"Path not found or not readable: {base}",
            "message_code": "storagebox_path_missing",
            "message_params": {"path": base},
            "details": detail[:500],
            "target_type": target.get("target_type", "generic"),
            "target_detection_method": target.get("method", "none"),
            "target_detection_hint": target.get("hint", ""),
            "steps": {"ssh_ok": True, "borg_ok": True, "path_exists": False, "path_writable": None},
        }

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    if base == ".":
        probe_dir = f".bbui-write-test-{stamp}"
    elif base == "/":
        probe_dir = f"/.bbui-write-test-{stamp}"
    else:
        probe_dir = f"{base}/.bbui-write-test-{stamp}"
    probe_file = f"{probe_dir}/probe.txt"

    mk = subprocess.run(_storagebox_ssh_base_cmd(p) + [f"mkdir {shlex.quote(probe_dir)}"], capture_output=True, text=True, timeout=12)
    if mk.returncode != 0:
        msg = _sanitize_ssh_noise(mk.stderr or mk.stdout or "Write test (mkdir) failed")
        return {
            "success": False,
            "message": f"Path is not writable: {base}",
            "message_code": "storagebox_path_not_writable",
            "message_params": {"path": base},
            "details": msg[:500],
            "target_type": target.get("target_type", "generic"),
            "target_detection_method": target.get("method", "none"),
            "target_detection_hint": target.get("hint", ""),
            "steps": {"ssh_ok": True, "borg_ok": True, "path_exists": True, "path_writable": False},
        }
    touch = subprocess.run(_storagebox_ssh_base_cmd(p) + [f"touch {shlex.quote(probe_file)}"], capture_output=True, text=True, timeout=12)
    if touch.returncode != 0:
        msg = _sanitize_ssh_noise(touch.stderr or touch.stdout or "Write test (touch) failed")
        subprocess.run(_storagebox_ssh_base_cmd(p) + [f"rmdir {shlex.quote(probe_dir)}"], capture_output=True, text=True, timeout=8)
        return {
            "success": False,
            "message": f"Path is not writable: {base}",
            "message_code": "storagebox_path_not_writable",
            "message_params": {"path": base},
            "details": msg[:500],
            "target_type": target.get("target_type", "generic"),
            "target_detection_method": target.get("method", "none"),
            "target_detection_hint": target.get("hint", ""),
            "steps": {"ssh_ok": True, "borg_ok": True, "path_exists": True, "path_writable": False},
        }
    stat = subprocess.run(_storagebox_ssh_base_cmd(p) + [f"stat {shlex.quote(probe_file)}"], capture_output=True, text=True, timeout=12)
    if stat.returncode != 0:
        msg = _sanitize_ssh_noise(stat.stderr or stat.stdout or "Write test (stat) failed")
        subprocess.run(_storagebox_ssh_base_cmd(p) + [f"rm {shlex.quote(probe_file)}"], capture_output=True, text=True, timeout=8)
        subprocess.run(_storagebox_ssh_base_cmd(p) + [f"rmdir {shlex.quote(probe_dir)}"], capture_output=True, text=True, timeout=8)
        return {
            "success": False,
            "message": "Write test failed because the probe file could not be verified.",
            "message_code": "storagebox_write_verify_failed",
            "details": msg[:500],
            "target_type": target.get("target_type", "generic"),
            "target_detection_method": target.get("method", "none"),
            "target_detection_hint": target.get("hint", ""),
            "steps": {"ssh_ok": True, "borg_ok": True, "path_exists": True, "path_writable": False},
        }
    rmf = subprocess.run(_storagebox_ssh_base_cmd(p) + [f"rm {shlex.quote(probe_file)}"], capture_output=True, text=True, timeout=12)
    if rmf.returncode != 0:
        msg = _sanitize_ssh_noise(rmf.stderr or rmf.stdout or "Write test (rm) failed")
        subprocess.run(_storagebox_ssh_base_cmd(p) + [f"rmdir {shlex.quote(probe_dir)}"], capture_output=True, text=True, timeout=8)
        return {
            "success": False,
            "message": "Write test failed because the probe file could not be removed.",
            "message_code": "storagebox_write_cleanup_failed",
            "details": msg[:500],
            "target_type": target.get("target_type", "generic"),
            "target_detection_method": target.get("method", "none"),
            "target_detection_hint": target.get("hint", ""),
            "steps": {"ssh_ok": True, "borg_ok": True, "path_exists": True, "path_writable": False},
        }
    rmdir = subprocess.run(_storagebox_ssh_base_cmd(p) + [f"rmdir {shlex.quote(probe_dir)}"], capture_output=True, text=True, timeout=12)
    if rmdir.returncode != 0:
        msg = _sanitize_ssh_noise(rmdir.stderr or rmdir.stdout or "Write test (rmdir) failed")
        return {
            "success": False,
            "message": "Write test succeeded, but cleanup failed.",
            "message_code": "storagebox_write_cleanup_failed",
            "details": msg[:500],
            "target_type": target.get("target_type", "generic"),
            "target_detection_method": target.get("method", "none"),
            "target_detection_hint": target.get("hint", ""),
            "steps": {"ssh_ok": True, "borg_ok": True, "path_exists": True, "path_writable": False},
        }
    return {
        "success": True,
        "message": "SSH, Borg, and write access checks succeeded.",
        "message_code": "storagebox_connection_success",
        "details": "SSH key authentication, remote Borg check, and write test (mkdir/touch/stat/rm/rmdir) succeeded.",
        "target_type": target.get("target_type", "generic"),
        "target_detection_method": target.get("method", "none"),
        "target_detection_hint": target.get("hint", ""),
        "steps": {"ssh_ok": True, "borg_ok": True, "path_exists": True, "path_writable": True},
    }


class _StorageKeyDeployManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def _append(self, sess: Dict[str, Any], text: str) -> None:
        if not text:
            return
        sess["output"] = (sess.get("output", "") + text)[-20000:]
        sess["updated_at"] = time.time()

    def start(self, ui_config: dict, target_override: str = "", profile_key: str = "") -> Dict[str, Any]:
        _conf, p = _storage_context(ui_config, profile_key)
        if not _storagebox_is_profile_complete(p):
            raise ValueError("Storage profile is incomplete")
        pub = storagebox_key_public(ui_config, profile_key=profile_key).get("public_key", "")
        if not pub:
            raise ValueError("Public key is empty")

        det = _detect_storage_target_type(p)
        target = str(target_override or det.get("target_type") or "generic").strip().lower()
        if target not in {"storagebox", "synology", "generic"}:
            target = "generic"

        key_q = shlex.quote(pub)
        remote_cmd = (
            "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
            f"(grep -qxF {key_q} ~/.ssh/authorized_keys 2>/dev/null || echo {key_q} >> ~/.ssh/authorized_keys) && "
            "chmod 600 ~/.ssh/authorized_keys"
        )

        cmd = _storagebox_ssh_base_cmd(p, batch_mode=False, force_tty=True) + [remote_cmd]
        sid = str(uuid.uuid4())
        pid, master_fd = pty.fork()
        if pid == 0:
            try:
                os.environ["LC_ALL"] = "C"
                os.environ["LANG"] = "C"
                os.execvp(cmd[0], cmd)
            except Exception:
                os._exit(127)

        sess = {
            "id": sid,
            "target_type": target,
            "target_detected": det.get("target_type", "generic"),
            "status": "running",
            "output": "",
            "created_at": time.time(),
            "updated_at": time.time(),
            "exit_code": None,
            "pid": pid,
            "fd": master_fd,
            "timed_out": False,
        }
        with self._lock:
            self._sessions[sid] = sess
        self._append(sess, f"[info] Starting deployment to target type: {target}\n")

        threading.Thread(target=self._reader_loop, args=(sid,), daemon=True).start()
        threading.Thread(target=self._timeout_watch, args=(sid, 180), daemon=True).start()
        return {"session_id": sid, "target_type": target, "profile_key": p.get("profile_key", ""), "profile_name": p.get("profile_name", "")}

    def _reader_loop(self, sid: str) -> None:
        while True:
            with self._lock:
                sess = self._sessions.get(sid)
            if not sess:
                return
            pid = sess.get("pid")
            fd = sess.get("fd")
            if not pid or fd is None:
                return
            r, _, _ = select.select([fd], [], [], 0.4)
            if r:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    chunk = b""
                if chunk:
                    text = chunk.decode("utf-8", errors="replace")
                    with self._lock:
                        self._append(sess, text)
            try:
                wpid, status = os.waitpid(int(pid), os.WNOHANG)
            except ChildProcessError:
                wpid, status = int(pid), 0
            if wpid == int(pid):
                rc = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 255
                with self._lock:
                    sess["exit_code"] = int(rc)
                    if sess.get("status") == "running":
                        sess["status"] = "success" if rc == 0 else "error"
                try:
                    os.close(fd)
                except OSError:
                    pass
                return

    def _timeout_watch(self, sid: str, timeout_sec: int) -> None:
        time.sleep(max(1, int(timeout_sec)))
        with self._lock:
            sess = self._sessions.get(sid)
            if not sess or sess.get("status") != "running":
                return
            pid = sess.get("pid")
            if pid:
                try:
                    os.killpg(int(pid), signal.SIGKILL)
                except Exception:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except Exception:
                        pass
                sess["status"] = "timeout"
                sess["timed_out"] = True
                self._append(sess, "\n[error] Session timeout reached (180s)\n")

    def input_text(self, session_id: str, text: str) -> Dict[str, Any]:
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                raise ValueError("Deployment session not found")
            if sess.get("status") != "running":
                return {"sent": False, "status": sess.get("status")}
            fd = sess.get("fd")
            if fd is None:
                raise RuntimeError("Session has no TTY")
            safe = str(text or "")
            os.write(fd, (safe + "\n").encode("utf-8"))
            sess["updated_at"] = time.time()
        return {"sent": True}

    def cancel(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                raise ValueError("Deployment session not found")
            pid = sess.get("pid")
            if pid:
                try:
                    os.killpg(int(pid), signal.SIGKILL)
                except Exception:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except Exception:
                        pass
            sess["status"] = "canceled"
            self._append(sess, "\n[info] Deployment cancelled.\n")
        return {"canceled": True}

    def state(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                raise ValueError("Deployment session not found")
            return {
                "session_id": session_id,
                "status": sess.get("status"),
                "output": sess.get("output", ""),
                "exit_code": sess.get("exit_code"),
                "target_type": sess.get("target_type"),
                "target_detected": sess.get("target_detected"),
                "updated_at": sess.get("updated_at"),
            }


_STORAGE_DEPLOY_MGR = _StorageKeyDeployManager()


def storagebox_deploy_start(ui_config: dict, target_override: str = "", profile_key: str = "") -> Dict[str, Any]:
    return _STORAGE_DEPLOY_MGR.start(ui_config, target_override=target_override, profile_key=profile_key)


def storagebox_deploy_input(session_id: str, text: str) -> Dict[str, Any]:
    return _STORAGE_DEPLOY_MGR.input_text(session_id, text)


def storagebox_deploy_cancel(session_id: str) -> Dict[str, Any]:
    return _STORAGE_DEPLOY_MGR.cancel(session_id)


def storagebox_deploy_state(session_id: str) -> Dict[str, Any]:
    return _STORAGE_DEPLOY_MGR.state(session_id)
