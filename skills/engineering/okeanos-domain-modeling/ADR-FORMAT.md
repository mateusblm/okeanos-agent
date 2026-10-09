# ADR Format

ADRs live in `docs/adr/` and use sequential numbering: `0001-slug.md`, `0002-slug.md`, etc.

Create the `docs/adr/` directory lazily: only when the first ADR is needed.

## Template

```md
# {Short title of the decision}

{1-3 sentences: what's the context, what did we decide, and why.}

## Confirmation

{How compliance with this decision is checked automatically: the lint rule, architecture test, CI check or type constraint that fails when someone breaks it. Or, when no automatic check is possible: "Manual: <what the reviewer checks>".}
```

That's it. An ADR can be a paragraph plus its Confirmation. The value is in recording *that* a decision was made, *why*, and *how breaking it gets caught*.

**Confirmation is mandatory.** A decision nobody checks erodes quietly, and agents are the fastest way to erode it: they follow the code in front of them, not the ADR they never opened. Turning the decision into a check (an architecture fitness function) makes it something an agent runs into instead of something it has to remember. Examples:

- "Ordering never imports from Billing" → an import-boundary lint rule (`eslint-plugin-boundaries`, `import-linter`, ArchUnit) or a test that scans imports.
- "All money is integer cents" → a type (`Cents`) plus a lint rule banning floats in the money module.
- "No synchronous HTTP between contexts" → a test that the HTTP client is only imported by adapters.

When the check doesn't exist yet, creating it is part of the work: add a ticket for it under `.scratch/<feature>/issues/` (or the configured tracker), blocked by nothing, so it lands with the feature. When it exists, add its command to `docs/agents/checks.json` `onDone` if it's fast, so the Okeanos hooks enforce it on every change.

## Optional sections

Only include these when they add genuine value. Most ADRs won't need them.

- **Status** frontmatter (`proposed | accepted | deprecated | superseded by ADR-NNNN`): useful when decisions are revisited
- **Considered Options**: only when the rejected alternatives are worth remembering
- **Consequences**: only when non-obvious downstream effects need to be called out

## Numbering

Scan `docs/adr/` for the highest existing number and increment by one.

## When to offer an ADR

All three of these must be true:

1. **Hard to reverse**: the cost of changing your mind later is meaningful
2. **Surprising without context**: a future reader will look at the code and wonder "why on earth did they do it this way?"
3. **The result of a real trade-off**: there were genuine alternatives and you picked one for specific reasons

If a decision is easy to reverse, skip it: you'll just reverse it. If it's not surprising, nobody will wonder why. If there was no real alternative, there's nothing to record beyond "we did the obvious thing."

### What qualifies

- **Architectural shape.** "We're using a monorepo." "The write model is event-sourced, the read model is projected into Postgres."
- **Integration patterns between contexts.** "Ordering and Billing communicate via domain events, not synchronous HTTP."
- **Technology choices that carry lock-in.** Database, message bus, auth provider, deployment target. Not every library: just the ones that would take a quarter to swap out.
- **Boundary and scope decisions.** "Customer data is owned by the Customer context; other contexts reference it by ID only." The explicit no-s are as valuable as the yes-s.
- **Deliberate deviations from the obvious path.** "We're using manual SQL instead of an ORM because X." Anything where a reasonable reader would assume the opposite. These stop the next engineer from "fixing" something that was deliberate.
- **Constraints not visible in the code.** "We can't use AWS because of compliance requirements." "Response times must be under 200ms because of the partner API contract."
- **Rejected alternatives when the rejection is non-obvious.** If you considered GraphQL and picked REST for subtle reasons, record it; otherwise someone will suggest GraphQL again in six months.
