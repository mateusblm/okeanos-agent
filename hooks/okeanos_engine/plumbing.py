"""Processes, git, per-session state, checks.json and the metrics log."""

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time


def run(cmd, cwd, timeout=10, shell=False, env=None):
    try:
        p = subprocess.run(cmd, cwd=cwd, shell=shell, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def git(root, *args, timeout=10):
    code, out = run(["git", *args], root, timeout)
    return out.strip() if code == 0 else None


def committed(root, rel):
    """Whether the repo-relative path exists at HEAD."""
    return git(root, "cat-file", "-e", f"HEAD:{rel}") is not None


def repo_root(cwd):
    code, out = run(["git", "rev-parse", "--show-toplevel"], cwd)
    return out.strip() if code == 0 else None


def git_common_dir(root):
    common = git(root, "rev-parse", "--git-common-dir") if root else None
    if not common:
        return None
    return common if os.path.isabs(common) else os.path.join(root, common)


def fallback_dir(root, *sub):
    """Writable stand-in for <git-common-dir>/okeanos when the git dir is read-only, as in
    Codex's workspace-write sandbox: <TMPDIR>/okeanos/<hash of the git dir>[/sub...]."""
    common = git_common_dir(root)
    if not common:
        return None
    key = hashlib.sha256(os.path.realpath(common).encode()).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), "okeanos", key, *sub)


def _writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        return os.access(d, os.W_OK)
    except OSError:
        return False


def okeanos_dir(root, *sub):
    """<git-common-dir>/okeanos[/sub...] for session state and metrics, created on demand.
    Falls back to fallback_dir() when the git dir can't be written; None outside a repo.
    Approvals don't use this: they are read from the git dir only (see approvals.py)."""
    common = git_common_dir(root)
    if not common:
        return None
    primary = os.path.join(common, "okeanos", *sub)
    if _writable(primary):
        return primary
    fallback = fallback_dir(root, *sub)
    return fallback if fallback and _writable(fallback) else None


def metrics_path(root):
    d = okeanos_dir(root)
    return os.path.join(d, "metrics.jsonl") if d else None


def metrics_files(root):
    """Every metrics file that exists for the repo: the git dir's and the fallback's."""
    common = git_common_dir(root)
    if not common:
        return []
    candidates = [os.path.join(common, "okeanos", "metrics.jsonl"), os.path.join(fallback_dir(root), "metrics.jsonl")]
    return [p for p in candidates if os.path.exists(p)]


def state_path(root, session_id):
    d = okeanos_dir(root, "sessions")
    if not d:
        return None
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "default")
    return os.path.join(d, safe + ".json")


def load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def save_state(path, state):
    try:
        with open(path, "w") as f:
            json.dump(state, f)
    except Exception:  # noqa: BLE001
        pass


def load_checks(root):
    try:
        with open(os.path.join(root, "docs", "agents", "checks.json")) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def tail(text, n=40):
    lines = text.strip().splitlines()
    return "\n".join(lines[-n:])


class Context:
    """What a rule needs besides the event: the repo root and a metrics logger."""

    def __init__(self, event, root):
        self.event = event
        self.root = root

    def log(self, kind, detail=""):
        """Append one event to <git-common-dir>/okeanos/metrics.jsonl for the okeanos-retro skill."""
        try:
            path = metrics_path(self.root)
            if not path:
                return
            branch = git(self.root, "rev-parse", "--abbrev-ref", "HEAD") or ""
            with open(path, "a") as f:
                f.write(json.dumps({"ts": int(time.time()), "agent": self.event.agent,
                                    "session": self.event.session_id, "branch": branch,
                                    "kind": kind, "detail": str(detail)[:300]}, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass
