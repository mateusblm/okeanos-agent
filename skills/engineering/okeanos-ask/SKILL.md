---
name: okeanos-ask
description: Ask which skill or flow fits your situation. A router over the Okeanos skills and routes.
disable-model-invocation: true
---

# Ask Okeanos

You don't remember every skill, so ask.

Before stating what a skill does or recommending a step be skipped, read that skill's SKILL.md: the summaries here are for orientation only.

A **flow** is a path through the skills. Most paths run along one **main flow**, and two **on-ramps** merge onto it. Everything else is standalone, or a vocabulary layer that runs underneath.

## The main flow: idea → ship

The route most work travels. You have an idea and want it built.

1. **`/okeanos-grill-with-docs`** sharpens the idea by interview. Start here whenever you are **working in a working directory**: it's stateful, retaining what it learns in `GLOSSARY.md` and ADRs. (No working directory? Use `/okeanos-grill` instead, covered under Standalone; `okeanos-grill-with-docs` runs the same interview and leaves a paper trail.)
2. **Branch: can you settle every question in conversation?** If a question needs a runnable answer (state, business logic, a UI you have to see), detour through a prototype, bridged by a **handoff** file in both directions (a prototype lives in its own directory; see Phase boundaries):
   - write a handoff out, then open a fresh session against that file,
   - **`/okeanos-prototype`** to answer the question with throwaway code,
   - hand back what you learned, and reference it from the original idea thread.
3. **Branch: is this a multi-session build?**
   - **Yes** → **`/okeanos-spec`** (turn the thread into a spec), then **`/okeanos-tickets`** to split it into tracer-bullet tickets, each declaring its **blocking edges**. Then work the tickets one of two ways:
     - **`/okeanos-implement`** per ticket, **starting a fresh context between each one**. On a local tracker that's one file per ticket under `.scratch/<feature>/issues/`, worked blockers-first by hand; on a real tracker the edges become native blocking links, so any ticket whose blockers are done can be grabbed. Each ticket is self-contained, so the last one's context is disposable.
     - **`/okeanos-implement-spec`** for the whole spec in one run. It reads the tickets as a **task graph**, runs implementer subagents across the ready **frontier** in parallel, and lands everything on one **integration branch**. Reach for it when you'd rather orchestrate the build than drive each ticket yourself.
     - **`/okeanos-afk`** runs the same tickets away-from-keyboard: one Docker sandbox and branch per ready ticket, an implementer driving `/okeanos-tdd`, a reviewer, then a merge into the integration branch. Reach for it when you want to walk away while the build runs. It hands back a report; `/okeanos-code-review` and the publish gate follow as usual.
   - **No** → **`/okeanos-implement`** right here, in the same context window.

   Either way, the code gets built by driving **`/okeanos-tdd`** (one red-green slice at a time) and closes out with **`/okeanos-code-review`**, a two-axis review (Standards + Spec) of the diff. `/okeanos-implement` runs both per ticket; `/okeanos-implement-spec`'s implementers each drive `/okeanos-tdd`, and it runs one `/okeanos-code-review` over the integration branch. Reach for **`/okeanos-tdd`** on its own when you just want to build a concrete behaviour test-first without a full spec, and **`/okeanos-code-review`** on its own whenever you want to review a branch or PR against a fixed point.

   Before it ships, **`/okeanos-as-built`** documents what was actually built: a per-feature doc with Mermaid diagrams (modules, main flow, data), and an update to the living `docs/architecture.md`. It reads the code and diff, not the plan, so the docs match what exists. It costs a lot of tokens, so it's offered with a recommendation and runs only when you say yes.

   When the work goes up as a pull request, **`/okeanos-pr`** shapes the body: the smallest visual that shows the change, before/after evidence that it works, and a one-way or two-way door call. It's model-invoked, so the agent reaches for it whenever it writes a PR.

4. **`/okeanos-retro`** closes the loop. After a build, and especially one that went sideways, it looks back over the session and suggests changes to the agent's **environment**, not the code: navigation pointers, automated checks, the coding standards `/okeanos-code-review` enforces, steering files, tooling. Mechanical mistakes become deterministic checks; judgement calls become coding standards. The next build then starts from a better environment.

### Context hygiene

Keep steps 1–3 in **one unbroken context window** (don't compact or clear until after `/okeanos-tickets`) so the grilling, spec, and tickets all build on the same thinking. Each `/okeanos-implement` then starts fresh, working from the ticket. Run `/okeanos-retro` in the session it's looking back on, before you clear; after clearing, point it at that session's log instead.

The limit on this is the **smart zone**: the window (~150k tokens on state-of-the-art models) within which the model still reasons sharply. If a session approaches it before `/okeanos-tickets`, don't push on degraded; compact the context at the nearest phase boundary and carry on (see Phase boundaries).

## On-ramps

A starting situation that generates work, then merges onto the main flow.

- **Bugs and requests piling up** → **`/okeanos-triage`**. It moves issues through triage roles and produces agent-ready issues, which **`/okeanos-implement`** later picks up.

  Triage is only for issues **you didn't create**: bug reports, incoming feature requests, anything that arrives raw. Tickets that `/okeanos-tickets` produced are already agent-ready, so **don't triage them**.

- **Something's broken** → **`/okeanos-diagnose`**. For the hard ones: the bug that resists a first glance, the intermittent flake, the regression that crept in between two known-good states. It refuses to theorise until it has a **tight feedback loop** (one command that already goes red on *this* bug), then fixes with a regression test. Once the fix is in, run **`/okeanos-retro`** in the same session to ask what would have prevented the bug; where the real finding is that there's no good seam to lock it down, take that into the main flow at **`/okeanos-grill-with-docs`**, with **`/okeanos-codebase-design`** as the vocabulary.

- **A huge, foggy effort: a greenfield project or a huge feature build, too big for one session** → **`/okeanos-wayfinder`**, the most cognitively demanding flow here. When the way from here to the destination isn't visible yet, it charts a **shared map** of **decision tickets** on the issue tracker and resolves them one at a time, producing **decisions, not deliverables**, until the fog is pushed back and the way is clear. Where **`/okeanos-grill-with-docs`** sharpens an idea you can hold in one session, wayfinder is for the idea you can't, and it's slower and denser, so save it for exactly that, never a well-scoped feature.

  When the map clears, **it hands off, it doesn't build**: merge onto the main flow at **`/okeanos-spec`**, which collapses the map's linked decisions into a buildable plan, then `/okeanos-tickets` and `/okeanos-implement` as usual. Looping the map straight into `/okeanos-implement` skips that collapse and throws the linked detail away, so go straight to `/okeanos-implement` only when the effort turned out genuinely small.

## Performance

- **`/okeanos-performance`**: something is slow, a performance regression or budget is at stake, or you want an optimisation. Baseline with one repeatable command, change one thing at a time, keep only gains above the noise (neutral is a revert), log every attempt, and never quote a number that wasn't measured. `/okeanos-diagnose` hands its perf branch here.

## Test strength

- **`/okeanos-mutation-check`**: mutation testing on the changed lines only; each surviving mutant becomes a new test. For big features, epics and critical logic, after implementation and before `/okeanos-code-review`.
- **`/okeanos-property-tests`**: property-based tests derived from the spec's invariants by a separate agent that never sees the implementation. For domain logic in big features and epics.

## Security

- **`/okeanos-threat-model`**: a 15-line threat model (the four Threat Modeling Manifesto questions, STRIDE as prompts) run during alignment whenever a change touches auth, external input, stored or personal data, secrets, third-party calls or LLM calls. Each mitigation becomes an "If ... then" acceptance criterion and a test.

## Vocabulary underneath

Two model-invoked references that run *beneath* the other skills, each the single source of truth for its vocabulary. Reach for them directly when the **words**, not the process, are the problem; or let the skills above pull them in.

- **`/okeanos-domain-modeling`**: sharpen the project's *domain* language: challenge a fuzzy term, resolve an overloaded word ("account" doing three jobs), record a hard-to-reverse decision as an ADR. It's the active discipline `/okeanos-grill-with-docs` drives to keep `GLOSSARY.md` a clean glossary.
- **`/okeanos-codebase-design`** is the deep-module vocabulary (module, interface, depth, seam, adapter, leverage, locality) for designing a module's *shape*: a lot of behaviour behind a small interface at a clean seam. `/okeanos-tdd` speaks it.

## Phase boundaries

A **phase** is a chunk of work inside a session: the grilling, the implementation, the QA. At the **boundary** between two of them you have five options, and picking between them is the fuzziest decision in this whole map:

- **Continue**: stay put. Costs nothing, loses nothing.
- **Clear**: start a fresh context, when nothing here matters to what's next.
- **Handoff**: write a portable markdown file (goal, decisions, state, next step, pointers). Narrow: only for a **new harness**, a **new directory**, a **colleague**, or forking a side task **mid-phase**. What it buys is portability.
- **Subagent**: send a tightly-scoped task to its own window and get a report back.
- **Compact** compresses this context and seeds a fresh session with it. The **default**, at the bottom of the tree rather than the first reach.

In Claude Code: Clear is `/clear` and Compact is `/compact`.

Read [PHASE-BOUNDARIES.md](PHASE-BOUNDARIES.md) for the ordered tree: the five questions, the reasoning behind each branch, and why the primary-source cost makes **Continue** the one to rule out first. Make the decision **at** a boundary; mid-phase, continue or split the rest into subagents.

## Standalone

Off the main flow entirely.

- **`/okeanos-grill`** ("grill me"): the relentless interview itself, **stateless**: rounds, the frontier, facts are the agent's job and decisions are yours. It saves nothing locally and builds no `GLOSSARY.md`. Reach for it when you are **not working in a working directory** (a plan, a design, a piece of writing). In a working directory, `/okeanos-grill-with-docs` runs the same interview and leaves a paper trail. `/okeanos-triage` and `/okeanos-wayfinder` run it internally.
- **`/okeanos-prototype`** is a small, throwaway program that answers one design question: does this state model feel right, or what should this UI look like. Throwaway is a constraint on how the code is written, not a promise to destroy it: the answer folds into the real code, and the prototype itself is kept as a **primary source** on a `prototype/<name>` branch out of main, pointed at from the implementation issue. It's the detour in step 2 of the main flow, but reach for it any time a design question is hard to settle on paper.
- **`/okeanos-frontend-ui`**: how to build **production UI**: the project's tokens and scales, every state (loading, empty, error, no permission), accessibility, the 320/768/1024/1440 breakpoints, and a check in a real browser with an isolated profile. `/okeanos-implement` reaches for it whenever a change touches UI; after `/okeanos-prototype` picks a variant, it builds the winner.
- **`/okeanos-research`**: delegate reading legwork to a **background agent**: it investigates a question against **primary sources**, then leaves a cited Markdown file in the repo. Keep working while it reads. The file it produces is something to take *into* the main flow at `/okeanos-grill-with-docs`, since research feeds the thinking rather than replacing it.
- **`/okeanos-wizard`** is for the steps only a **human** can take: provisioning infrastructure, setting up credentials or CI secrets, clicking through an unfamiliar third-party dashboard, running a one-off migration or cutover. It generates an interactive bash script that opens each URL, captures each value, and writes it into `.env` and GitHub secrets, so the procedure stops being something you re-explain to an agent every time. Model-invoked, so the agent reaches for it the moment it hits a wall only you can pass. If the agent could just do it itself, it should; this is for where a human is genuinely in the loop.
- **`/okeanos-writing-for-agents`** is the reference for writing documents agents consume: skills, AGENTS.md, pointed-at docs.

## Precondition

**`/okeanos-onboard`**: runs first in any repo without a `CLAUDE.md`. It reads the project and writes that file (what it is, commands, structure, conventions, pitfalls), so every later session starts with the context.


**`/okeanos-setup`**: run before your first engineering flow to configure the issue tracker, triage labels, and doc layout the other skills assume. Custom issue trackers also work.
