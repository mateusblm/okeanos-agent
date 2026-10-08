# TASK

Review branch `{{SOURCE_BRANCH}}` against `{{TARGET_BRANCH}}` and improve it without changing behaviour.

<ticket>

{{TICKET_BODY}}

</ticket>

## Diff

!`git diff {{TARGET_BRANCH}}...HEAD`

# REVIEW

1. **Spec**: does the diff deliver every acceptance criterion of the ticket, and nothing beyond it? Note gaps; fix small ones.
2. **Standards**: follow @.sandcastle/CODING_STANDARDS.md and the repo's own conventions.
3. **Tests**: new behaviour is covered through public interfaces, not implementation details.
4. **Safety**: no injection, credential leaks, unsafe casts, or unchecked assumptions.
5. **Clarity**: remove needless complexity, dead code, and comments that restate the code. Prefer explicit over clever.

# EXECUTION

If you change anything, run `{{VERIFY_COMMAND}}`, fix failures, and commit the refinements. If the branch is already good, change nothing. Do not edit `.scratch/` or `.sandcastle/`.

Output <promise>COMPLETE</promise> when finished.
