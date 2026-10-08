"""Skills must read the same in Claude Code, Codex, GitHub Copilot and Cursor.

Claude Code-only tool names may appear only on a line that starts with
"In Claude Code:", which marks a note that is genuinely about Claude Code.
"""

import re
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent / "skills"

FORBIDDEN = {
    "Skill tool": re.compile(r"Skill tool"),
    "Agent tool": re.compile(r"Agent tool"),
    "Task tool": re.compile(r"Task tool"),
    "AskUserQuestion": re.compile(r"AskUserQuestion"),
    "TodoWrite": re.compile(r"TodoWrite"),
    "CLAUDE_PLUGIN_ROOT": re.compile(r"CLAUDE_PLUGIN_ROOT"),
    "/clear": re.compile(r"(?<![\w./-])/clear\b"),
    "/compact": re.compile(r"(?<![\w./-])/compact\b"),
}

CLAUDE_NOTE = re.compile(r"^\s*(?:[-*>|]\s*)*\**In Claude Code:")


def skill_files():
    return sorted(p for p in SKILLS.rglob("*") if p.is_file() and "node_modules" not in p.parts)


def test_skills_use_no_claude_only_tool_names():
    violations = []
    for path in skill_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if CLAUDE_NOTE.match(line):
                continue
            for name, pattern in FORBIDDEN.items():
                if pattern.search(line):
                    violations.append(f"{path.relative_to(SKILLS.parent)}:{lineno}: {name}")
    assert not violations, "Claude Code-only names outside an 'In Claude Code:' line:\n" + "\n".join(violations)


def frontmatter(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0].strip() == "---", f"{path} has no frontmatter"
    fields = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if match:
            fields[match.group(1)] = match.group(2).strip()
    raise AssertionError(f"{path} frontmatter is not closed")


SKILL_MDS = sorted(SKILLS.rglob("SKILL.md"))


def test_skills_exist():
    assert SKILL_MDS


@pytest.mark.parametrize("path", SKILL_MDS, ids=lambda p: p.parent.name)
def test_skill_has_name_and_description(path):
    fields = frontmatter(path)
    assert fields.get("name"), f"{path} has no name"
    assert fields.get("description"), f"{path} has no description"
    assert fields["name"] == path.parent.name
