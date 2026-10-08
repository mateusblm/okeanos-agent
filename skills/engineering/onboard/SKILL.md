---
name: onboard
description: Read a project that lacks Okeanos context and write it - a short, human-approved context file (CLAUDE.md in Claude Code, AGENTS.md in other agents) and the docs/agents/checks.json the Okeanos hooks run. Use at the start of a session in a repo without that context file or checks.json, or when the user asks to create or refresh the project's context file.
---

# Onboard

Two files give every later session what it needs, and nothing more:

- **The context file**: `CLAUDE.md` in Claude Code, `AGENTS.md` in every other agent (Codex, Copilot, Cursor read it natively). Below, "the context file" means the one for the agent you are running in. It holds the few things an agent can't cheaply rediscover: the commands, the non-obvious conventions, and the traps. Short and approved by the user.
- **`docs/agents/checks.json`**: the commands the Okeanos hooks run deterministically: format and lint after each edit, typecheck, tests and build before the agent may stop.

Keep the context file lean on purpose. In a 2026 study, LLM-generated context files with repository overviews didn't improve agent results and raised cost by over 20%; the helpful ones were short and written or reviewed by humans. An agent can list directories itself; it can't guess a project's traps.

Write in the language the user speaks in the session. Do this before anything else the user asked, then carry on with their request.

## When to skip

- Not inside a git repository, or no source files yet: nothing to describe. Carry on silently.
- Both files exist: nothing to do unless the user asks for a refresh.
- The context file exists but `checks.json` doesn't: do only step 3, without touching the context file.
- In Claude Code, `AGENTS.md` exists but `CLAUDE.md` doesn't: the new `CLAUDE.md` starts with `@AGENTS.md` (so Claude Code loads it) and adds only what `AGENTS.md` lacks.
- In another agent, `CLAUDE.md` exists but `AGENTS.md` doesn't: propose moving its content to a new `AGENTS.md` and leaving `@AGENTS.md` as the first line of `CLAUDE.md`, so both agents read one file. If the user declines, write an `AGENTS.md` with only what this agent needs from `CLAUDE.md`.

## 1. Read the project

Read, don't guess, stopping as soon as you can fill the sections below:

- `README*`, `CONTRIBUTING*`, existing `docs/`, ADRs.
- Manifests and lockfiles (`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, ...): stack, package manager, scripts.
- How it builds and ships: `Makefile`, `justfile`, `Dockerfile`, compose files, CI workflows. CI shows the commands that really gate a merge.
- Quality config: linter, formatter, type checker, test runner.
- `.env.example`: variable names only, never values.
- A few entry points and one representative module, to spot conventions that differ from the ecosystem's defaults.

Don't run anything that installs, builds, migrates, starts services, or touches the network.

## 2. Draft the context file and get it approved

Use the `writing-for-agents` skill for how to write for an agent reader. Draft this shape (headings in the session language):

```markdown
# <Nome do projeto>

<Uma ou duas frases: o que é e para quem.>

## Comandos

| Para | Comando |
| :- | :- |
| Instalar | `...` |
| Testes | `...` |
| Typecheck / lint | `...` |
| Build | `...` |

## Convenções

<Só o que difere do padrão do ecossistema e você viu no código: onde ficam os testes se não é o óbvio, padrão de erros, regras de arquitetura, padrão de commit.>

## Cuidados

<Arquivos gerados que não se editam à mão, variáveis de ambiente obrigatórias (só nomes), comandos lentos ou perigosos, regras que quebram o build.>
```

Rules:

- **No repository overview.** No directory map, no file list, no stack tour: the agent reads those itself. Add a line about structure only when it's a trap ("`legacy/` está congelado, não edite").
- Under ~40 lines. Every line must be something an agent would get wrong without it.
- Only facts you found. Omit what you couldn't confirm.
- No secrets or environment values.

Show the draft to the user and ask them to cut or correct anything before you write it. Write it only after they confirm. If they say "pode gravar" or similar without edits, write it as drafted.

## 3. Write `docs/agents/checks.json`

From the commands you confirmed (or from the context file when it already existed), write:

```json
{
  "onEdit": [
    { "name": "format", "cmd": "npx prettier --write {file}", "ext": [".ts", ".tsx", ".js"] },
    { "name": "lint", "cmd": "npx eslint {file}", "ext": [".ts", ".tsx", ".js"] }
  ],
  "onDone": [
    { "name": "typecheck", "cmd": "npm run typecheck" },
    { "name": "test", "cmd": "npm test" }
  ],
  "maxChangedLines": 400
}
```

The same shape for other stacks (use what the project really has):

| Stack | `onEdit` | `onDone` |
| :- | :- | :- |
| Python | `ruff format {file}`, `ruff check {file}` (`.py`) | `mypy .` or `pyright`, `pytest -q` |
| Go | `gofmt -w {file}` (`.go`) | `go vet ./...`, `go test ./...` |
| Rust | `rustfmt {file}` (`.rs`) | `cargo clippy -- -D warnings`, `cargo test` |
| Java/Kotlin | (none, formatting runs in the build) | `./gradlew check` or `mvn -q verify` |
| C# | `dotnet format --include {file}` | `dotnet build`, `dotnet test` |
| Ruby | `bundle exec rubocop -a {file}` (`.rb`) | `bundle exec rspec` |
| PHP | `vendor/bin/php-cs-fixer fix {file}` (`.php`) | `vendor/bin/phpstan`, `vendor/bin/phpunit` |

- `onEdit` runs after every edit on the edited file (`{file}` is replaced by its path). Only per-file commands that finish in seconds: formatter, linter. Use `ext` so a linter never runs on a file it can't parse. Leave it empty when the project has neither.
- `onDone` runs before the agent may stop, whenever code changed in the session: typecheck, tests, build. A failing command blocks the stop and its output goes back to the agent.
- Use the project's own scripts and the exact commands CI runs. Never add a tool the project doesn't already use.
- `maxChangedLines` is the size budget per session; above it the user gets a warning to split the work. Keep 400 unless the user says otherwise.
- Optional `testPatterns`: extra regexes that identify test files when the project uses an unusual layout. The defaults cover the usual layouts of JS/TS, Python, Go, Java/Kotlin/Scala, C#, Swift, Ruby, PHP, Elixir, Dart and Rust's `tests/` folder. Tests written inline in source files (Rust `#[cfg(test)]` modules) aren't recognised as test files, so the committed-test guard doesn't cover them; say so to the user when the project relies on them.

## 4. Hand back

Tell the user in one or two lines what you created. Don't commit: the files go in with the next commit of the flow. Then continue with what the user asked.
