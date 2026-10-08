---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
---

Implement the work described by the user in the spec or tickets.

If the user passes a ticket reference, fetch it from the issue tracker and state its title before starting. If the reference is ambiguous, ask.

Use the `tdd` skill where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

Before review, when the change is visible to a user (UI, HTTP API, CLI output), run the application and exercise the changed path once: use the `run` skill if it is available, otherwise start the app with the commands in `CLAUDE.md` or `AGENTS.md`. Keep the evidence (command and output, health check, or before/after screenshots for UI) for the publish gate. Tests passing is not the same as the feature working. For UI changes, also check accessibility on the changed screen: run axe (via Playwright or the browser tools) when available, otherwise check by hand that every control has a label and works by keyboard.

Once done, use the `code-review` skill to review the work.

Commit your work to the current branch.
