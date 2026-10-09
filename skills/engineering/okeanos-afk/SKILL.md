---
name: okeanos-afk
description: Implement a feature's local tickets away-from-keyboard, in parallel Docker sandboxes (Sandcastle), then hand back for review. Use after tickets are approved, when the user chooses AFK execution over implementing in the session.
---

# AFK

Run a feature's approved tickets (`.scratch/<feature>/issues/`) in isolated Docker sandboxes while the user is away. Each ready ticket gets its own branch and sandbox, an implementer that drives `okeanos-tdd`, and a reviewer. Finished branches merge into the integration branch, tickets are marked done, and a report comes back.

The runner is [scaffold/main.mts](scaffold/main.mts), built on Sandcastle (`@ai-hero/sandcastle`). It works out the ready tickets straight from the ticket files (`**Status:**` and `**Blocked by:**` lines), so the ticket format from `okeanos-tickets` must hold.

## Preconditions

- The tickets were approved at G1. This skill never decides on its own to go AFK.
- `docker info` succeeds. If it doesn't, stop and tell the user.
- The current branch is the integration branch, not the default branch. If you're on the default branch, create `okeanos/<feature>` and switch to it.
- The working tree is clean. Commit the spec and tickets first if they are tracked.

## 1. Set up the repo (once per repo)

Skip this step if `.sandcastle/main.mts` already exists.

1. Ask the user which agent runs in the sandboxes: Claude Code (default), Codex, GitHub Copilot or Cursor. The runner supports only these four; anything else fails at startup with the list.
2. Copy every file in this skill's `scaffold/` folder into `<repo>/.sandcastle/`. Rename `gitignore` to `.gitignore` and `env.example` to `.env.example`.
3. Copy the `okeanos-tdd`, `okeanos-codebase-design` and `okeanos-frontend-ui` skill folders (siblings of this skill's folder) into `.sandcastle/skills/`. The sandbox mounts them where the chosen agent reads user skills (`~/.claude/skills` for Claude Code, `~/.agents/skills` for the others). The folder is gitignored, so re-copy it when it is missing.
4. Fill in the configuration block at the top of `.sandcastle/main.mts` from what the repo actually uses. Set `AGENT` to `"claude"`, `"codex"`, `"copilot"` or `"cursor"`, and adjust that agent's row in `MODELS` if the user wants other models. Set `HIDDEN_ACCEPTANCE = true` when the user wants it for a critical feature: a separate agent then writes each ticket's acceptance tests from the criteria alone, kept outside the repo until the implementer and reviewer finish, and the ticket only merges if they pass. It doubles agent runs per ticket and needs a spec that names the interfaces to test. The rest of the block: `INSTALL_COMMAND` (lockfile tells the package manager), `VERIFY_COMMAND` (typecheck plus tests, from `package.json` scripts, `Makefile`, CI config), `COPY_TO_WORKTREE` (e.g. `node_modules` to speed up installs).
5. In `.sandcastle/Dockerfile`, keep the install block of the chosen agent at the `OKEANOS: agent CLI` marker: for anything other than Claude Code, uncomment that agent's line and comment out the Claude Code one. If the project needs runtimes beyond Node (Python, Go, a database client), add them at the `OKEANOS: project runtimes` marker.
6. Write `.sandcastle/CODING_STANDARDS.md` from the repo's real conventions: `CLAUDE.md` or `AGENTS.md`, linters, existing code. Keep it short and specific.
7. Install the runner: `npm install --prefix .sandcastle`.
8. Build the image: `.sandcastle/node_modules/.bin/sandcastle docker build-image`.
9. The token is a human step. Tell the user to copy `.sandcastle/.env.example` to `.sandcastle/.env` and paste the chosen agent's entry themselves:
   - Claude Code: run `claude setup-token` and paste it as `CLAUDE_CODE_OAUTH_TOKEN` (or set `ANTHROPIC_API_KEY`).
   - Codex: `OPENAI_API_KEY`.
   - GitHub Copilot: `GITHUB_TOKEN` (or `COPILOT_GITHUB_TOKEN`), a token with the "Copilot Requests" permission.
   - Cursor: `CURSOR_API_KEY`.

   Never read, print, or write the token or key yourself, not even to check it is set. Wait until they confirm.

Show the user the filled configuration block (with `AGENT`) and the Dockerfile changes before the first run.

## 2. Pilot, then launch

Every AFK run starts with a pilot, in the background from the repo root:

```bash
.sandcastle/node_modules/.bin/tsx .sandcastle/main.mts <feature-slug> --pilot
```

It runs one round on at most two ready tickets. When it ends, read `.scratch/<feature>/afk-report.md` and the merged diff:

- **Both done, tests green, diff sizes sane**: launch the full run yourself, without waiting for the user (they chose AFK):

  ```bash
  .sandcastle/node_modules/.bin/tsx .sandcastle/main.mts <feature-slug>
  ```

- **Anything failed** (baseline red, install broken, verify command wrong, tickets misunderstood): stop. Fix the setup or the tickets, or bring it to the user. A broken setup caught on two tickets costs minutes; caught on twenty, it costs the afternoon.

Tell the user it is running, how many tickets are ready, and that they can leave. Logs go to `.sandcastle/logs/`.

## 3. Hand back

When the run ends, read `.scratch/<feature>/afk-report.md` and summarize it in one short block: done, failed (with reason), still open.

- **Failed tickets**: inspect the branch (`okeanos/afk-<feature>-<NN>`) and the logs. Fix them in the session (use the `okeanos-implement` skill for that ticket) or re-run AFK after fixing the cause.
- **All done**: use the `okeanos-code-review` skill on the integration branch against the base it was cut from, then offer the `okeanos-as-built` docs and use that skill only if the user wants them. Then G2 as usual.

Clean up the per-ticket branches that were merged (`git branch -d okeanos/afk-<feature>-*`).
