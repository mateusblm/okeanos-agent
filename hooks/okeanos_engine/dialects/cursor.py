"""Cursor IDE dialect (hooks reference: https://cursor.com/docs/agent/hooks).

Hooks are wired in ~/.cursor/hooks.json by `okeanos install`, one subcommand per event:
  session-start (sessionStart), shell (beforeShellExecution), pre-tool (preToolUse on the file tools),
  post-tool (postToolUse on the file tools), agent-response (afterAgentResponse), stop (stop).
Every payload carries conversation_id (our session id) and workspace_roots; `cwd` is sometimes
empty, and then the first workspace root is the working directory.

Shell: beforeShellExecution sends `command` and `cwd` and enforces `permission: "ask"`, so an ask
stays an ask there. Editor: preToolUse sends `tool_name` Write/Delete (documented) or StrReplace
(seen in the field), with `tool_input.file_path` or `.path`, `content` for Write and
`old_string`/`new_string` for StrReplace. Cursor accepts but does NOT enforce "ask" in preToolUse
(the tool would run), so an ask is rendered as deny with the last line
`Para aprovar: okeanos aprovar <alvo>`. A Write whose new content we can't read counts as a
rewrite of the whole file, like a Delete. Permission hooks always print JSON: Cursor blocks the
action when a permission hook's output doesn't parse.

postToolUse answers with `additional_context` (the only channel back to the agent after an edit).
stop has no last-message field: afterAgentResponse's `text` is remembered per conversation in
<git-common-dir>/okeanos/sessions/ so the stop check can see the handoff line. A stop "block"
becomes `followup_message`, which Cursor submits as the next user message (capped by loop_limit,
5 by default, above the rules' 3 attempts). An aborted or failed turn is never continued.
Messages meant only for the user have no field on stop and sessionStart and are dropped.
"""

import json
import os

from ..model import (ASK, BLOCK, DENY, MULTI_EDIT, EDIT, OTHER, POST_TOOL, PRE_TOOL, SESSION_START, SHELL,
                     STOP, WRITE, Event)
from ..plumbing import okeanos_dir, repo_root

NAME = "cursor"

HOOKS = {
    "session-start": (SESSION_START, "sessionStart"),
    "shell": (PRE_TOOL, "beforeShellExecution"),
    "pre-tool": (PRE_TOOL, "preToolUse"),
    "post-tool": (POST_TOOL, "postToolUse"),
    "agent-response": (None, "afterAgentResponse"),
    "stop": (STOP, "stop"),
}
PERMISSION_HOOKS = ("beforeShellExecution", "preToolUse")
SHELL_TOOLS = {"Shell", "Terminal", "run_terminal_cmd"}
EDIT_TOOLS = {"StrReplace", "Edit", "search_replace"}
WRITE_TOOLS = {"Write", "MultiEdit", "edit_file", "write"}
DELETE_TOOLS = {"Delete", "delete_file"}
FILE_TOOLS_MATCHER = "Write|StrReplace|Delete|Edit|MultiEdit"
NO_ASK = ("O Cursor não pede confirmação nas edições pelo hook: peça ao usuário que rode no terminal dele o "
          "comando abaixo e tente de novo. Você nunca roda esse comando.")
LAST_MESSAGE_SUFFIX = ".cursor-last-response"


class Malformed(Exception):
    pass


def _str(value, default=""):
    if value is None:
        return default
    if not isinstance(value, str):
        raise Malformed
    return value


def working_dir(data):
    """The payload's cwd, else the first workspace root, else None (the hook's own cwd)."""
    cwd = _str(data.get("cwd"), None)
    if cwd:
        return cwd
    roots = data.get("workspace_roots")
    if roots is None:
        return None
    if not isinstance(roots, list) or not all(isinstance(r, str) for r in roots):
        raise Malformed
    return roots[0] if roots and roots[0] else None


def session_of(data):
    for key in ("conversation_id", "session_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def last_response_path(cwd, session_id):
    d = okeanos_dir(repo_root(cwd or os.getcwd()))
    if not d:
        return None
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (session_id or "default"))
    return os.path.join(d, "sessions", safe + LAST_MESSAGE_SUFFIX)


def remember_response(cwd, session_id, text):
    path = last_response_path(cwd, session_id)
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)


def last_response(cwd, session_id):
    path = last_response_path(cwd, session_id)
    try:
        with open(path) as f:
            return f.read()
    except Exception:  # noqa: BLE001
        return ""


def file_event(event, name, ti):
    """Fill an editor-tool Event from tool_input."""
    path = next((v for v in (ti.get("file_path"), ti.get("path"), ti.get("target_file")) if v), "")
    event.file_path = _str(path)
    if event.file_path and not os.path.isabs(event.file_path) and event.cwd:
        event.file_path = os.path.join(event.cwd, event.file_path)
    if event.kind == POST_TOOL:
        event.tool = MULTI_EDIT
        return event
    content = next((v for v in (ti.get("content"), ti.get("contents"), ti.get("file_text")) if v is not None), None)
    if name in DELETE_TOOLS:
        event.tool, event.content = WRITE, ""
    elif "old_string" in ti or "new_string" in ti:
        event.tool = EDIT
        event.edits = [(_str(ti.get("old_string")), _str(ti.get("new_string")))]
    elif isinstance(ti.get("edits"), list):
        edits = ti["edits"]
        if not all(isinstance(e, dict) for e in edits):
            raise Malformed
        event.tool = MULTI_EDIT
        event.edits = [(_str(e.get("old_string")), _str(e.get("new_string"))) for e in edits]
    else:
        event.tool, event.content = WRITE, _str(content)  # unknown content: a rewrite of the whole file
    return event


def parse(hook, data):
    """Cursor hook payload -> Event, or None when there is nothing to check."""
    if hook not in HOOKS or not isinstance(data, dict):
        return None
    try:
        kind = HOOKS[hook][0]
        cwd, sid = working_dir(data), session_of(data)
        if hook == "agent-response":
            remember_response(cwd, sid, _str(data.get("text")))
            return None
        event = Event(agent=NAME, kind=kind, cwd=cwd, session_id=sid)
        if hook == "shell":
            event.tool, event.command = SHELL, _str(data.get("command"))
            return event
        if kind in (PRE_TOOL, POST_TOOL):
            ti = data.get("tool_input") or {}
            if not isinstance(ti, dict):
                raise Malformed
            name = data.get("tool_name")
            if name in SHELL_TOOLS:
                if kind == POST_TOOL:
                    return None
                event.tool, event.command = SHELL, _str(ti.get("command"))
                return event
            if name in EDIT_TOOLS | WRITE_TOOLS | DELETE_TOOLS:
                if kind == POST_TOOL and name in DELETE_TOOLS:
                    return None
                return file_event(event, name, ti)
            event.tool = OTHER
            return event
        if kind == STOP:
            if data.get("status", "completed") != "completed":
                return None
            event.last_message = last_response(cwd, sid)
        return event
    except (Malformed, OSError):
        return None


def render(hook, event, decision):
    """Decision -> (stdout text, exit code)."""
    hook_event = HOOKS.get(hook, (None, None))[1]
    if hook_event in PERMISSION_HOOKS:
        if decision.action not in (ASK, DENY):
            return json.dumps({"permission": "allow"}), 0
        reason, permission = decision.reason, decision.action
        if decision.action == ASK and hook_event == "preToolUse":
            permission = DENY
            if decision.targets:
                head, last = reason.rsplit("\n", 1) if "\n" in reason else ("", reason)
                reason = "\n".join(p for p in (head, NO_ASK, last) if p)
        out = {"permission": permission, "user_message": reason, "agent_message": reason}
        return json.dumps(out, ensure_ascii=False), 0
    out = {}
    if decision.action == BLOCK and hook_event == "stop":
        out["followup_message"] = decision.reason
    elif decision.action == BLOCK and hook_event == "postToolUse":
        out["additional_context"] = decision.reason
    elif decision.context and hook_event == "sessionStart":
        out["additional_context"] = decision.context
    return (json.dumps(out, ensure_ascii=False) if out else ""), 0
