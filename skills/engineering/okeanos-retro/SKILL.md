---
name: okeanos-retro
description: "Conduct a retrospective on a coding session."
metadata:
  credits:
    skill: correct
    author: Lauren Tan
    url: "https://github.com/cursor/plugins/tree/main/pstack/skills/correct"
---

The user has asked for a **retrospective**. You are suggesting improvements to the coding agent's **environment** to improve future runs.

## Steps

1. Use the `okeanos-writing-for-agents` skill for the writing style guide.

2. Read the primary sources for the session the user specifies. This may mean searching through session logs on this machine. If the user doesn't specify a session, default to the current one.

   Then read the measurements, not impressions. Developers in a 2025 RCT believed AI made them about 20% faster when it made them 19% slower; a retro built on how the session felt repeats that error. The Okeanos hooks log every gate event as one JSON per line (`ts`, `agent`, `session`, `branch`, `kind`, `detail`) to `$(git rev-parse --git-common-dir)/okeanos/metrics.jsonl`, or, when the git dir is read-only (a sandboxed agent), to the fallback `<TMPDIR>/okeanos/<hash>/metrics.jsonl`. Run `okeanos metrics <days>` (for example `okeanos metrics 7`) to count events by `kind` and by agent across both files; its header names the files it read, so open those for `detail` and `session`. The fallback lives under TMPDIR, which the system may wipe on reboot: if the counts look short, say so instead of reading the gap as a quiet period. Summarize the period under review by `kind`:

   - `stop:block` / `stop:escalate`: the definition of done failed (which command, how often, whether it reached the user).
   - `stop:tamper` / `stop:suppression`: tests loosened, lint or type checks silenced.
   - `stop:size`: sessions that went over the line budget.
   - `pre-bash:deny` / `pre-bash:ask`, `pre-edit:ask`: dangerous commands, unknown packages, edits to committed tests.
   - `post-edit:fail`: per-edit lint and format failures.

   Add what git shows: reverts, fix-up commits on the same lines, and CI failures if the repo has CI. A kind that repeats is the strongest candidate for a finding.

   Read `docs/agents/regras.md` if it exists. A rule enforced by "nada" that the session or the log shows violated again is a finding.

3. Look for candidates for improvement in these categories.

- **Navigation**: how easy was it for the agent to find the right files? Are there hidden dependencies between files? Would a **navigation pointer** make it easier? _Use when_ the session took a long time to find a piece of information.
- **Automated checks**: are there automated checks that could catch errors the agent made? Linting, typing, tests, filesystem linters? Read the repo's own check command first (its `package.json`/build-tool `lint`/`check` scripts, its CI workflow), so a check that already exists but sits unwired or silently broken is the finding, not a reinvention. A repo with no **guardrail** (no pre-commit hook and no CI job running its lint/typecheck/test command) is itself a finding: an un-linted repo is a standing missed opportunity, not a neutral default. _Use when_ the agent made a mistake an automated check could have caught, or the repo has no guardrail at all.
- **Coding standards**: should the **reviewer agent** be given a new rule to enforce? Should an existing rule be removed or clarified? Classify the violation first: a **mechanical** one (a fixed syntactic pattern, a banned API, an import shape, a file-location rule) gets a deterministic check, full stop: a custom rule in the repo's own linter, a new pre-commit hook, or a new CI job, whichever the repo's language and existing guardrail make cheapest. Default to building the check over writing the rule. Reserve `CODING_STANDARDS.md` for genuine **judgement calls** (cross-file consistency, "matches the surrounding style," anything no guardrail could ever substitute for). _Use when_ the reviewer agent failed to catch a mistake.
- **Global AGENTS.md**: are there any steering instructions that should be moved to coding standards (or automated checks) instead? _Use when_ the AGENTS.md file is particularly large - in the repo OR the user's global scope.
- **Tool economy**: did the agent make expensive tool calls that could be streamlined? Is there any custom tooling (CLI's, MCP's) that is particularly token-inefficient? _Use when_ the agent made an expensive tool call.
- **No-ops**: look for instructions in steering files that don't modify the agent's behavior. _Use when_ the steering files are large and unwieldy.
- **Information access**: look for opportunities to increase the agent's access to information. Teeing dev server logs, readonly access to third-party services. _Use when_ a crucial piece of information was not available to the agent.

4. Present these candidates to the user, in order of severity, with the measurement behind each one.

5. End with **one to three system changes** the user can approve: a hook or check, a rule in `CODING_STANDARDS.md` or `CLAUDE.md`, a skill edit, a new `checks.json` command. Never "be more careful" or "remember to ...": a lesson that lives only in a promise is lost by the next session.

   Place each change on the **ladder**, strongest rung first, and pick the highest one you can afford:

   1. **Architecture**: make the error impossible. One owner per piece of state, one supported way per task, internals hidden so the wrong import fails, one source of truth instead of hand-synced lists, old ways deleted so nobody copies them.
   2. **Types**: the bad state can't be written.
   3. **Lint rule or check** (a linter rule, a githook, or a command in `docs/agents/checks.json`) whose message says the fix: the file, type, or function to use instead. If the pattern is already common, fail only when a change adds more.
   4. **Test** of the behavior, one that would fail if the functions it calls returned nothing.
   5. **Docs** or an agent rule, only for judgment calls. Nothing fails when an agent skips them.

   For each change, say why the rungs above it were not chosen (too costly, not expressible in this language, needs judgment).

   **Prove each new check.** Find the real past error it targets: a commit, a revert, or an event in `okeanos metrics`/`metrics.jsonl`. Run the check against that state (for example in a temporary worktree at the commit) and paste the failure output. If there is no real past error to run it against, say so explicitly; never present an unproven check as proven.

   Apply the approved changes, and update the rule table (step 6) in the same change.

6. **Keep `docs/agents/regras.md`**, the table of the project's rules and what enforces each one. If it doesn't exist, propose it with the rules you found (in `CLAUDE.md`/`AGENTS.md`, `CODING_STANDARDS.md`, `checks.json`, the hooks) and create it once the user approves. Add or update a row with every change; drop a row once its error can't happen.

   ```markdown
   # Regras

   | Regra | O que a aplica |
   | :- | :- |
   | Não editar testes commitados para passar | hook (pre-edit) |
   | Dinheiro só via `Money`, nunca `float` | tipo (`Money`) |
   | Toda rota nova tem teste de contrato | teste (`tests/test_routes.py`) |
   | Nomes de domínio seguem o GLOSSARY | nada (julgamento, review) |
   ```

   The second column is one of: hook, check (its name in `checks.json`), lint, tipo, teste, or nada.

## Reference

### Implementation vs Review

Remember that all work goes through two stages: implementation and review. The implementation agent has the most **context pressure**. They are responsible for exploration, writing code, and debugging failures.

The review agent has the least context pressure - it receives a diff, so no exploration needed. It often does not need to write code or debug.

This means that the review agent should be responsible for imposing coding standards, not the implementation agent.

### Files

You have access to several files in the repo:

- `CLAUDE.md`/`AGENTS.md`: these files are pushed to the context window of any agent working in this repo. They should be used incredibly sparingly, usually only for **navigation pointers** to other files.
- `CODING_STANDARDS.md`: this file is read during review, not implementation. Add **navigation pointers** to docs folders if the standards file gets more than 1,000 lines long.
- Docs: use docs as references files, pointed to by other files. Look for existing docs before writing new ones.
- Skills: use skills for docs (since their description goes into the agent's context window), or for user-invoked commands. Follow the advice in the `okeanos-writing-for-agents` skill.
