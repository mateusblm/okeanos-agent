# TASK

Write the acceptance tests for ticket {{TICKET_ID}}. Do not implement anything.

<ticket>

{{TICKET_BODY}}

</ticket>

<spec>

{{SPEC}}

</spec>

# RULES

- One or more tests per acceptance criterion of the ticket (the EARS lines: "When ... shall ...", "If ... then ..."). Name each test after the criterion it proves.
- Test only through the public interfaces the spec names (its seams and implementation decisions). Never invent an internal function to call; if the spec doesn't name the interface a criterion needs, skip that criterion and list it in your final message.
- Expected values come from the spec, never from reading or guessing the implementation.
- Follow the repo's test conventions: read `CLAUDE.md`, the test runner config and two existing tests first. Put the tests where the repo keeps tests.
- These tests are expected to fail now, because the behaviour isn't built yet. That's fine. They must still compile or load: no syntax errors, imports pointing at the interfaces the spec names.
- Change nothing outside test files. Do not edit `.scratch/` or `.sandcastle/`.

Commit the tests (`test: acceptance tests for ticket {{TICKET_ID}}`), then output <promise>COMPLETE</promise>.
