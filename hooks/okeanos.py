#!/usr/bin/env python3
"""Okeanos deterministic hooks.

Subcommands (one per hook event, wired in hooks/hooks.json):
  session-start  record the session's starting HEAD
  pre-bash       publish gate (G2), dangerous git/rm guard, secret scan, package check
  pre-edit       ask before rewriting committed test files (additions are free)
  post-edit      run the repo's per-file format/lint commands
  stop           definition of done: run the repo's checks, flag test tampering and oversized diffs

Per-repo commands live in docs/agents/checks.json (written by the onboard skill).
State lives under <git-common-dir>/okeanos/, never in the working tree.
Every failure inside a hook degrades to "allow": a broken hook must not block work.
"""

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_BLOCKS = 3
DEFAULT_MAX_LINES = 400

TEST_PATTERNS = [
    r"(^|/)(test|tests|__tests__|spec|specs)/",
    r"\.(test|spec)\.[cm]?[jt]sx?$",
    r"(^|/)test_[^/]+\.py$",
    r"_test\.(py|go)$",
    r"(Test|Tests|Spec)\.(java|kt|cs|swift)$",
    r"_spec\.rb$",
]

DOC_PATTERNS = [r"\.(md|mdx|txt|rst)$", r"(^|/)docs/", r"(^|/)\.scratch/", r"(^|/)CHANGELOG"]
LOCKFILES = r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lockb?|poetry\.lock|uv\.lock|Cargo\.lock|go\.sum)$"

SKIP_MARKERS = re.compile(
    r"\.(skip|only)\(|\b(xit|xdescribe|xtest)\(|@pytest\.mark\.skip|@unittest\.skip|\bt\.Skip\(|#\[ignore\]|@Disabled|@Ignore"
)
ASSERTION = re.compile(r"\b(expect|assert\w*|should)\b|\.to(Be|Equal|Throw|Match|Have)|\bt\.(Error|Fatal)")

SECRET_PATTERNS = [
    ("AWS access key", r"AKIA[0-9A-Z]{16}"),
    ("GitHub token", r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})"),
    ("Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("Private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("Stripe live key", r"\b[sr]k_live_[A-Za-z0-9]{20,}"),
    ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}"),
    ("Anthropic API key", r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    ("OpenAI API key", r"\bsk-(proj-)?[A-Za-z0-9_-]{40,}"),
]

POPULAR = {
    "npm": "react react-dom vue svelte next express koa fastify lodash underscore axios moment dayjs date-fns "
    "typescript webpack vite rollup esbuild babel jest vitest mocha chai sinon eslint prettier "
    "chalk commander yargs dotenv uuid zod yup joi ajv debug cors body-parser mongoose sequelize "
    "prisma pg mysql2 redis ioredis jsonwebtoken bcrypt bcryptjs passport socket.io ws nodemon "
    "rxjs immer redux zustand classnames clsx tailwindcss postcss autoprefixer sass graphql "
    "cheerio puppeteer playwright sharp multer nanoid ramda bluebird got node-fetch cross-env "
    "rimraf glob minimist semver tslib inquirer ora execa fs-extra",
    "pypi": "requests numpy pandas scipy matplotlib flask django fastapi uvicorn pydantic sqlalchemy "
    "pytest boto3 botocore urllib3 six setuptools wheel pip certifi idna charset-normalizer "
    "python-dateutil pyyaml jinja2 click rich typer httpx aiohttp celery redis psycopg2 "
    "psycopg2-binary pillow scikit-learn tensorflow torch transformers openai anthropic "
    "beautifulsoup4 lxml selenium cryptography pyjwt tqdm black ruff mypy flake8 isort poetry",
    "crates": "serde serde_json tokio anyhow thiserror clap rand regex reqwest log env_logger tracing "
    "chrono itertools lazy_static once_cell futures hyper axum actix-web syn quote proc-macro2",
}


SUPPRESSION = re.compile(
    r"@ts-(ignore|nocheck|expect-error)|eslint-disable|#\s*type:\s*ignore|#\s*noqa|pylint:\s*disable|"
    r"\bas any\b|:\s*any\b|<any>|@SuppressWarnings|#\[allow\(|//\s*nolint|#\s*nosec"
)

CTX = {"root": None, "session": None, "event": None}

# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------

def metrics_path(root):
    common = git(root, "rev-parse", "--git-common-dir") if root else None
    if not common:
        return None
    if not os.path.isabs(common):
        common = os.path.join(root, common)
    d = os.path.join(common, "okeanos")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "metrics.jsonl")


def log_event(kind, detail=""):
    """Append one event to <git-common-dir>/okeanos/metrics.jsonl for the retro skill."""
    try:
        path = metrics_path(CTX["root"])
        if not path:
            return
        branch = git(CTX["root"], "rev-parse", "--abbrev-ref", "HEAD") or ""
        with open(path, "a") as f:
            f.write(json.dumps({"ts": int(time.time()), "session": CTX["session"], "branch": branch,
                                "kind": kind, "detail": str(detail)[:300]}, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(0)


def pre_decision(decision, reason):
    log_event(f"{CTX['event']}:{decision}", reason.splitlines()[0] if reason else "")
    emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }})


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


def state_path(root, session_id):
    common = git(root, "rev-parse", "--git-common-dir")
    if not common:
        return None
    if not os.path.isabs(common):
        common = os.path.join(root, common)
    d = os.path.join(common, "okeanos", "sessions")
    os.makedirs(d, exist_ok=True)
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


def is_test(rel, checks):
    pats = TEST_PATTERNS + list(checks.get("testPatterns", []))
    return any(re.search(p, rel) for p in pats)


def is_doc(rel):
    return any(re.search(p, rel) for p in DOC_PATTERNS)


def tail(text, n=40):
    lines = text.strip().splitlines()
    return "\n".join(lines[-n:])


# ---------------------------------------------------------------------------
# session-start
# ---------------------------------------------------------------------------

def session_start(data, root):
    path = state_path(root, data.get("session_id"))
    if not path:
        return
    state = load_state(path)
    if "start_head" not in state:
        state["start_head"] = git(root, "rev-parse", "HEAD") or ""
        state["started_at"] = time.time()
        save_state(path, state)


# ---------------------------------------------------------------------------
# pre-bash
# ---------------------------------------------------------------------------

def split_segments(command):
    return [s.strip() for s in re.split(r"&&|\|\||;|\||\n", command) if s.strip()]


def tokens(segment):
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def strip_env_prefix(toks):
    i = 0
    while i < len(toks) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[i]):
        i += 1
    if i < len(toks) and toks[i] in ("sudo", "command", "exec", "time"):
        i += 1
    return toks[i:]


def check_git(toks, root):
    """Return (decision, reason) for a git invocation, or None."""
    if not toks or toks[0] != "git":
        return None
    args = toks[1:]
    while args and args[0] in ("-C", "-c"):
        args = args[2:]
    if not args:
        return None
    sub, rest = args[0], args[1:]
    if "--no-verify" in rest or (sub == "commit" and "-n" in rest):
        return ("deny", "Okeanos: --no-verify pula os hooks de verificação do repositório. Corrija o que o hook acusa em vez de pulá-lo.")
    if sub == "push":
        if any(a in ("--force", "-f") or (a.startswith("-") and not a.startswith("--") and "f" in a) for a in rest):
            return ("deny", "Okeanos: force push reescreve histórico publicado. Se for mesmo necessário, o usuário roda o comando.")
        return ("ask", "Okeanos · G2: publicar (git push) exige a sua aprovação. Confira o resumo do G2 antes de aprovar.")
    if sub == "merge":
        branch = git(root, "rev-parse", "--abbrev-ref", "HEAD") if root else None
        if branch in ("main", "master", "develop", "trunk"):
            return ("ask", f"Okeanos · G2: merge na branch padrão ({branch}) exige a sua aprovação.")
    return None


def check_cli_publish(toks):
    if len(toks) >= 3 and toks[0] in ("gh", "glab") and toks[1] in ("pr", "mr") and toks[2] in ("create", "merge"):
        return ("ask", f"Okeanos · G2: `{' '.join(toks[:3])}` publica o trabalho e exige a sua aprovação.")
    return None


def check_rm(toks, root):
    if not toks or toks[0] != "rm":
        return None
    flags = "".join(t[1:] for t in toks[1:] if t.startswith("-") and not t.startswith("--"))
    long_flags = [t for t in toks[1:] if t.startswith("--")]
    recursive = "r" in flags or "R" in flags or "--recursive" in long_flags
    if not recursive:
        return None
    for target in (t for t in toks[1:] if not t.startswith("-")):
        expanded = os.path.expanduser(os.path.expandvars(target))
        if expanded in ("/", "~", os.path.expanduser("~"), "*", ".", ".."):
            return ("deny", f"Okeanos: `rm -r {target}` apaga demais. Remova caminhos específicos dentro do repositório.")
        absolute = os.path.normpath(expanded if os.path.isabs(expanded) else os.path.join(root or os.getcwd(), expanded))
        if root and not (absolute == root or absolute.startswith(root + os.sep)) and not absolute.startswith("/tmp/"):
            return ("deny", f"Okeanos: `rm -r` fora do repositório ({target}). Se for intencional, o usuário roda o comando.")
    return None


def scan_secrets(root):
    """Scan what a commit could include: tracked changes vs HEAD plus untracked files."""
    findings = []
    diff = git(root, "diff", "HEAD", "-U0", "--no-color", timeout=20) or ""
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif line.startswith("+") and not line.startswith("+++") and current:
            for name, pat in SECRET_PATTERNS:
                if re.search(pat, line):
                    findings.append(f"{current}: {name}")
    untracked = (git(root, "ls-files", "--others", "--exclude-standard") or "").splitlines()
    for rel in untracked[:500]:
        if re.search(r"(^|/)\.env(\.[^/]*)?$", rel) and not re.search(r"\.(example|sample|template)$", rel):
            findings.append(f"{rel}: arquivo .env não ignorado pelo git")
            continue
        try:
            full = os.path.join(root, rel)
            if os.path.getsize(full) > 1_000_000:
                continue
            with open(full, errors="ignore") as f:
                text = f.read()
        except Exception:  # noqa: BLE001
            continue
        for name, pat in SECRET_PATTERNS:
            if re.search(pat, text):
                findings.append(f"{rel}: {name}")
    return sorted(set(findings))


def package_requests(toks):
    """Return [(ecosystem, name)] for install commands that add named packages."""
    if not toks:
        return []
    tool, args = toks[0], toks[1:]
    eco, names = None, []
    if tool in ("npm", "pnpm", "yarn", "bun") and args and args[0] in ("i", "install", "add"):
        eco, names = "npm", args[1:]
    elif tool in ("pip", "pip3") and args and args[0] == "install":
        eco, names = "pypi", args[1:]
    elif tool == "uv" and args[:1] == ["add"]:
        eco, names = "pypi", args[1:]
    elif tool == "uv" and args[:2] == ["pip", "install"]:
        eco, names = "pypi", args[2:]
    elif tool == "poetry" and args[:1] == ["add"]:
        eco, names = "pypi", args[1:]
    elif tool == "cargo" and args[:1] == ["add"]:
        eco, names = "crates", args[1:]
    if not eco:
        return []
    out, skip_next = [], False
    for a in names:
        if skip_next:
            skip_next = False
            continue
        if a in ("-r", "--requirement", "-e", "--editable", "-c", "--constraint", "--index-url", "-i", "--registry", "--features"):
            skip_next = True
            continue
        if a.startswith("-") or a.startswith(".") or a.startswith("/") or "://" in a or a.startswith("git+"):
            continue
        if eco == "npm":
            name = re.sub(r"(?<=.)@[^@/]*$", "", a)
        else:
            name = re.split(r"[=<>!~\[;@ ]", a, maxsplit=1)[0]
        if name:
            out.append((eco, name))
    return out


def fetch_json(url, timeout=4):
    req = urllib.request.Request(url, headers={"User-Agent": "okeanos-hook (claude code plugin)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def edit_distance(a, b):
    """Damerau-Levenshtein (optimal string alignment): a swap of two letters counts as one edit."""
    if abs(len(a) - len(b)) > 1:
        return 2
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def check_package(eco, name):
    """Return (decision, reason) or None when the package looks fine or can't be checked."""
    concerns = []
    try:
        if eco == "npm":
            meta = fetch_json("https://registry.npmjs.org/" + urllib.parse.quote(name, safe="@"))
            created = (meta.get("time") or {}).get("created", "")
            try:
                dl = fetch_json("https://api.npmjs.org/downloads/point/last-week/" + urllib.parse.quote(name, safe="@"))
                if dl.get("downloads", 0) < 1000:
                    concerns.append(f"{dl.get('downloads', 0)} downloads na última semana")
            except Exception:  # noqa: BLE001
                pass
        elif eco == "pypi":
            meta = fetch_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
            uploads = [f.get("upload_time_iso_8601", "") for files in meta.get("releases", {}).values() for f in files]
            created = min((u for u in uploads if u), default="")
        else:
            meta = fetch_json(f"https://crates.io/api/v1/crates/{urllib.parse.quote(name)}")
            created = (meta.get("crate") or {}).get("created_at", "")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ("deny", f"Okeanos: o pacote `{name}` não existe em {eco}. Pode ser um nome alucinado; confira o nome certo antes de instalar.")
        return None
    except Exception:  # noqa: BLE001
        return None  # offline or registry down: don't block work
    if created:
        try:
            from datetime import datetime, timezone
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(created.replace("Z", "+00:00"))).days
            if age < 30:
                concerns.append(f"publicado há {age} dias")
        except Exception:  # noqa: BLE001
            pass
    base = name.split("/")[-1].lower()
    for pop in POPULAR.get(eco, "").split():
        if base != pop and edit_distance(base, pop) == 1:
            concerns.append(f"nome a uma letra de `{pop}`")
            break
    if concerns:
        return ("ask", f"Okeanos: confira o pacote `{name}` antes de instalar: {', '.join(concerns)}.")
    return None


def pre_bash(data, root):
    command = (data.get("tool_input") or {}).get("command", "")
    if not command:
        return
    asks = []
    for seg in split_segments(command):
        toks = strip_env_prefix(tokens(seg))
        for check in (lambda t: check_git(t, root), check_cli_publish, lambda t: check_rm(t, root)):
            result = check(toks)
            if result and result[0] == "deny":
                pre_decision(*result)
            elif result:
                asks.append(result[1])
        if root and toks[:2] == ["git", "commit"]:
            secrets = scan_secrets(root)
            if secrets:
                pre_decision("deny", "Okeanos: possível segredo no que seria commitado:\n- " + "\n- ".join(secrets[:10])
                             + "\nTire o segredo do código (variável de ambiente, .gitignore) antes de commitar.")
        for eco, name in package_requests(toks)[:5]:
            result = check_package(eco, name)
            if result and result[0] == "deny":
                pre_decision(*result)
            elif result:
                asks.append(result[1])
    if asks:
        pre_decision("ask", "\n".join(asks))


# ---------------------------------------------------------------------------
# pre-edit: committed tests are the contract
# ---------------------------------------------------------------------------

TEST_DEF = re.compile(
    r"\b(test|it|describe|context|scenario)(\.each)?\s*\(|\bdef test_|\bfunc Test|@Test\b|#\[test\]|\bclass Test"
)


def significant(text):
    return [l.strip() for l in text.splitlines() if l.strip()]


def protected_lines_removed(old_text, new_text):
    """Assertion or test-definition lines present before and gone after the edit."""
    remaining = set(significant(new_text))
    return [l for l in significant(old_text)
            if l not in remaining and (ASSERTION.search(l) or TEST_DEF.search(l))]


def pre_edit(data, root):
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ""
    if not path or not root:
        return
    full = os.path.normpath(path if os.path.isabs(path) else os.path.join(root, path))
    if not full.startswith(root + os.sep):
        return
    rel = os.path.relpath(full, root)
    if not is_test(rel, load_checks(root)):
        return
    if git(root, "cat-file", "-e", f"HEAD:{rel}") is None:
        return  # not committed yet: still being written
    tool = data.get("tool_name")
    pairs = []
    if tool == "Edit":
        pairs = [(ti.get("old_string", ""), ti.get("new_string", ""))]
    elif tool == "MultiEdit":
        pairs = [(e.get("old_string", ""), e.get("new_string", "")) for e in ti.get("edits", [])]
    elif tool == "Write":
        try:
            with open(full, errors="ignore") as f:
                pairs = [(f.read(), ti.get("content", ""))]
        except Exception:  # noqa: BLE001
            return
    removed = [l for old, new in pairs for l in protected_lines_removed(old, new)]
    skipped = [l for old, new in pairs for l in significant(new)
               if SKIP_MARKERS.search(l) and l not in set(significant(old))]
    if removed or skipped:
        detail = "\n".join(f"- {l[:100]}" for l in (removed + skipped)[:5])
        pre_decision("ask", f"Okeanos: `{rel}` é um teste já commitado, e esta edição altera, remove ou desliga "
                            f"asserções ou casos de teste:\n{detail}\nTestes commitados são o contrato: mudar exige a sua aprovação. "
                            "Adicionar testes e mexer em imports ou helpers não pede.")


# ---------------------------------------------------------------------------
# post-edit: per-file format and lint
# ---------------------------------------------------------------------------

def post_edit(data, root):
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ""
    if not path or not root:
        return
    full = os.path.normpath(path if os.path.isabs(path) else os.path.join(root, path))
    if not full.startswith(root + os.sep) or not os.path.exists(full):
        return
    rel = os.path.relpath(full, root)
    failures = []
    for check in load_checks(root).get("onEdit", []):
        exts = check.get("ext") or []
        if exts and not any(rel.endswith(e) for e in exts):
            continue
        cmd = check.get("cmd", "").replace("{file}", shlex.quote(rel))
        if not cmd:
            continue
        code, out = run(cmd, root, timeout=int(check.get("timeout", 30)), shell=True)
        if code != 0:
            failures.append(f"[{check.get('name', 'check')}] `{cmd}` falhou:\n{tail(out, 25)}")
    if failures:
        log_event("post-edit:fail", rel)
        emit({"decision": "block", "reason": "Okeanos: verificação por edição em " + rel + ":\n\n" + "\n\n".join(failures)})


# ---------------------------------------------------------------------------
# stop: definition of done
# ---------------------------------------------------------------------------

def changed_files(root, base):
    files = set()
    if base:
        files.update((git(root, "diff", "--name-only", base) or "").splitlines())
    files.update((git(root, "diff", "--name-only", "HEAD") or "").splitlines())
    files.update((git(root, "ls-files", "--others", "--exclude-standard") or "").splitlines())
    return sorted(f for f in files if f)


def fingerprint(root, base, files):
    h = hashlib.sha256()
    h.update((git(root, "rev-parse", "HEAD") or "").encode())
    h.update((git(root, "diff", base or "HEAD", "--no-color", timeout=20) or "").encode())
    for rel in files:
        full = os.path.join(root, rel)
        if os.path.isfile(full) and git(root, "ls-files", "--error-unmatch", rel) is None:
            try:
                with open(full, "rb") as f:
                    h.update(f.read(200_000))
            except Exception:  # noqa: BLE001
                pass
    return h.hexdigest()


def tamper_report(root, base, checks):
    if not base:
        return []
    notes = []
    for line in (git(root, "diff", "--name-status", base) or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].startswith("D") and is_test(parts[1], checks):
            notes.append(f"teste apagado: {parts[1]}")
    diff = git(root, "diff", base, "-U0", "--no-color", timeout=20) or ""
    current, removed, added = None, {}, {}
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif current and is_test(current, checks):
            if line.startswith("+") and not line.startswith("+++"):
                body = line[1:].strip()
                added.setdefault(current, []).append(body)
                if SKIP_MARKERS.search(body):
                    notes.append(f"teste desligado (skip/only) em {current}: {body[:80]}")
            elif line.startswith("-") and not line.startswith("---"):
                removed.setdefault(current, []).append(line[1:].strip())
    for rel, lines in removed.items():
        gone = [l for l in lines if ASSERTION.search(l) and l not in added.get(rel, [])]
        if gone:
            notes.append(f"{len(gone)} asserção(ões) removida(s) ou alterada(s) em {rel}")
    return notes


def suppression_report(root, base):
    if not base:
        return []
    notes, current = [], None
    for line in (git(root, "diff", base, "-U0", "--no-color", timeout=20) or "").splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif current and line.startswith("+") and not line.startswith("+++") and not is_doc(current):
            body = line[1:].strip()
            if SUPPRESSION.search(body):
                notes.append(f"supressão nova em {current}: {body[:80]}")
    return notes[:10]


def changed_lines(root, base):
    total = 0
    for line in (git(root, "diff", "--numstat", base or "HEAD") or "").splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit() and not re.search(LOCKFILES, parts[2]) and not is_doc(parts[2]):
            total += int(parts[0]) + int(parts[1])
    return total


def stop(data, root):
    path = state_path(root, data.get("session_id"))
    if not path:
        return
    state = load_state(path)
    base = state.get("start_head") or git(root, "rev-parse", "HEAD")
    files = [f for f in changed_files(root, base) if not is_doc(f)]
    if not files:
        return
    checks = load_checks(root)
    fp = fingerprint(root, base, files)
    if fp in (state.get("passed_fp"), state.get("escalated_fp")):
        return

    failures = []
    for check in checks.get("onDone", []):
        cmd = check.get("cmd", "")
        if not cmd:
            continue
        code, out = run(cmd, root, timeout=int(check.get("timeout", 600)), shell=True)
        if code != 0:
            failures.append(f"[{check.get('name', 'check')}] `{cmd}` falhou:\n{tail(out)}")

    if failures:
        state["blocks"] = state.get("blocks", 0) + 1
        log_event("stop:block", failures[0].splitlines()[0])
        if state["blocks"] > MAX_BLOCKS:
            log_event("stop:escalate", failures[0].splitlines()[0])
            state["blocks"] = 0
            state["escalated_fp"] = fp
            save_state(path, state)
            emit({"systemMessage": "Okeanos: a definição de pronto falhou "
                  f"{MAX_BLOCKS} vezes seguidas e precisa de você:\n\n" + "\n\n".join(failures)})
        save_state(path, state)
        emit({"decision": "block", "reason": "Okeanos · definição de pronto: corrija antes de encerrar "
              f"(tentativa {state['blocks']}/{MAX_BLOCKS}). Se não der para corrigir, explique o bloqueio ao usuário.\n\n"
              + "\n\n".join(failures)})

    state["blocks"] = 0
    warnings = []
    tamper = tamper_report(root, base, checks)
    suppressions = suppression_report(root, base)
    size = changed_lines(root, base)
    limit = int(checks.get("maxChangedLines", DEFAULT_MAX_LINES))
    if size > limit:
        warnings.append(f"{size} linhas alteradas nesta sessão (limite {limit}): considere dividir em tickets menores.")
        if state.get("size_logged") != size // 100:
            state["size_logged"] = size // 100
            log_event("stop:size", size)
    review = tamper + suppressions
    review_sig = hashlib.sha256("\n".join(review).encode()).hexdigest() if review else ""
    if review and state.get("tamper_sig") != review_sig:
        state["tamper_sig"] = review_sig
        save_state(path, state)
        for note in review:
            log_event("stop:tamper" if note in tamper else "stop:suppression", note)
        emit({"decision": "block", "reason": "Okeanos: pontos que o usuário precisa saber nesta sessão:\n- " + "\n- ".join(review)
              + "\nNa sua resposta, diga cada um ao usuário com o motivo. Teste afrouxado ou supressão sem motivo forte: desfaça."})
    if state.get("passed_fp") != fp:
        log_event("stop:pass", f"{size} linhas")
    state["passed_fp"] = fp
    save_state(path, state)
    if tamper:
        warnings.append("testes alterados: " + "; ".join(tamper))
    if suppressions:
        warnings.append(f"{len(suppressions)} supressão(ões) de lint/tipo nova(s)")
    if warnings:
        emit({"systemMessage": "Okeanos: " + "\n".join(warnings)})


# ---------------------------------------------------------------------------

HANDLERS = {
    "session-start": session_start,
    "pre-bash": pre_bash,
    "pre-edit": pre_edit,
    "post-edit": post_edit,
    "stop": stop,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in HANDLERS:
        sys.exit(0)
    try:
        data = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        sys.exit(0)
    if os.environ.get("OKEANOS_HOOK_DEBUG"):
        with open(os.path.expanduser("~/.okeanos-hook-debug.jsonl"), "a") as f:
            f.write(json.dumps({"cmd": sys.argv[1], "data": data}) + "\n")
    root = repo_root(data.get("cwd") or os.getcwd())
    CTX.update(root=root, session=data.get("session_id"), event=sys.argv[1])
    if not root and sys.argv[1] != "pre-bash":
        sys.exit(0)
    try:
        HANDLERS[sys.argv[1]](data, root)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        pass  # a broken hook must never block work
    sys.exit(0)


if __name__ == "__main__":
    main()
