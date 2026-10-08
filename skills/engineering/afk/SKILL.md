---
name: afk
description: Implement a feature's local tickets away-from-keyboard, in parallel Docker sandboxes (Sandcastle), then hand back for review. Use after tickets are approved, when the user chooses AFK execution over implementing in the session.
---

# AFK

Run a feature's approved tickets (`.scratch/<feature>/issues/`) in isolated Docker sandboxes while the user is away. Each ready ticket gets its own branch and sandbox, an implementer that drives `tdd`, and a reviewer. Finished branches merge into the integration branch, tickets are marked done, and a report comes back.

The runner is [scaffold/main.mts](scaffold/main.mts), built on Sandcastle (`@ai-hero/sandcastle`). It works out the ready tickets straight from the ticket files (`**Status:**` and `**Blocked by:**` lines), so the ticket format from `to-tickets` must hold.

## Preconditions

- The tickets were approved at G1. This skill never decides on its own to go AFK.
- `docker info` succeeds. If it doesn't, stop and tell the user.
- The current branch is the integration branch, not the default branch. If you're on the default branch, create `okeanos/<feature>` and switch to it.
- The working tree is clean. Commit the spec and tickets first if they are tracked.

## 1. Set up the repo (once per repo)

Skip this step if `.sandcastle/main.mts` already exists.

1. Copy every file in this skill's `scaffold/` folder into `<repo>/.sandcastle/`. Rename `gitignore` to `.gitignore` and `env.example` to `.env.example`.
2. Copy the `tdd` and `codebase-design` skill folders (siblings of this skill's folder) into `.sandcastle/skills/`. The sandbox mounts them as the agent's skills. The folder is gitignored, so re-copy it when it is missing.
3. Fill in the configuration block at the top of `.sandcastle/main.mts` from what the repo actually uses. Set `HIDDEN_ACCEPTANCE = true` when the user wants it for a critical feature: a separate agent then writes each ticket's acceptance tests from the criteria alone, kept outside the repo until the implementer and reviewer finish, and the ticket only merges if they pass. It doubles agent runs per ticket and needs a spec that names the interfaces to test. The rest of the block: `INSTALL_COMMAND` (lockfile tells the package manager), `VERIFY_COMMAND` (typecheck plus tests, from `package.json` scripts, `Makefile`, CI config), `COPY_TO_WORKTREE` (e.g. `node_modules` to speed up installs).
4. If the project needs runtimes beyond Node (Python, Go, a database client), add them to `.sandcastle/Dockerfile` at the `OKEANOS:` marker.
5. Write `.sandcastle/CODING_STANDARDS.md` from the repo's real conventions: `CLAUDE.md`, linters, existing code. Keep it short and specific.
6. Install the runner: `npm install --prefix .sandcastle`.
7. Build the image: `.sandcastle/node_modules/.bin/sandcastle docker build-image`.
8. The token is a human step. Tell the user to run `claude setup-token` and paste the result as `CLAUDE_CODE_OAUTH_TOKEN` in `.sandcastle/.env` (copy it from `.sandcastle/.env.example`). Never read, print, or write the token yourself. Wait until they confirm.

Show the user the filled configuration block and the Dockerfile changes before the first run.

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

- **Failed tickets**: inspect the branch (`okeanos/afk-<feature>-<NN>`) and the logs. Fix them in the session (Skill tool with "implement" for that ticket) or re-run AFK after fixing the cause.
- **All done**: call the Skill tool with "code-review" on the integration branch against the base it was cut from, then call the Skill tool with "as-built". Then G2 as usual.

Clean up the per-ticket branches that were merged (`git branch -d okeanos/afk-<feature>-*`).
