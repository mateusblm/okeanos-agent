---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
metadata:
  credits:
    skill: incremental-implementation, source-driven-development
    author: Addy Osmani
    url: "https://github.com/addyosmani/agent-skills"
---

Implement the work described by the user in the spec or tickets.

If the user passes a ticket reference, fetch it from the issue tracker and state its title before starting. If the reference is ambiguous, ask.

Use the `tdd` skill where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end. Don't rerun a check that passed on code that hasn't changed since.

Deliver in slices:

- Each slice is one vertical behaviour (a thin path through every layer it needs), not a layer. Riskiest slice first when one is uncertain.
- After each slice the project compiles and the existing tests pass. Then commit it, one commit per slice, with a message that says why. A refactor gets its own commit, apart from the behaviour.
- Never leave the branch broken between slices.

Touch only what the ticket needs. When you notice something outside its scope (a bug, a smell, a missing test, an outdated doc), don't fix it: add it to a **notei, não mexi** list, one line each with the file. Show the list in the publish gate summary, so the user decides what becomes a ticket.

Before using a framework or library API, read its version in the manifest or lockfile and check the official docs for that version. Cite the page when the choice isn't obvious. If you couldn't check, say so to the user and mark it unverified. When the docs and the existing code disagree, ask.

When the change touches production UI (components, screens, styles), use the `frontend-ui` skill while building it.

Before review, when the change is visible to a user (UI, HTTP API, CLI output), run the application and exercise the changed path once:

- If `docs/agents/verificar.md` exists, follow it: start the app as **Subir** says, run **Checar** until it is ready, exercise the changed path the way **Exercitar** does (the changed path, not only the main one), capture what **Evidência** asks for, then run **Limpar** and confirm the evidence survived it. Attach that evidence to the publish gate summary. When a step marked `(não verificado)` works, remove the mark; when a step is wrong, fix the file and tell the user.
- Otherwise use the `run` skill if it is available, or start the app with the commands in `CLAUDE.md` or `AGENTS.md`, and keep the evidence (command and output, health check, or before/after screenshots for UI) for the publish gate. Then offer the user, once, to create the script with the `onboard` skill (only its `verificar.md` step).

Tests passing is not the same as the feature working. For UI changes, also check accessibility on the changed screen: run axe (via Playwright or the browser tools) when available, otherwise check by hand that every control has a label and works by keyboard.

Once done, use the `code-review` skill to review the work.

Commit your work to the current branch.
