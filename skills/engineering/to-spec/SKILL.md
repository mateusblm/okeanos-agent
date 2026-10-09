---
name: to-spec
description: "Turn the current conversation into a spec and publish it to the project issue tracker: no interview, just synthesis of what you've already discussed."
---

This skill takes the current conversation context and codebase understanding and produces a spec. Do NOT interview the user; just synthesize what you already know.

The issue tracker and triage label vocabulary should have been provided to you. If not, use the `setup-okeanos` skill.

## Process

1. Explore the repo to understand the current state of the codebase, if you haven't already. Use the project's domain glossary vocabulary throughout the spec, and respect any ADRs in the area you're touching.

2. Sketch out the seams at which you're going to test the feature. Existing seams should be preferred to new ones. Use the highest seam possible. If new seams are needed, propose them at the highest point you can. The fewer seams across the codebase, the better - the ideal number is one.

Check with the user that these seams match their expectations.

3. If the change touches any of the security triggers listed under **Security** in the template, use the `threat-model` skill and fold its result into the spec.

4. Write the spec using the template below, then publish it to the project issue tracker. Apply the `ready-for-agent` triage label - no need for additional triage.

<spec-template>

## Problem Statement

The problem that the user is facing, from the user's perspective.

## Solution

The solution to the problem, from the user's perspective.

## User Stories

A LONG, numbered list of user stories. Each user story should be in the format of:

1. As an <actor>, I want a <feature>, so that <benefit>

<user-story-example>
1. As a mobile bank customer, I want to see balance on my accounts, so that I can make better informed decisions about my spending
</user-story-example>

This list of user stories should be extremely extensive and cover all aspects of the feature.

## Acceptance Criteria

Testable criteria in EARS notation, grouped by user story number. Each criterion becomes at least one test.

- Ubiquitous: `The <system> shall <response>.`
- Event-driven: `When <trigger>, the <system> shall <response>.`
- State-driven: `While <state>, the <system> shall <response>.`
- Optional feature: `Where <feature is included>, the <system> shall <response>.`
- Unwanted behaviour: `If <unwanted condition>, then the <system> shall <response>.`

Every user story gets at least one **If ... then** criterion: invalid input, failure of a dependency, missing permission, empty state. That one pattern is what forces the error paths into the open before code exists. Write them in the user's language (for Portuguese: `Quando ..., o sistema deve ...`, `Se ..., então o sistema deve ...`).

## Security

Only when the change touches authentication or authorization, external input, persisted or personal data, secrets, network calls to third parties, or LLM calls: the threat model from the `threat-model` skill (at most 15 lines). Each mitigation also appears as an **If ... then** acceptance criterion. Omit the section otherwise.

## Non-Functional Checks

Only the lines that apply; omit the section when none does. Each one becomes an acceptance criterion or a G2 checklist item.

- **Service or API**: which new failures are logged or counted, which external calls get a timeout, and the SLI that would show this feature broken in production (e.g. "share of `POST /calc` answered 2xx in under 300 ms").
- **UI**: accessibility (every control has a label, works by keyboard, contrast passes WCAG AA) and the performance budget (bundle size growth, largest contentful paint) if the project has one.
- **Data**: migration plan (expand → migrate → contract), and whether it's reversible.

## Implementation Decisions

A list of implementation decisions that were made. This can include:

- The modules that will be built/modified
- The interfaces of those modules that will be modified
- Technical clarifications from the developer
- Architectural decisions
- Schema changes
- API contracts
- Specific interactions

Do NOT include specific file paths or code snippets. They may end up being outdated very quickly.

Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline it within the relevant decision and note briefly that it came from a prototype. Trim to the decision-rich parts, not a working demo, just the important bits.

## Testing Decisions

A list of testing decisions that were made. Include:

- A description of what makes a good test (only test external behavior, not implementation details)
- Which modules will be tested
- Prior art for the tests (i.e. similar types of tests in the codebase)

## Out of Scope

A description of the things that are out of scope for this spec.

## Further Notes

Any further notes about the feature.

## Open Questions

Anything the conversation didn't settle, each marked `[NEEDS CLARIFICATION: <question>]` (in Portuguese, `[PRECISA ESCLARECER: <pergunta>]`). Use the same marker inline wherever a requirement depends on the answer. Never guess to fill a gap: a marked question is cheap now, a wrong guess is expensive after the build. The spec can't pass the G1 pre-check while a marker is open.

</spec-template>
