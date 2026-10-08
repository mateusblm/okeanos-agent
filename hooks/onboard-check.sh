#!/usr/bin/env bash
# SessionStart: if the session is in a git repo with source files but no agent
# context file (CLAUDE.md in Claude Code, AGENTS.md elsewhere) or no
# docs/agents/checks.json, tell the agent to run the onboard skill first.
#   onboard-check.sh [--agent claude|codex|copilot|cursor|...]   (default: claude)
# The output is hookSpecificOutput.additionalContext (Claude Code, Codex), a top-level
# additionalContext (Copilot's camelCase sessionStart) or additional_context (Cursor).
set -u

agent=claude
case "${1:-}" in
  --agent) agent="${2:-claude}" ;;
  --agent=*) agent="${1#--agent=}" ;;
esac

input="$(cat 2>/dev/null || true)"
cwd="$(printf '%s' "$input" | sed -n 's/.*"cwd"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
# Cursor may send an empty cwd; its workspace_roots[0] is the project.
[ -n "$cwd" ] || cwd="$(printf '%s' "$input" | sed -n 's/.*"workspace_roots"[[:space:]]*:[[:space:]]*\[[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
cwd="${cwd:-${CURSOR_PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-$PWD}}}"

root="$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)" || exit 0
# Only repos with something beyond a README are worth onboarding.
files="$(git -C "$root" ls-files 2>/dev/null | grep -viE '^(readme|license|\.gitignore)' | head -n 1)"
[ -n "$files" ] || exit 0

has_checks=0
[ -f "$root/docs/agents/checks.json" ] && has_checks=1

if [ "$agent" = claude ]; then
  has_context=0
  { [ -f "$root/CLAUDE.md" ] || [ -f "$root/.claude/CLAUDE.md" ]; } && has_context=1
  [ "$has_context" = 1 ] && [ "$has_checks" = 1 ] && exit 0
  if [ "$has_context" = 1 ]; then
    note="This repo has CLAUDE.md but no docs/agents/checks.json, so the Okeanos hooks have no commands to run. Before anything else, call the Skill tool with okeanos:onboard and do only its checks.json step."
  elif [ -f "$root/AGENTS.md" ]; then
    note="This repo has AGENTS.md but no CLAUDE.md. Before anything else, call the Skill tool with okeanos:onboard."
  else
    note="This repo has no CLAUDE.md. Before anything else, call the Skill tool with okeanos:onboard."
  fi
else
  has_context=0
  { [ -f "$root/AGENTS.md" ] || [ -f "$root/AGENTS.override.md" ]; } && has_context=1
  # Copilot also reads CLAUDE.md and .github/copilot-instructions.md as project instructions.
  if [ "$agent" = copilot ]; then
    { [ -f "$root/CLAUDE.md" ] || [ -f "$root/.claude/CLAUDE.md" ] || [ -f "$root/.github/copilot-instructions.md" ]; } && has_context=1
  fi
  [ "$has_context" = 1 ] && [ "$has_checks" = 1 ] && exit 0
  if [ "$has_context" = 1 ]; then
    note="This repo has AGENTS.md but no docs/agents/checks.json, so the Okeanos hooks have no commands to run. Before anything else, use the \`onboard\` skill and do only its checks.json step."
  elif [ -f "$root/CLAUDE.md" ]; then
    note="This repo has CLAUDE.md but no AGENTS.md, the context file this agent reads. Before anything else, use the \`onboard\` skill."
  else
    note="This repo has no AGENTS.md. Before anything else, use the \`onboard\` skill."
  fi
fi

msg="Okeanos: ${note} Then continue with the user's request."
if [ "$agent" = cursor ]; then
  printf '{"additional_context":"%s"}\n' "$msg"
elif [ "$agent" = copilot ]; then
  # Copilot's camelCase sessionStart reads a top-level additionalContext.
  printf '{"additionalContext":"%s"}\n' "$msg"
else
  printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$msg"
fi
