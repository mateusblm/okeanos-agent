---
name: mutation-check
description: Measure whether the tests of a change actually catch bugs - mutation testing restricted to the changed lines, with each surviving mutant turned into a new test. Use after implementation of a big feature, an epic, or critical logic (money, permissions, data integrity), or when the user asks whether the tests are good enough.
---

# Mutation check

Passing tests prove little when the agent wrote both the code and the tests: assertions tend to check what the code does rather than what it should do. Mutation testing measures the tests themselves. A tool makes small deliberate bugs (mutants) in the code, such as `>` becoming `>=` or a `return x` becoming `return null`, and reruns the tests. A mutant the tests don't notice (a survivor) marks a behaviour no test pins down.

Run it only on what changed: Google runs mutation testing per code review on changed lines for exactly that reason, since whole-codebase runs are slow and noisy.

## When

- Feature grande and Épico, after implementation and before `code-review`.
- Any route touching critical logic: money, permissions, data integrity, parsing.
- When the user asks.

Skip it for UI layout, configuration, glue code, and changes under ~30 lines of logic.

## 1. Pick the tool the project can run

Use the tool the project already has. If it has none, propose the standard one for the stack and add it only after the user agrees (it is a new dev dependency, and the package guard will check it):

| Stack | Tool | Changed-files run |
| :- | :- | :- |
| JS/TS | StrykerJS | `npx stryker run --mutate <file1>,<file2>` |
| Python | mutmut | `mutmut run --paths-to-mutate <file1>,<file2>` |
| Java/Kotlin | PIT | `-DtargetClasses=<classes>` with the Maven/Gradle plugin |
| Rust | cargo-mutants | `cargo mutants --in-diff <diff-file>` |
| Go | go-mutesting | `go-mutesting <package>` |

The changed source files are `git diff --name-only <base>...HEAD`, minus tests, docs and generated files.

## 2. Run and read

Run the tool on the changed source files only. Collect the surviving mutants with their location and the mutation applied. Ignore equivalent mutants (a change that can't alter behaviour, like a mutation inside dead logging) and say which you ignored and why.

## 3. Kill the survivors

For each meaningful survivor, write a test that fails with the mutant and passes with the real code: through the public interface, with the expected value taken from the spec, never recomputed the way the code computes it. Adding tests is always free under the Okeanos test guard. Rerun the tool on the same files to confirm the survivor is now killed.

If a survivor exposes behaviour the spec never decided (what should happen at exactly the boundary?), that is a question for the user, not a test to guess.

## 4. Report

One short block for the G2 summary:

```markdown
**Mutação** (<tool>, <n> arquivos alterados): <killed>/<total> mortos (<score>%). Sobreviventes restantes: <n>, <one line each: where and why it's acceptable or what's undecided>.
```
