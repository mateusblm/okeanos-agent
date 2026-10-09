"""GitHub Copilot dialect: Copilot CLI and the cloud agent
(hooks reference: https://docs.github.com/en/copilot/reference/hooks-reference).

Hooks are wired in ~/.copilot/hooks/okeanos.json by `okeanos install`, one subcommand per event:
  session-start (sessionStart), pre-tool (preToolUse), post-tool (postToolUse), stop (agentStop).
`prompt` (userPromptSubmitted) is understood but not installed: Copilot drops the output of
command hooks on that event, so the first-prompt route reminder rides on session-start instead
(session-start yields a session_start and a prompt Event; the cli combines them).

Two payload variants, picked by the event name in the config:
  camelCase (sessionStart, preToolUse, ...): sessionId, cwd, toolName, toolArgs (a JSON string
    in the CLI; an object is accepted too). Tools: bash/powershell (command), edit (path, old_str,
    new_str), create (path, file_text), str_replace_editor (command + those), apply_patch.
  VS Code compatible (SessionStart, PreToolUse, ...): session_id, hook_event_name, tool_name with
    the Claude tool name (Bash, Edit, Write), tool_input. Claude field names are accepted too.
The arguments of the edit tools aren't in the docs; both spellings are read.

Output is one JSON object on stdout, exit code 0 (a non-zero exit denies preToolUse).
preToolUse: {"permissionDecision": allow|deny|ask, "permissionDecisionReason"}; the CLI shows ask
to the user, the cloud agent (COPILOT_AGENT_PROMPT in the environment) treats it as deny, so there
ask is rendered as deny, keeping the last line `Para aprovar: okeanos aprovar <alvo>`. So is
COPILOT_ALLOW_ALL, where nobody may be watching. agentStop: {"decision": "block", "reason"} runs
another turn. sessionStart/postToolUse: {"additionalContext"}. The VS Code variant also gets the
Claude-style hookSpecificOutput. There is no user-only message field, so Decision.message is dropped.
agentStop carries no final message: it is read from the transcript (format not documented; the
last JSON line whose type or role says assistant).
"""

import json
import os
from dataclasses import dataclass

from ..model import (ASK, BLOCK, DENY, EDIT, MULTI_EDIT, OTHER, POST_TOOL, PRE_TOOL, PROMPT, SESSION_START,
                     SHELL, STOP, WRITE, Event)
from .codex import patch_events, shell_command

NAME = "copilot"

HOOKS = {
    "session-start": (SESSION_START, "sessionStart", "SessionStart"),
    "prompt": (PROMPT, "userPromptSubmitted", "UserPromptSubmit"),
    "pre-tool": (PRE_TOOL, "preToolUse", "PreToolUse"),
    "post-tool": (POST_TOOL, "postToolUse", "PostToolUse"),
    "stop": (STOP, "agentStop", "Stop"),
}
SHELL_TOOLS = {"bash", "powershell", "shell", "Bash"}
PATCH_TOOLS = {"apply_patch"}
EDIT_TOOLS = {"edit", "create", "write", "str_replace_editor", "Edit", "Write", "MultiEdit"}
PASCAL_KEYS = ("hook_event_name", "session_id", "tool_name", "tool_input")
NO_ASK = ("Aqui o Copilot não pede confirmação pelo hook (agente na nuvem ou --allow-all): peça ao "
          "usuário que rode no terminal dele o comando abaixo e tente de novo. Você nunca roda esse comando.")
TRANSCRIPT_TAIL = 256 * 1024


@dataclass
class CopilotEvent(Event):
    pascal: bool = False  # VS Code compatible payload: answer with hookSpecificOutput too


class Malformed(Exception):
    pass


def _str(value, default=""):
    if value is None:
        return default
    if not isinstance(value, str):
        raise Malformed
    return value


def _first(d, *keys):
    return next((d[k] for k in keys if d.get(k) is not None), None)


def no_ask():
    """The cloud agent answers ask with deny; with --allow-all there may be no one to ask."""
    return bool(os.environ.get("COPILOT_AGENT_PROMPT") or os.environ.get("COPILOT_ALLOW_ALL"))


def tool_args(raw):
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            raise Malformed
    if not isinstance(raw, dict):
        raise Malformed
    return raw


def edit_event(event, name, args):
    """Fill an edit/create Event; None when the call doesn't change a file (view, undo)."""
    path = _str(_first(args, "path", "file_path", "filePath"))
    if not path:
        raise Malformed
    if not os.path.isabs(path) and event.cwd:
        path = os.path.join(event.cwd, path)
    event.file_path = path
    sub = args.get("command") if name == "str_replace_editor" else None
    if sub not in (None, "create", "str_replace", "insert"):
        return None
    content = _first(args, "file_text", "content")
    if sub == "create" or name in ("create", "write", "Write") or (content is not None and sub is None
                                                                    and "old_str" not in args
                                                                    and "old_string" not in args):
        event.tool, event.content = WRITE, _str(content)
    elif isinstance(args.get("edits"), list):
        edits = args["edits"]
        if not all(isinstance(e, dict) for e in edits):
            raise Malformed
        event.tool = MULTI_EDIT
        event.edits = [(_str(_first(e, "old_str", "old_string")), _str(_first(e, "new_str", "new_string")))
                       for e in edits]
    else:
        old = "" if sub == "insert" else _str(_first(args, "old_str", "old_string"))
        event.tool, event.edits = EDIT, [(old, _str(_first(args, "new_str", "new_string")))]
    return event


def patch_text(args):
    text = _first(args, "input", "patch", "command")
    return text if isinstance(text, str) and "*** Begin Patch" in text else None


def last_assistant_message(path):
    """The final assistant text from the transcript, "" when it can't be read."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - TRANSCRIPT_TAIL))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError, ValueError):
        return ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("type") or entry.get("role") or "")
        if "assistant" not in kind:
            continue
        for holder in (entry.get("data"), entry.get("message"), entry):
            if isinstance(holder, dict) and isinstance(holder.get("content"), str):
                return holder["content"]
    return ""


def parse(hook, data):
    """Copilot hook payload -> Event, a list of Events, or None."""
    if hook not in HOOKS or not isinstance(data, dict):
        return None
    try:
        kind = HOOKS[hook][0]
        pascal = any(k in data for k in PASCAL_KEYS)
        sid = _first(data, "sessionId", "session_id")
        sid = sid if isinstance(sid, str) else None
        cwd = _str(data.get("cwd"), None)

        def make(k):
            return CopilotEvent(agent=NAME, kind=k, cwd=cwd, session_id=sid, pascal=pascal)

        event = make(kind)
        if kind in (PRE_TOOL, POST_TOOL):
            name = _first(data, "toolName", "tool_name")
            args = tool_args(_first(data, "toolArgs", "tool_input"))
            patch = patch_text(args) if name in PATCH_TOOLS or name == "Edit" else None
            if name in SHELL_TOOLS:
                if kind == POST_TOOL:
                    return None
                command = shell_command(args.get("command"))
                event.tool, event.command = SHELL, command
                patched = patch_events(command, kind, cwd, sid, agent=NAME)
                return [event] + patched if patched else event
            if patch is not None or name in PATCH_TOOLS:
                return patch_events(patch or "", kind, cwd, sid, agent=NAME) or None
            if name in EDIT_TOOLS:
                event = edit_event(event, name, args)
                if event is not None and kind == POST_TOOL:
                    event.tool = MULTI_EDIT
                return event
            event.tool = OTHER
            return event
        if kind == STOP:
            transcript = _first(data, "transcriptPath", "transcript_path")
            event.last_message = last_assistant_message(transcript) if isinstance(transcript, str) else ""
        elif kind == PROMPT:
            event.prompt = _str(data.get("prompt"))
        elif kind == SESSION_START:
            prompt = make(PROMPT)
            prompt.prompt = _str(_first(data, "initialPrompt", "initial_prompt"))
            return [event, prompt]
        return event
    except Malformed:
        return None


def render(hook, event, decision):
    """Decision -> (stdout text, exit code)."""
    if hook not in HOOKS:
        return "", 0
    kind, _, pascal_name = HOOKS[hook]
    pascal = bool(getattr(event, "pascal", False))
    out, extra = {}, {}
    if decision.action in (ASK, DENY) and kind == PRE_TOOL:
        action, reason = decision.action, decision.reason
        if action == ASK and no_ask():
            action = DENY
            if decision.targets:
                head, last = reason.rsplit("\n", 1) if "\n" in reason else ("", reason)
                reason = "\n".join(p for p in (head, NO_ASK, last) if p)
        out = {"permissionDecision": action, "permissionDecisionReason": reason}
        extra = {"permissionDecision": action, "permissionDecisionReason": reason}
    elif decision.action == BLOCK and kind == STOP:
        out = {"decision": "block", "reason": decision.reason}
    elif decision.action == BLOCK and kind == POST_TOOL:
        out = {"additionalContext": decision.reason}
        extra = dict(out)
    if decision.context and kind in (SESSION_START, PROMPT):
        out = {"additionalContext": decision.context}
        extra = dict(out)
    if pascal and extra:
        out["hookSpecificOutput"] = {"hookEventName": pascal_name, **extra}
    return (json.dumps(out, ensure_ascii=False) if out else ""), 0
