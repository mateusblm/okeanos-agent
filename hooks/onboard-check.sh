#!/usr/bin/env bash
# SessionStart: if the session is in a git repo with source files but no
# CLAUDE.md, tell Okeanos to run the onboard skill before anything else.
set -u

input="$(cat 2>/dev/null || true)"
cwd="$(printf '%s' "$input" | sed -n 's/.*"cwd"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
cwd="${cwd:-${CLAUDE_PROJECT_DIR:-$PWD}}"

root="$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)" || exit 0
# Only repos with something beyond a README are worth onboarding.
files="$(git -C "$root" ls-files 2>/dev/null | grep -viE '^(readme|license|\.gitignore)' | head -n 1)"
[ -n "$files" ] || exit 0

has_context=0
{ [ -f "$root/CLAUDE.md" ] || [ -f "$root/.claude/CLAUDE.md" ]; } && has_context=1
has_checks=0
[ -f "$root/docs/agents/checks.json" ] && has_checks=1
[ "$has_context" = 1 ] && [ "$has_checks" = 1 ] && exit 0

if [ "$has_context" = 1 ]; then
  note="This repo has CLAUDE.md but no docs/agents/checks.json, so the Okeanos hooks have no commands to run. Before anything else, call the Skill tool with okeanos:onboard and do only its checks.json step."
elif [ -f "$root/AGENTS.md" ]; then
  note="This repo has AGENTS.md but no CLAUDE.md. Before anything else, call the Skill tool with okeanos:onboard."
else
  note="This repo has no CLAUDE.md. Before anything else, call the Skill tool with okeanos:onboard."
fi

msg="Okeanos: ${note} Then continue with the user's request."
printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$msg"
