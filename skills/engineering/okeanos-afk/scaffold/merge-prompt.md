# TASK

Merge these branches into the current branch (`{{TARGET_BRANCH}}`), one at a time:

{{BRANCHES}}

For each branch:

1. `git merge <branch> --no-edit`
2. Resolve conflicts by reading both sides and keeping the behaviour each branch intended.
3. Run `{{VERIFY_COMMAND}}`. Fix failures before moving on, and commit the fixes.

If a branch cannot be merged without breaking the build, run `git merge --abort` (or reset to the commit before that merge) and skip it. A skipped branch must not end up merged.

Do not edit `.scratch/` or `.sandcastle/`; ticket state is updated outside the sandbox.

Output <promise>COMPLETE</promise> when done.
