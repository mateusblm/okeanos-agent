---
name: okeanos-property-tests
description: Derive property-based tests from the invariants in a spec and run them against the implementation, written by a separate agent that sees only the spec and the public interface. Use after implementing domain logic in a big feature or epic (parsers, calculations, state transitions, serialization), or when the user asks for property-based or generative tests.
---

# Property tests

Example tests check the cases someone thought of. Property tests state a rule that must hold for every input, then let a generator hunt for the input that breaks it, and shrink it to the smallest counterexample. An agent writing property tests from a spec has found real bugs that maintainers confirmed, including in NumPy.

The value comes from independence: the properties must come from the spec, not from the code. Run the work in a **subagent** that receives only the spec, the ticket criteria and the public interface signatures, never the implementation.

## When

Feature grande and Épico with domain logic, after implementation: parsers and formatters, calculations, state machines, serialization, sorting and filtering, anything with a round trip. Skip for UI, glue code and plain CRUD.

## 1. Find the properties

From the spec's acceptance criteria and domain rules, list candidate properties. The usual shapes:

- **Round trip**: `decode(encode(x)) == x`, `parse(format(x)) == x`.
- **Invariant**: something always true of the output (a total never negative, a sorted list stays sorted, an ID is unique).
- **Idempotence**: doing it twice equals doing it once (normalize, deduplicate, apply a migration).
- **Equivalence**: matches a simpler reference implementation or an older version.
- **Commutativity or order independence**: when the spec says order doesn't matter.
- **Error properties**: every invalid input in a class is rejected with the specified error (from the "If ... then" criteria).

Keep only properties the spec actually implies. Show the list to the user only if a property depends on an undecided rule.

## 2. Write them with the stack's library

Use the library the project has; if none, propose the standard one and add it after the user agrees: **fast-check** (JS/TS), **Hypothesis** (Python), **jqwik** (Java), **proptest** (Rust), **rapid** or `testing/quick` (Go).

Spawn the subagent with: the spec, the acceptance criteria, the public signatures it may call, the test conventions of the repo (`CLAUDE.md` or `AGENTS.md`, two existing tests), and this brief: "Write one property test per property below, through the public interface only. Generators must cover edge values (empty, zero, negative, unicode, huge). Run them. Report each failing property with the shrunk counterexample. Don't change non-test code."

## 3. Act on counterexamples

A counterexample is either a bug or a property the spec didn't really imply. Decide which with the spec, not by bending the property:

- **Bug**: keep the property test (it now fails), fix the code in the normal TDD loop.
- **Spec gap**: a question for the user. Don't weaken the generator to make it pass.

## 4. Report

One short block for the G2 summary: properties tested, counterexamples found, and what happened to each.
