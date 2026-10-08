---
name: onboard
description: Read a project that has no CLAUDE.md and write one, so every later session starts with the project's context. Use at the start of a session in a repo without CLAUDE.md, or when the user asks to create or refresh the project's context file.
---

# Onboard

A repo without `CLAUDE.md` makes every session rediscover what the project is. Read the project once and write that file: what it is, how to run it, where things live, and what to be careful with. Do this before anything else the user asked, then carry on with their request.

Write in the language the user speaks in the session.

## When to skip

- Not inside a git repository, or the repo has no source files yet (only a README or nothing): there is nothing to describe. Say nothing and carry on.
- `CLAUDE.md` exists at the repo root or in `.claude/`: the project already has context. Only rewrite it when the user asks.
- `AGENTS.md` exists but `CLAUDE.md` doesn't: create a `CLAUDE.md` whose first line is `@AGENTS.md`, so Claude Code loads it. Add nothing else unless `AGENTS.md` lacks the essentials below; then add only the missing sections under the import.

## 1. Read the project

Read, don't guess. In roughly this order, stopping once you can fill every section:

- `README*`, `CONTRIBUTING*`, existing `docs/` (especially `docs/architecture.md`), ADRs.
- Manifests and lockfiles: `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`, `Gemfile`, `composer.json`, and the like. They give the stack, the package manager, and the scripts.
- How it builds and ships: `Makefile`, `justfile`, `Dockerfile`, compose files, `.github/workflows/` or other CI. CI shows the real commands that gate a merge.
- Quality config: linters, formatters, type checker, test runner config.
- Environment: `.env.example` and config files. Record variable names only, never values.
- Structure: the top two levels of the tree (`git ls-files` grouped by directory). Open a few entry points and one representative module to see the conventions in use.
- Tests: where they live, how they are named, which runner.

Do not run commands that install, build, migrate, start services, or touch the network. You may run the test or typecheck command once if the repo is small and it clearly needs no setup; if you didn't run a command, its source (the script or CI job) is enough.

## 2. Write `CLAUDE.md`

Call the Skill tool with "writing-for-agents" for how to write for an agent reader. Then write `CLAUDE.md` at the repo root with this shape (headings in the session language):

```markdown
# <Nome do projeto>

<Duas ou três frases: o que o projeto é, para quem, e o que faz.>

## Stack

<Linguagem e versão, framework, banco, serviços externos. Uma linha cada.>

## Comandos

| Para | Comando |
| :- | :- |
| Instalar | `...` |
| Rodar local | `...` |
| Testes | `...` |
| Typecheck / lint | `...` |
| Build | `...` |

## Estrutura

<Diretório → o que vive nele. Só os que importam para trabalhar no código.>

## Convenções

<Só o que você viu no código ou na config: estilo, padrões de nome, onde ficam os testes, como erros são tratados, padrão de commit se o histórico mostra um.>

## Cuidados

<Arquivos gerados que não se editam à mão, variáveis de ambiente obrigatórias (só nomes), passos lentos ou perigosos, pegadinhas que a leitura revelou.>

## Documentação

<Links para README, docs/architecture.md, ADRs e outros docs que existem.>
```

Rules:

- Keep it under ~80 lines. It loads into every session, so every line must earn its place. Link to longer docs instead of copying them.
- Only facts you found. Omit a section rather than fill it with guesses; a command you couldn't find stays out of the table.
- Name things the way the code and docs name them.
- No secrets, tokens, or environment values.

## 3. Hand back

Tell the user in one or two lines that the project had no `CLAUDE.md`, that you created it, and what it covers. Don't commit it: it goes in with the user's next commit or the flow's first commit. Then continue with what the user asked.
