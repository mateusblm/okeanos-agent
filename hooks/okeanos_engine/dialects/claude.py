"""Claude Code dialect.

Hooks are wired in hooks/hooks.json, one subcommand per hook:
  session-start (SessionStart), prompt (UserPromptSubmit), pre-bash (PreToolUse Bash),
  pre-edit (PreToolUse Edit|Write|MultiEdit), post-edit (PostToolUse Edit|Write|MultiEdit), stop (Stop).
Output is JSON on stdout with exit code 0; no output means allow.
"""

import json

from ..model import (ASK, BLOCK, DENY, EDIT, MULTI_EDIT, OTHER, POST_TOOL, PRE_TOOL, PROMPT,
                     SESSION_START, SHELL, STOP, WRITE, Event)

NAME = "claude"

HOOKS = {
    "session-start": (SESSION_START, "SessionStart"),
    "prompt": (PROMPT, "UserPromptSubmit"),
    "pre-bash": (PRE_TOOL, "PreToolUse"),
    "pre-edit": (PRE_TOOL, "PreToolUse"),
    "post-edit": (POST_TOOL, "PostToolUse"),
    "stop": (STOP, "Stop"),
}
EDIT_TOOLS = {"Edit": EDIT, "Write": WRITE, "MultiEdit": MULTI_EDIT}


class Malformed(Exception):
    pass


def _str(value, default=""):
    if value is None:
        return default
    if not isinstance(value, str):
        raise Malformed
    return value


def parse(hook, data):
    """Claude Code hook payload -> Event, or None when there is nothing to check."""
    if hook not in HOOKS or not isinstance(data, dict):
        return None
    try:
        kind = HOOKS[hook][0]
        sid = data.get("session_id")
        event = Event(agent=NAME, kind=kind, cwd=_str(data.get("cwd"), None),
                      session_id=sid if isinstance(sid, str) else None)
        if kind in (PRE_TOOL, POST_TOOL):
            ti = data.get("tool_input") or {}
            if not isinstance(ti, dict):
                raise Malformed
            if hook == "pre-bash":
                event.tool = SHELL
                event.command = _str(ti.get("command"))
                return event
            event.tool = EDIT_TOOLS.get(data.get("tool_name"), OTHER)
            event.file_path = _str(ti.get("file_path"))
            if event.tool == EDIT:
                event.edits = [(_str(ti.get("old_string")), _str(ti.get("new_string")))]
            elif event.tool == MULTI_EDIT:
                edits = ti.get("edits") or []
                if not isinstance(edits, list) or not all(isinstance(e, dict) for e in edits):
                    raise Malformed
                event.edits = [(_str(e.get("old_string")), _str(e.get("new_string"))) for e in edits]
            elif event.tool == WRITE:
                event.content = _str(ti.get("content"))
        elif kind == STOP:
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
        out["hookSpecificOutput"] = {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision.action,
            "permissionDecisionReason": decision.reason,
        }
    elif decision.action == BLOCK and hook_event in ("PostToolUse", "Stop"):
        out["decision"] = "block"
        out["reason"] = decision.reason
    if decision.context and hook_event in ("UserPromptSubmit", "SessionStart"):
        out["hookSpecificOutput"] = {"hookEventName": hook_event, "additionalContext": decision.context}
    if decision.message:
        out["systemMessage"] = decision.message
    return (json.dumps(out, ensure_ascii=False) if out else ""), 0
