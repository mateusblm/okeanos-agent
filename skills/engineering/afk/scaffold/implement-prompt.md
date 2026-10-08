# TASK

Implement ticket {{TICKET_ID}}: {{TICKET_TITLE}}

You are on branch `{{SOURCE_BRANCH}}`, created from `{{TARGET_BRANCH}}`. Only work on this ticket.

<ticket>

{{TICKET_BODY}}

</ticket>

The ticket belongs to this spec. Use it for context and vocabulary only; do not implement other parts of it.

<spec>

{{SPEC}}

</spec>

# CONTEXT

Recent commits:

!`git log -n 10 --format="%h %ad %s" --date=short`

Read `CLAUDE.md` or `AGENTS.md`, `GLOSSARY.md`, and any ADRs under `docs/adr/` if they exist. Follow the repo's conventions.

# EXECUTION

0. Run `{{VERIFY_COMMAND}}` before changing anything. If it already fails on this untouched branch, commit nothing and explain in your final message that the baseline is red: building on a red baseline hides your own failures.
1. Explore the code the ticket touches, especially existing tests near it. Search for code that already does part of the job (helpers, utilities, similar features) and reuse it instead of writing a second version.
2. Call the Skill tool with "tdd" and build the ticket one red-green slice at a time against its acceptance criteria.
3. Run `{{VERIFY_COMMAND}}` and fix every failure.
4. Commit after each red and each green, with messages that name the ticket ({{TICKET_ID}}). The commit history is the progress log for whoever picks this up next.

Rules:

- Do not edit anything under `.scratch/` or `.sandcastle/`. Ticket state is managed outside the sandbox.
- If the ticket is impossible as written (contradicts the code, missing a decision), commit nothing and explain why in your final message.

When every acceptance criterion is met, tests pass, and the work is committed, output <promise>COMPLETE</promise>.
