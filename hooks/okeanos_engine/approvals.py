"""Approvals granted by the human with `okeanos aprovar <alvo>`.

Stored in <git-common-dir>/okeanos/approvals.json as {target: {approved_at, expires_at}}.
A target is matched exactly: a repo-relative file path, `push`, or `pacote:<name>`.
The clock is time.time(), or OKEANOS_NOW (seconds since the epoch) in tests.
"""

import json
import os
import tempfile
import time

from .plumbing import git

TTL = 600  # ten minutes
PUSH = "push"
PACKAGE_PREFIX = "pacote:"


def now():
    try:
        return float(os.environ["OKEANOS_NOW"])
    except (KeyError, ValueError):
        return time.time()


def state_dir(root):
    """<git-common-dir>/okeanos for the repo at root, without creating it; None outside a repo."""
    common = git(root, "rev-parse", "--git-common-dir") if root else None
    if not common:
        return None
    if not os.path.isabs(common):
        common = os.path.join(root, common)
    return os.path.normpath(os.path.join(common, "okeanos"))


def path(root):
    d = state_dir(root)
    return os.path.join(d, "approvals.json") if d else None


def load(root):
    p = path(root)
    try:
        with open(p) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def active(root):
    """{target: expires_at} for approvals still valid now."""
    t = now()
    out = {}
    for target, entry in load(root).items():
        try:
            expires = float(entry["expires_at"])
        except Exception:  # noqa: BLE001
            continue
        if expires > t:
            out[target] = expires
    return out


def is_approved(root, target):
    return bool(root) and target in active(root)


def _save(root, data):
    p = path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), prefix=".approvals-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, p)


def grant(root, targets):
    """Record targets as approved for TTL seconds; drop expired ones. Returns expires_at."""
    t = now()
    data = {k: v for k, v in load(root).items() if k in active(root)}
    for target in targets:
        data[target] = {"approved_at": int(t), "expires_at": int(t + TTL)}
    _save(root, data)
    return int(t + TTL)


def revoke(root, target=None):
    """Remove one target (or all). Returns the removed targets."""
    data = load(root)
    removed = list(data) if target is None else [k for k in data if k == target]
    for k in removed:
        data.pop(k)
    _save(root, data)
    return removed


def how_to(targets):
    """The last line of every ask reason."""
    return "Para aprovar: okeanos aprovar " + " ".join(targets)
