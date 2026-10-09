"""The agent-neutral contract between dialects and rules.

A dialect turns an agent's hook payload into an Event, the rules turn the Event
into a Decision, and the dialect turns the Decision into the agent's output.
Rules never see agent payloads; dialects never decide anything.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Event kinds
SESSION_START = "session_start"
PROMPT = "prompt"
PRE_TOOL = "pre_tool"
POST_TOOL = "post_tool"
STOP = "stop"
EVENT_KINDS = (SESSION_START, PROMPT, PRE_TOOL, POST_TOOL, STOP)

# Tool kinds (only meaningful for pre_tool / post_tool)
SHELL = "shell"
EDIT = "edit"
WRITE = "write"
MULTI_EDIT = "multi_edit"
OTHER = "other"
TOOL_KINDS = (SHELL, EDIT, WRITE, MULTI_EDIT, OTHER)

# Decision actions
ALLOW = "allow"
ASK = "ask"
DENY = "deny"
BLOCK = "block"


@dataclass
class Event:
    agent: str                            # dialect name, e.g. "claude"; recorded in every metrics event
    kind: str                             # one of EVENT_KINDS
    cwd: Optional[str] = None             # directory the agent works in; None = the hook's own cwd
    session_id: Optional[str] = None      # stable per agent session; None = "default"
    tool: Optional[str] = None            # one of TOOL_KINDS for pre_tool/post_tool, else None
    command: str = ""                     # shell: the full command line
    file_path: str = ""                   # edit/write/multi_edit (and post_tool): target path, absolute or relative to the repo root
    edits: List[Tuple[str, str]] = field(default_factory=list)  # edit/multi_edit: (old_text, new_text) pairs
    content: Optional[str] = None         # write: the full new file content (old content is read from disk)
    prompt: str = ""                      # prompt: the user's message
    last_message: str = ""                # stop: the agent's final message (handoff line detection)


@dataclass
class Decision:
    """What the rules want. The dialect decides how to express it.

    action:
      allow  nothing to say (context/message may still be set)
      ask    pre_tool: needs the user's approval; reason says why
      deny   pre_tool: refuse; reason says why
      block  stop: don't let the agent finish yet; post_tool: send reason back to the agent
    reason:  text for the agent (and the user, in approval prompts)
    context: prompt/session_start: text to add to the agent's context
    message: text shown to the user only, never blocks
    targets: ask: what `okeanos aprovar` would release; the reason then ends with that command
    """
    action: str = ALLOW
    reason: str = ""
    context: str = ""
    message: str = ""
    targets: List[str] = field(default_factory=list)

    @property
    def silent(self):
        return self.action == ALLOW and not self.context and not self.message
