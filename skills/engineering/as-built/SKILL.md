---
name: as-built
description: Document what was actually built at the end of a flow - a per-feature doc with Mermaid diagrams, plus updates to the living architecture doc. Use after code-review and before publishing, or when the user asks to document, diagram, or explain the architecture of implemented work.
---

# As-built

Write the docs for what was **actually built**, from the code and the diff, not from the plan. The spec says what was intended; this says what exists. Two outputs, both Markdown with Mermaid, both committed with the code:

- **Feature doc**: `docs/features/<feature-slug>.md`, one per feature.
- **Architecture doc**: `docs/architecture.md`, the living overview of the whole system, updated in place.

Write in the language of the repo's existing docs. With no docs yet, use the language the user speaks in the session.

If the repo already keeps docs somewhere else (a docs site, `documentation/`, a different layout recorded in `CLAUDE.md`), follow that convention instead and keep the same two roles.

## 1. Gather the facts

- The diff since the branch point: `git diff $(git merge-base HEAD <base>)...HEAD`, where `<base>` is the branch the work was cut from.
- The spec and tickets under `.scratch/<feature>/`, if any, and the AFK report if the build ran AFK.
- ADRs written during the flow (`docs/adr/`) and `GLOSSARY.md`. Name everything in the glossary's vocabulary.
- The existing `docs/architecture.md`, if there is one.

Read the changed code itself, not just the diff, wherever a diagram needs to show how pieces connect. When the spec and the code disagree, the code wins, and the doc notes the deviation.

## 2. Pick the diagrams

Each diagram must answer a question a new reader would ask. Choose by what changed:

| Changed | Diagram |
| :- | :- |
| Always | `flowchart` of the modules involved and how they depend on each other. Mark new modules with `:::new` and changed ones with `:::changed`. |
| A flow crossing 3+ participants (request path, job, integration) | `sequenceDiagram` of the main path. Add the main failure path only if it is part of the behaviour. |
| Schema or persisted data | `erDiagram` of the touched entities and their relations. |
| An explicit state machine | `stateDiagram-v2`. |

Two or three diagrams is usually right. Keep each under ~15 nodes; split rather than cram. Label nodes with module or concept names, never file paths.

### Mermaid rules (GitHub renders these)

- Quote any label with spaces or punctuation: `A["Auth service"]`, `A -->|"on success"| B`.
- Node IDs are plain identifiers (`authService`), labels carry the readable name.
- Declare classes before use: `classDef new fill:#d4f7d4,stroke:#2e7d32` and `classDef changed fill:#fff4c2,stroke:#b8860b`.
- No HTML in labels except `<br/>`.
- If `mmdc` (mermaid-cli) is installed, render each diagram once to check it parses. Don't install it just for this.

## 3. Write the feature doc

`docs/features/<feature-slug>.md`:

```markdown
# <Feature name>

<Two or three sentences: what the user can do now that they couldn't before.>

**Status:** shipped on `<branch>` · **Spec:** <link or "none"> · **ADRs:** <links or "none">

## What was built

<User-facing behaviour, as a short list. Note any deviation from the spec and why.>

## How it works

<One short paragraph per diagram, then the diagram.>

## Modules

| Module | Responsibility | Change |
| :- | :- | :- |
| <name> | <one line> | new / changed |

## Data

<Schema changes and migrations, with the erDiagram. Omit the section if nothing persisted changed.>

## Testing

<Which seams are tested, where those tests live (directory level), and how to run them.>

## Limits and follow-ups

<Known gaps, out-of-scope items, and follow-up tickets.>
```

Omit any section that would be empty except **What was built** and **How it works**.

## 4. Update the architecture doc

`docs/architecture.md` is the map of the system. Its shape:

```markdown
# Architecture

<One paragraph: what the system is and its main parts.>

## System

<flowchart of the top-level components and how they connect, including external services.>

## Components

- **<Component>**: <one line>. Features: [<feature>](features/<slug>.md)

## Key flows

- [<Flow name>](features/<slug>.md#how-it-works): <one line>
```

- **It exists**: edit only what this feature changed. Add new components, update changed edges in the system diagram, link the new feature doc. Never rewrite unrelated parts.
- **It doesn't exist**: create it. Survey the top-level structure of the codebase (entry points, main modules, external services) to draw the system diagram, then add this feature on top. Keep the first version coarse; it gets sharper with each feature.

## 5. Bug fixes

Bug flows don't create a feature doc. If the fix changed behaviour that an existing feature doc or the architecture doc describes, update those docs. Otherwise do nothing.

## 6. Finish

Commit the docs on the work branch (`docs: as-built for <feature>`). In the G2 summary, link the feature doc and say what changed in the architecture doc.
