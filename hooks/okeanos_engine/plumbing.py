"""Processes, git, per-session state, checks.json and the metrics log."""

import json
import os
import re
import subprocess
import time


def run(cmd, cwd, timeout=10, shell=False):
    try:
        p = subprocess.run(cmd, cwd=cwd, shell=shell, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def git(root, *args, timeout=10):
    code, out = run(["git", *args], root, timeout)
    return out.strip() if code == 0 else None


def repo_root(cwd):
    code, out = run(["git", "rev-parse", "--show-toplevel"], cwd)
    return out.strip() if code == 0 else None


def okeanos_dir(root, *sub):
    """<git-common-dir>/okeanos[/sub...], created on demand; None outside a repo."""
    common = git(root, "rev-parse", "--git-common-dir") if root else None
    if not common:
        return None
    if not os.path.isabs(common):
        common = os.path.join(root, common)
    d = os.path.join(common, "okeanos", *sub)
    os.makedirs(d, exist_ok=True)
    return d


def metrics_path(root):
    d = okeanos_dir(root)
    return os.path.join(d, "metrics.jsonl") if d else None


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
        """Append one event to <git-common-dir>/okeanos/metrics.jsonl for the retro skill."""
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
