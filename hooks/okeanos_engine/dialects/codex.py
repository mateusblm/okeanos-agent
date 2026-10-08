"""OpenAI Codex dialect (hooks reference: https://learn.chatgpt.com/docs/hooks).

Hooks are wired in Codex's user hooks.json by `okeanos install`, one subcommand per event:
  session-start (SessionStart), prompt (UserPromptSubmit), pre-tool (PreToolUse Bash|apply_patch),
  post-tool (PostToolUse Bash|apply_patch), stop (Stop).
Payloads: tool_name "Bash" carries the shell command in tool_input.command; tool_name "apply_patch"
carries the patch text in tool_input.command (`*** Begin Patch` ... `*** End Patch`).
Output is JSON on stdout with exit code 0; no output means allow.

Codex parses permissionDecision "ask" but doesn't support it (the tool would run anyway), so an
ask is rendered as deny, keeping the last line `Para aprovar: okeanos aprovar <alvo>`. A Stop
"block" makes Codex continue the turn with the reason as the next prompt.
"""

import json
import os
import re
import shlex

from ..model import (ASK, BLOCK, DENY, MULTI_EDIT, OTHER, POST_TOOL, PRE_TOOL, PROMPT, SESSION_START,
                     SHELL, STOP, WRITE, Event)

NAME = "codex"

HOOKS = {
    "session-start": (SESSION_START, "SessionStart"),
    "prompt": (PROMPT, "UserPromptSubmit"),
    "pre-tool": (PRE_TOOL, "PreToolUse"),
    "post-tool": (POST_TOOL, "PostToolUse"),
    "stop": (STOP, "Stop"),
}
SHELL_TOOLS = {"Bash", "shell", "local_shell", "exec_command", "unified_exec"}
PATCH_TOOLS = {"apply_patch", "Edit", "Write"}
SHELLS = {"bash", "sh", "zsh", "dash"}
NO_ASK = ("O Codex não pede confirmação pelo hook: peça ao usuário que rode no terminal dele o comando "
          "abaixo e tente de novo. Você nunca roda esse comando.")


class Malformed(Exception):
    pass


def _str(value, default=""):
    if value is None:
        return default
    if not isinstance(value, str):
        raise Malformed
    return value


def shell_command(value):
    """tool_input.command as a string: Codex sends a string; older shells sent an argv list."""
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        if len(value) >= 3 and os.path.basename(value[0]) in SHELLS and value[1] in ("-c", "-lc"):
            return value[2]
        return shlex.join(value)
    return _str(value)


# ---------------------------------------------------------------------------
# apply_patch
# ---------------------------------------------------------------------------

HEADER = re.compile(r"^\*\*\* (Add|Delete|Update) File: (.+?)\s*$")
MOVE = re.compile(r"^\*\*\* Move to: (.+?)\s*$")


def parse_patch(text):
    """The files of an apply_patch text: [{op, path, move_to, hunks, added, broken}], [] if none.

    hunks: [(old_text, new_text)] for updates; added: the new file's lines for adds.
    broken: a section that doesn't follow the grammar; callers treat it as a full rewrite.
    """
    if "*** Begin Patch" not in text:
        return []
    lines = text.split("*** Begin Patch", 1)[1].splitlines()
    files, cur, hunk = [], None, None

    def close_hunk():
        if cur is not None and hunk is not None and (hunk[0] or hunk[1]):
            cur["hunks"].append(("\n".join(hunk[0]), "\n".join(hunk[1])))

    for line in lines:
        if line.strip() == "*** End Patch":
            break
        m = HEADER.match(line)
        if m:
            close_hunk()
            cur = {"op": m.group(1).lower(), "path": m.group(2), "move_to": None, "hunks": [], "added": [],
                   "broken": False}
            hunk = None
            files.append(cur)
            continue
        if cur is None:
            continue
        if cur["op"] == "add":
            if line.startswith("+"):
                cur["added"].append(line[1:])
            elif line.strip():
                cur["broken"] = True
        elif cur["op"] == "update":
            mv = MOVE.match(line)
            if mv and hunk is None:
                cur["move_to"] = mv.group(1)
            elif line.startswith("@@"):
                close_hunk()
                hunk = ([], [])
            elif line.strip() == "*** End of File":
                continue
            elif line[:1] in (" ", "-", "+") or line == "":
                if hunk is None:
                    hunk = ([], [])
                body = line[1:]
                if line[:1] in (" ", ""):
                    hunk[0].append(body)
                    hunk[1].append(body)
                elif line[0] == "-":
                    hunk[0].append(body)
                else:
                    hunk[1].append(body)
            else:
                cur["broken"] = True
        elif line.strip():
            cur["broken"] = True  # a delete section has no body
    close_hunk()
    return files


def patch_events(text, kind, cwd, session_id):
    """One Event per file the patch touches. Anything we can't read is a full rewrite."""
    def at(path):
        return path if os.path.isabs(path) or not cwd else os.path.join(cwd, path)

    def make(path, **fields):
        return Event(agent=NAME, kind=kind, cwd=cwd, session_id=session_id, file_path=at(path), **fields)

    events = []
    for f in parse_patch(text):
        if kind == POST_TOOL:
            if f["op"] != "delete":
                events.append(make(f["move_to"] or f["path"], tool=MULTI_EDIT))
            continue
        rewrite = {"tool": WRITE, "content": ""}
        if f["op"] == "delete" or f["broken"]:
            events.append(make(f["path"], **rewrite))
        elif f["op"] == "add":
            events.append(make(f["path"], tool=WRITE, content="\n".join(f["added"]) + "\n"))
        elif f["move_to"]:
            events.append(make(f["path"], **rewrite))      # the old file is gone
            events.append(make(f["move_to"], **rewrite))   # and whatever was at the destination
        else:
            events.append(make(f["path"], tool=MULTI_EDIT, edits=list(f["hunks"])))
    return events


# ---------------------------------------------------------------------------
# parse / render
# ---------------------------------------------------------------------------

def parse(hook, data):
    """Codex hook payload -> Event, a list of Events (one per patched file), or None."""
    if hook not in HOOKS or not isinstance(data, dict):
        return None
    try:
        kind = HOOKS[hook][0]
        sid = data.get("session_id")
        sid = sid if isinstance(sid, str) else None
        cwd = _str(data.get("cwd"), None)
        event = Event(agent=NAME, kind=kind, cwd=cwd, session_id=sid)
        if kind in (PRE_TOOL, POST_TOOL):
            ti = data.get("tool_input") or {}
            if not isinstance(ti, dict):
                raise Malformed
            name = data.get("tool_name")
            if name in SHELL_TOOLS:
                command = shell_command(ti.get("command"))
                patched = patch_events(command, kind, cwd, sid)
                if kind == POST_TOOL:
                    return patched or None
                event.tool, event.command = SHELL, command
                return [event] + patched if patched else event
            if name in PATCH_TOOLS:
                text = next((v for v in (ti.get("command"), ti.get("input"), ti.get("patch")) if v is not None), "")
                return patch_events(_str(text), kind, cwd, sid) or None
            event.tool = OTHER
            return event
        if kind == STOP:
            event.last_message = _str(data.get("last_assistant_message"))
        elif kind == PROMPT:
            event.prompt = _str(data.get("prompt"))
        return event
    except Malformed:
        return None


def render(hook, event, decision):
    """Decision -> (stdout text, exit code)."""
    hook_event = HOOKS.get(hook, (None, None))[1]
    out = {}
    if decision.action in (ASK, DENY) and hook_event == "PreToolUse":
        reason = decision.reason
        if decision.action == ASK and decision.targets:
            head, last = reason.rsplit("\n", 1) if "\n" in reason else ("", reason)
            reason = "\n".join(p for p in (head, NO_ASK, last) if p)
        out["hookSpecificOutput"] = {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    elif decision.action == BLOCK and hook_event in ("PostToolUse", "Stop"):
        out["decision"] = "block"
        out["reason"] = decision.reason
    if decision.context and hook_event in ("UserPromptSubmit", "SessionStart"):
        out["hookSpecificOutput"] = {"hookEventName": hook_event, "additionalContext": decision.context}
    if decision.message:
        out["systemMessage"] = decision.message
    return (json.dumps(out, ensure_ascii=False) if out else ""), 0
