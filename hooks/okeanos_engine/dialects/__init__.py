"""Dialects: one module per agent, each exposing NAME, parse(hook, data) and render(hook, event, decision).

parse(hook, data) -> Event | None
    hook is the subcommand from the agent's hook config; data is the decoded stdin JSON
    (any JSON value). Return None when there is nothing to check (unknown hook, malformed payload).
render(hook, event, decision) -> (stdout_text, exit_code)
    event may be None (parse failed or an internal error happened); decision is then allow.

Adding an agent: write dialects/<agent>.py and register it below. Rules stay untouched.
"""

from . import claude

DIALECTS = {claude.NAME: claude}
DEFAULT = claude.NAME
