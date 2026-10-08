"""The Okeanos rules. Input: a normalized Event. Output: a Decision.

Nothing here knows which agent is calling. Per-repo commands live in
docs/agents/checks.json (written by the onboard skill); state lives under
<git-common-dir>/okeanos/, never in the working tree.
"""

import hashlib
import os
import re
import shlex
import time

from . import approvals
from .model import (ALLOW, ASK, BLOCK, DENY, EDIT, MULTI_EDIT, POST_TOOL, PRE_TOOL, PROMPT,
                    SESSION_START, SHELL, STOP, WRITE, Decision)
from .packages import check_package, package_requests
from .plumbing import git, load_checks, load_state, run, save_state, state_path, tail

MAX_BLOCKS = 3
HANDOFF_MARK = "**Okeanos** · precisa de você"
DEFAULT_MAX_LINES = 400

TEST_PATTERNS = [
    r"(^|/)(test|tests|__tests__|spec|specs|Tests|androidTest|testFixtures)/",
    r"\.(test|spec)\.[A-Za-z]+$",  # foo.test.ts, foo.spec.js, foo.test.py...
    r"(^|/)test_[^/]+\.py$",
    r"_(test|spec)\.(py|go|rb|exs|lua|dart|cpp|cc|c)$",
    r"(Test|Tests|Spec|IT)\.(java|kt|kts|scala|cs|fs|swift|php|groovy)$",
]

DOC_PATTERNS = [r"\.(md|mdx|txt|rst)$", r"(^|/)docs/", r"(^|/)\.scratch/", r"(^|/)CHANGELOG"]
LOCKFILES = r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lockb?|poetry\.lock|uv\.lock|Cargo\.lock|go\.sum)$"

SKIP_MARKERS = re.compile(
    r"\.(skip|only)\(|\b(xit|xdescribe|xtest|fit|fdescribe)\(|@pytest\.mark\.(skip|xfail)|@unittest\.skip|"
    r"\bpytest\.skip\(|\bt\.Skip(Now|f)?\(|#\[ignore\]|@Disabled|@Ignore|\[Ignore\]|\[Fact\(Skip|"
    r"markTestSkipped|@tag\s+:skip|^pending\b|^skip\s*\(|@Skip"
)
ASSERTION = re.compile(
    r"\b(expect|assert\w*|should|verify|require\.\w+)\b|\.to(Be|Equal|Throw|Match|Have|Contain)|"
    r"\bt\.(Error|Fatal)|\bAssert\.\w+|\$this->assert|\bXCTAssert\w*|\bassert!|\bassert_eq!|\bshouldBe\b|\bexpectThat\b"
)

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

SUPPRESSION = re.compile(
    r"@ts-(ignore|nocheck|expect-error)|eslint-disable|biome-ignore|#\s*type:\s*ignore|#\s*noqa|pylint:\s*disable|"
    r"#\s*pyright:\s*ignore|\bas any\b|:\s*any\b|<any>|@SuppressWarnings|@Suppress\(|#\[allow\(|"
    r"//\s*nolint|#\s*nosec|rubocop:disable|@phpstan-ignore|@psalm-suppress|#pragma warning disable|"
    r"SuppressMessage|NOSONAR|swiftlint:disable|//\s*@ts-|#\s*noinspection"
)


def is_test(rel, checks):
    pats = TEST_PATTERNS + list(checks.get("testPatterns", []))
    return any(re.search(p, rel) for p in pats)


def is_doc(rel):
    return any(re.search(p, rel) for p in DOC_PATTERNS)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def decide(event, ctx):
    """The one function dialects call (through the cli). Never raises on purpose,
    but the caller still treats any exception as allow."""
    if not ctx.root and event.kind != PRE_TOOL:
        return Decision()
    if event.kind == SESSION_START:
        return session_start(event, ctx)
    if event.kind == PROMPT:
        return prompt(event, ctx)
    if event.kind == PRE_TOOL:
        if event.tool == SHELL:
            decision, label = pre_shell(event, ctx), "pre-bash"
        elif event.tool in (EDIT, WRITE, MULTI_EDIT):
            decision, label = pre_edit(event, ctx), "pre-edit"
        else:
            return Decision()
        if decision.action in (ASK, DENY):
            ctx.log(f"{label}:{decision.action}", decision.reason.splitlines()[0] if decision.reason else "")
        return decision
    if event.kind == POST_TOOL:
        return post_edit(event, ctx)
    if event.kind == STOP:
        return stop(event, ctx)
    return Decision()


# ---------------------------------------------------------------------------
# session_start: record the session's starting HEAD
# ---------------------------------------------------------------------------

def session_start(event, ctx):
    path = state_path(ctx.root, event.session_id)
    if path:
        state = load_state(path)
        if "start_head" not in state:
            state["start_head"] = git(ctx.root, "rev-parse", "HEAD") or ""
            state["started_at"] = time.time()
            save_state(path, state)
    return Decision()


# ---------------------------------------------------------------------------
# pre_tool / shell: publish gate (G2), dangerous git/rm, secrets, packages, test writes
# ---------------------------------------------------------------------------

def split_segments(command):
    """Split on unquoted &&, ||, ;, | and newlines (separators inside quotes stay put)."""
    segments, buf, quote, i = [], [], None, 0
    while i < len(command):
        ch = command[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < len(command):
                buf.append(command[i:i + 2])
                i += 2
                continue
            if ch == quote:
                quote = None
            buf.append(ch)
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif command.startswith(("&&", "||"), i):
            segments.append("".join(buf))
            buf = []
            i += 2
            continue
        elif ch in ";|\n":
            segments.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return [s.strip() for s in segments if s.strip()]


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
    """Return (action, reason) for a git invocation, or None."""
    if not toks or toks[0] != "git":
        return None
    args = toks[1:]
    while args and args[0] in ("-C", "-c"):
        args = args[2:]
    if not args:
        return None
    sub, rest = args[0], args[1:]
    if "--no-verify" in rest or (sub == "commit" and "-n" in rest):
        return (DENY, "Okeanos: --no-verify pula os hooks de verificação do repositório. Corrija o que o hook acusa em vez de pulá-lo.")
    if sub == "push":
        if any(a in ("--force", "-f") or (a.startswith("-") and not a.startswith("--") and "f" in a) for a in rest):
            return (DENY, "Okeanos: force push reescreve histórico publicado. Se for mesmo necessário, o usuário roda o comando.")
        return (ASK, "Okeanos · G2: publicar (git push) exige a sua aprovação. Confira o resumo do G2 antes de aprovar.")
    if sub == "merge":
        branch = git(root, "rev-parse", "--abbrev-ref", "HEAD") if root else None
        if branch in ("main", "master", "develop", "trunk"):
            return (ASK, f"Okeanos · G2: merge na branch padrão ({branch}) exige a sua aprovação.")
    return None


def check_cli_publish(toks):
    if len(toks) >= 3 and toks[0] in ("gh", "glab") and toks[1] in ("pr", "mr") and toks[2] in ("create", "merge"):
        return (ASK, f"Okeanos · G2: `{' '.join(toks[:3])}` publica o trabalho e exige a sua aprovação.")
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
            return (DENY, f"Okeanos: `rm -r {target}` apaga demais. Remova caminhos específicos dentro do repositório.")
        absolute = os.path.normpath(expanded if os.path.isabs(expanded) else os.path.join(root or os.getcwd(), expanded))
        if root and not (absolute == root or absolute.startswith(root + os.sep)) and not absolute.startswith("/tmp/"):
            return (DENY, f"Okeanos: `rm -r` fora do repositório ({target}). Se for intencional, o usuário roda o comando.")
    return None


def secret_types(text):
    """Names of the secret kinds found in text (never the values)."""
    return [name for name, pat in SECRET_PATTERNS if re.search(pat, text)]


def is_env_file(rel):
    return bool(re.search(r"(^|/)\.env(\.[^/]*)?$", rel)) and not re.search(r"\.(example|sample|template)$", rel)


def added_lines(diff):
    """[(path, line)] for the lines a `git diff -U0` adds (deleted files have none)."""
    out, current = [], None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("+") and current:
            out.append((current, line[1:]))
    return out


def scan_secrets(root):
    """Scan what a commit could include: tracked changes vs HEAD plus untracked files."""
    diff = git(root, "diff", "HEAD", "-U0", "--no-color", timeout=20) or ""
    findings = [f"{rel}: {name}" for rel, line in added_lines(diff) for name in secret_types(line)]
    untracked = (git(root, "ls-files", "--others", "--exclude-standard") or "").splitlines()
    for rel in untracked[:500]:
        if is_env_file(rel):
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
        findings += [f"{rel}: {name}" for name in secret_types(text)]
    return sorted(set(findings))


def bash_write_targets(segment, toks):
    """Paths a shell segment writes, moves or deletes (best effort)."""
    targets = [m.group(1) for m in re.finditer(r"(?:^|[^<>&0-9])>>?\s*([^\s;&|<>]+)", segment)]
    if not toks:
        return targets
    tool, args = toks[0], toks[1:]
    if tool == "sed" and any(a == "--in-place" or a.startswith("-i") for a in args):
        targets += [a for a in args if not a.startswith("-")][1:]
    elif tool == "perl" and any(a.startswith("-") and "i" in a for a in args):
        targets += [a for a in args if not a.startswith("-")][1:]
    elif tool == "awk" and "inplace" in args:
        targets += [a for a in args if not a.startswith("-") and a != "inplace"][1:]
    elif tool in ("tee", "truncate", "rm", "touch", "shred", "unlink"):
        targets += [a for a in args if not a.startswith("-")]
    elif tool in ("mv", "cp", "ln", "install", "rsync") and args:
        plain = [a for a in args if not a.startswith("-")]
        targets += plain if tool == "mv" else plain[-1:]
    elif tool == "dd":
        targets += [a[3:] for a in args if a.startswith("of=")]
    elif tool == "git" and args[:1] == ["rm"]:
        targets += [a for a in args[1:] if not a.startswith("-")]
    return targets


def committed_tests_touched(root, cwd, targets):
    checks = load_checks(root)
    hit = []
    for target in targets:
        full = os.path.normpath(target if os.path.isabs(target) else os.path.join(cwd or root, target))
        if not full.startswith(root + os.sep):
            continue
        rel = os.path.relpath(full, root)
        if is_test(rel, checks) and git(root, "cat-file", "-e", f"HEAD:{rel}") is not None:
            hit.append(rel)
    return sorted(set(hit))


# ---------------------------------------------------------------------------
# approvals belong to the human: the agent never grants them to itself
# ---------------------------------------------------------------------------

HUMAN_ONLY = ("Okeanos: aprovações são do humano. Só o usuário roda `okeanos aprovar`/`revogar`, no terminal dele, "
              "e ninguém além da CLI escreve no estado do Okeanos ({what}). Peça ao usuário e espere.")
APPROVAL_SUBCOMMANDS = ("aprovar", "revogar")
# Tools that run a command line given as an argument or on stdin (including pseudo-terminal wrappers).
COMMAND_RUNNERS = {"sh", "bash", "zsh", "dash", "ksh", "fish", "eval", "xargs", "script", "unbuffer",
                   "expect", "socat", "su", "runuser", "setsid", "nohup", "env", "timeout", "watch"}
STATE_READERS = {"cat", "less", "more", "head", "tail", "ls", "jq", "grep", "rg", "wc", "stat", "file", "diff",
                 "git", "echo", "printf"}  # their writes go through redirects, which are checked above
STATE_MENTION = re.compile(r"(^|[^A-Za-z0-9_])\.git/okeanos(/|\b)|okeanos/approvals\.json")
APPROVAL_TEXT = re.compile(r"okeanos[^\s;&|]*['\"]?\s+(\S+\s+)*?['\"]?(aprovar|revogar)\b")


def okeanos_program(tok):
    """True if a token names the okeanos CLI (any path, inside x=$(...) or backticks)."""
    name = os.path.basename(re.split(r"[=(`'\"]", tok)[-1])
    return bool(re.fullmatch(r"okeanos(\.py)?", name)) or name.startswith("okeanos_engine")


def runs_approval(toks, depth=0):
    for i, tok in enumerate(toks):
        if okeanos_program(tok) and any(t.strip(")`'\"") in APPROVAL_SUBCOMMANDS for t in toks[i + 1:]):
            return True
    plain = strip_env_prefix(toks)
    if depth < 3 and plain and os.path.basename(plain[0]) in COMMAND_RUNNERS:
        for tok in plain[1:]:
            if any(ch.isspace() for ch in tok):
                if any(runs_approval(tokens(seg), depth + 1) for seg in split_segments(tok)):
                    return True
    return False


def under(path, directory):
    return path == directory or path.startswith(directory + os.sep)


def touches_okeanos_state(path, state_dir):
    path = os.path.normpath(path)
    return (state_dir and under(path, state_dir)) or bool(re.search(r"(^|/)\.git/okeanos(/|$)", path))


def self_approval(event, ctx):
    """A deny reason if the shell command approves, revokes or writes Okeanos state; else None."""
    command = event.command
    state_dir = approvals.state_dir(ctx.root) if ctx.root else None
    cwd = event.cwd or ctx.root or os.getcwd()
    segments = split_segments(command)
    for seg in segments:
        toks = tokens(seg)
        if runs_approval(toks):
            return HUMAN_ONLY.format(what="aprovação pelo agente")
        plain = strip_env_prefix(toks)
        for target in bash_write_targets(seg, plain):
            full = os.path.expanduser(target)
            if touches_okeanos_state(full if os.path.isabs(full) else os.path.join(cwd, full), state_dir):
                return HUMAN_ONLY.format(what=target)
        mentions = STATE_MENTION.search(seg) or (state_dir and state_dir in seg)
        if mentions and plain and os.path.basename(plain[0]) not in STATE_READERS:
            return HUMAN_ONLY.format(what="estado em .git/okeanos")
    runners = [strip_env_prefix(tokens(seg)) for seg in segments]
    if any(r and os.path.basename(r[0]) in COMMAND_RUNNERS for r in runners) and APPROVAL_TEXT.search(command):
        return HUMAN_ONLY.format(what="aprovação pelo agente")
    return None


def resolve_asks(asks, ctx):
    """asks: [(targets, reason)]. Approved targets drop out; returns the Decision."""
    root = ctx.root
    live = approvals.active(root) if root else {}
    pending, approved = [], []
    for targets, reason in asks:
        if targets and all(t in live for t in targets):
            approved += targets
        else:
            pending.append((targets, reason))
    if not pending:
        if approved:
            ctx.log(f"{LABELS[ctx.event.tool]}:approved", " ".join(dict.fromkeys(approved)))
        return Decision()
    wanted = list(dict.fromkeys(t for targets, _ in pending for t in targets if t not in live))
    text = "\n".join(reason for _, reason in pending)
    return Decision(ASK, text + ("\n" + approvals.how_to(wanted) if wanted else ""), targets=wanted)


LABELS = {SHELL: "pre-bash", EDIT: "pre-edit", WRITE: "pre-edit", MULTI_EDIT: "pre-edit"}


def pre_shell(event, ctx):
    root, command = ctx.root, event.command
    if not command:
        return Decision()
    denied = self_approval(event, ctx)
    if denied:
        return Decision(DENY, denied)
    live = approvals.active(root) if root else {}
    asks = []
    for seg in split_segments(command):
        toks = strip_env_prefix(tokens(seg))
        for check in (lambda t: check_git(t, root), check_cli_publish, lambda t: check_rm(t, root)):
            result = check(toks)
            if result and result[0] == DENY:
                return Decision(DENY, result[1])
            elif result:
                asks.append(([approvals.PUSH], result[1]))
        if root:
            touched = committed_tests_touched(root, event.cwd, bash_write_targets(seg, toks))
            pending = [t for t in touched if t not in live]
            if touched:
                asks.append((touched, "Okeanos: este comando escreve, move ou apaga teste(s) já commitado(s): "
                             + ", ".join(pending or touched) + ". Testes commitados são o contrato: mudar exige a sua aprovação. "
                             "Adicionar testes novos não pede; prefira a ferramenta Edit para mudanças pontuais."))
        if root and toks[:2] == ["git", "commit"]:
            secrets = scan_secrets(root)
            if secrets:
                return Decision(DENY, "Okeanos: possível segredo no que seria commitado:\n- " + "\n- ".join(secrets[:10])
                                + "\nTire o segredo do código (variável de ambiente, .gitignore) antes de commitar.")
        for eco, name in package_requests(toks)[:5]:
            result = check_package(eco, name)
            if result and result[0] == DENY:
                return Decision(DENY, result[1])
            elif result:
                asks.append(([approvals.PACKAGE_PREFIX + name], result[1]))
    return resolve_asks(asks, ctx)


# ---------------------------------------------------------------------------
# pre_tool / edit, write, multi_edit: committed tests are the contract
# ---------------------------------------------------------------------------

TEST_DEF = re.compile(
    r"\b(test|it|describe|context|scenario)(\.each)?\s*\(|\bdef test_|\bfunc Test|@Test\b|#\[test\]|\bclass Test"
)


def significant(text):
    return [l.strip() for l in text.splitlines() if l.strip()]


def norm_code(text):
    """Formatting-insensitive form: no whitespace, no trailing commas, one quote style.
    A formatter splitting an assertion over several lines doesn't change it."""
    s = re.sub(r"\s+", "", text).replace("'", '"')
    return re.sub(r",([)\]}])", r"\1", s)


def protected_lines_removed(old_text, new_text):
    """Assertion or test-definition lines present before and gone (not just reformatted) after the edit."""
    remaining = norm_code(new_text)
    return [l for l in significant(old_text)
            if (ASSERTION.search(l) or TEST_DEF.search(l)) and norm_code(l) not in remaining]


def weakened_test_lines(old_text, new_text):
    """Lines that remove or alter assertions/test cases, or newly skip tests, going from old to new."""
    before = set(significant(old_text))
    skipped = [l for l in significant(new_text) if SKIP_MARKERS.search(l) and l not in before]
    return protected_lines_removed(old_text, new_text) + skipped


def repo_file(root, path):
    """(full, rel) for a path inside the repo, else None."""
    full = os.path.normpath(path if os.path.isabs(path) else os.path.join(root, path))
    if not full.startswith(root + os.sep):
        return None
    return full, os.path.relpath(full, root)


def pre_edit(event, ctx):
    root = ctx.root
    if event.file_path:
        state_dir = approvals.state_dir(root) if root else None
        base = event.cwd or root or os.getcwd()
        full = os.path.expanduser(event.file_path)
        if touches_okeanos_state(full if os.path.isabs(full) else os.path.join(base, full), state_dir):
            return Decision(DENY, HUMAN_ONLY.format(what=event.file_path))
    if not root:
        return Decision()
    target = repo_file(root, event.file_path) if event.file_path else None
    if not target:
        return Decision()
    full, rel = target
    if not is_test(rel, load_checks(root)):
        return Decision()
    if git(root, "cat-file", "-e", f"HEAD:{rel}") is None:
        return Decision()  # not committed yet: still being written
    if event.tool == WRITE:
        try:
            with open(full, errors="ignore") as f:
                pairs = [(f.read(), event.content or "")]
        except Exception:  # noqa: BLE001
            return Decision()
    else:
        pairs = list(event.edits)
    weakened = [l for old, new in pairs for l in weakened_test_lines(old, new)]
    if weakened:
        detail = "\n".join(f"- {l[:100]}" for l in weakened[:5])
        return resolve_asks([([rel], f"Okeanos: `{rel}` é um teste já commitado, e esta edição altera, remove ou desliga "
                                     f"asserções ou casos de teste:\n{detail}\nTestes commitados são o contrato: mudar exige a sua aprovação. "
                                     "Adicionar testes e mexer em imports ou helpers não pede.")], ctx)
    return Decision()


# ---------------------------------------------------------------------------
# post_tool: per-file format and lint
# ---------------------------------------------------------------------------

def post_edit(event, ctx):
    root = ctx.root
    target = repo_file(root, event.file_path) if event.file_path else None
    if not target or not os.path.exists(target[0]):
        return Decision()
    rel = target[1]
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
        ctx.log("post-edit:fail", rel)
        return Decision(BLOCK, "Okeanos: verificação por edição em " + rel + ":\n\n" + "\n\n".join(failures))
    return Decision()


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
        now = norm_code("\n".join(added.get(rel, [])))
        gone = [l for l in lines if ASSERTION.search(l) and norm_code(l) not in now]
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


def stop(event, ctx):
    root = ctx.root
    path = state_path(root, event.session_id)
    if not path:
        return Decision()
    state = load_state(path)
    base = state.get("start_head") or git(root, "rev-parse", "HEAD")
    files = [f for f in changed_files(root, base) if not is_doc(f)]
    if not files:
        return Decision()
    checks = load_checks(root)
    fp = fingerprint(root, base, files)
    if fp in (state.get("passed_fp"), state.get("escalated_fp")):
        return Decision()

    failures = []
    for check in checks.get("onDone", []):
        cmd = check.get("cmd", "")
        if not cmd:
            continue
        code, out = run(cmd, root, timeout=int(check.get("timeout", 600)), shell=True)
        if code != 0:
            failures.append(f"[{check.get('name', 'check')}] `{cmd}` falhou:\n{tail(out)}")

    if failures and HANDOFF_MARK in event.last_message:
        # The agent says the fix needs a user decision: stop now, but make the failure visible.
        state["blocks"] = 0
        state["escalated_fp"] = fp
        save_state(path, state)
        ctx.log("stop:handoff", failures[0].splitlines()[0])
        return Decision(message="Okeanos: o agente parou com a definição de pronto falhando porque a correção "
                                "depende de uma decisão sua:\n\n" + "\n\n".join(failures))

    if failures:
        state["blocks"] = state.get("blocks", 0) + 1
        ctx.log("stop:block", failures[0].splitlines()[0])
        if state["blocks"] > MAX_BLOCKS:
            ctx.log("stop:escalate", failures[0].splitlines()[0])
            state["blocks"] = 0
            state["escalated_fp"] = fp
            save_state(path, state)
            return Decision(message="Okeanos: a definição de pronto falhou "
                                    f"{MAX_BLOCKS} vezes seguidas e precisa de você:\n\n" + "\n\n".join(failures))
        save_state(path, state)
        return Decision(BLOCK, "Okeanos · definição de pronto: corrija antes de encerrar "
                               f"(tentativa {state['blocks']}/{MAX_BLOCKS}). Se a correção depende de uma decisão do usuário "
                               f"(por exemplo, mudar um teste commitado ou uma regra de produto), não force: explique a decisão "
                               f"e termine sua resposta com a linha `{HANDOFF_MARK}`.\n\n"
                               + "\n\n".join(failures))

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
            ctx.log("stop:size", size)
    review = tamper + suppressions
    review_sig = hashlib.sha256("\n".join(review).encode()).hexdigest() if review else ""
    if review and state.get("tamper_sig") != review_sig:
        state["tamper_sig"] = review_sig
        save_state(path, state)
        for note in review:
            ctx.log("stop:tamper" if note in tamper else "stop:suppression", note)
        return Decision(BLOCK, "Okeanos: pontos que o usuário precisa saber nesta sessão:\n- " + "\n- ".join(review)
                               + "\nNa sua resposta, diga cada um ao usuário com o motivo. Teste afrouxado ou supressão sem motivo forte: desfaça.")
    if state.get("passed_fp") != fp:
        ctx.log("stop:pass", f"{size} linhas")
    state["passed_fp"] = fp
    save_state(path, state)
    if tamper:
        warnings.append("testes alterados: " + "; ".join(tamper))
    if suppressions:
        warnings.append(f"{len(suppressions)} supressão(ões) de lint/tipo nova(s)")
    if warnings:
        return Decision(message="Okeanos: " + "\n".join(warnings))
    return Decision()


# ---------------------------------------------------------------------------
# prompt: first message of a session gets the route reminder
# ---------------------------------------------------------------------------

ROUTE_REMINDER = ("Okeanos: antes de agir nesta demanda, classifique a rota e anuncie em uma linha "
                  "(**Okeanos** · rota: <Direto|Bug|Feature|Feature grande|Épico|Triagem> · <motivo>). "
                  "Perguntas puras dispensam o anúncio.")


def prompt(event, ctx):
    path = state_path(ctx.root, event.session_id)
    if not path:
        return Decision()
    state = load_state(path)
    if state.get("route_reminded"):
        return Decision()
    state["route_reminded"] = True
    save_state(path, state)
    return Decision(context=ROUTE_REMINDER)
