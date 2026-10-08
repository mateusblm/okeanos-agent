# Okeanos

Na mitologia grega, Okeanos é o rio sem fim que circunda o mundo. Aqui é um plugin do Claude Code que conduz cada demanda de desenvolvimento por um fluxo contínuo: do alinhamento à entrega, com dois gates de aprovação. Você não chama skills: o Okeanos classifica a demanda, escolhe a rota e chama as skills sozinho.

## Como funciona

O núcleo é o output style [`output-styles/okeanos.md`](output-styles/okeanos.md), marcado com `force-for-plugin: true`. Ele fica ativo em toda sessão, em qualquer projeto, sempre que o plugin estiver habilitado. Também usa `keep-coding-instructions: true`, então as instruções de engenharia padrão do Claude Code continuam valendo por baixo.

Ele não é um agente de thread principal (`"agent"` no settings) porque isso substituiria o system prompt inteiro do Claude Code.

| Rota | Fluxo |
| :- | :- |
| Direto | pergunta ou mudança trivial, sem processo |
| Bug | `tdd` (regressão) ou `diagnosing-bugs` → `code-review` → **G2** |
| Feature | `grill-with-docs` → **G1** → `implement` → `as-built` → **G2** |
| Feature grande | `grill-with-docs` → `to-spec` → `to-tickets` → **G1** → `implement-spec` ou `afk` → `code-review` → `as-built` → **G2** |
| Épico | `wayfinder` → `to-spec` → ... |
| Triagem | `triage` |

- **G1**: aprovação antes de escrever código de produção.
- **G2**: aprovação antes de push, PR, merge ou deploy.

Na primeira demanda de engenharia num repo sem `docs/agents/issue-tracker.md`, ele roda `setup-okeanos` (tracker padrão: markdown local em `.scratch/`).

Para fugir do processo numa demanda, escreva **"sem okeanos"** ou **"modo livre"** na mensagem.

## Docs do que foi construído

Antes do G2, a skill [`as-built`](skills/engineering/as-built/SKILL.md) documenta o que foi de fato implementado, lendo o código e o diff, não o plano:

- `docs/architecture.md`: a arquitetura viva no padrão **arc42** (12 seções), com diagramas **C4** em Mermaid (contexto, containers, componentes, execução e implantação). Criada na primeira entrega, atualizada nas seguintes;
- `docs/features/<feature>.md`: o que foi construído, onde se encaixa no C4 (novo em verde, alterado em amarelo), fluxos, testes e pendências.

Exemplo completo em [`examples/calc`](examples/calc).

Os docs entram no mesmo commit/PR do código e renderizam direto no GitHub. Em bugs, só atualiza docs existentes se o fix mudou comportamento documentado.

## AFK

Na Feature grande, o G1 pergunta se a implementação roda na sessão ou **AFK**. No AFK, a skill [`afk`](skills/engineering/afk/SKILL.md) monta um runner em `.sandcastle/` no projeto (uma vez por repo) e:

1. lê os tickets de `.scratch/<feature>/issues/` e calcula quais estão prontos pelas linhas `**Status:**` e `**Blocked by:**`;
2. roda cada ticket pronto num container Docker isolado, na sua própria branch, com um agente implementador (usando `tdd`) e um revisor;
3. faz o merge das branches na branch de integração e marca os tickets como `done`;
4. repete até não sobrar ticket pronto e escreve `.scratch/<feature>/afk-report.md`.

Na volta, o Okeanos lê o relatório, roda `code-review` e para no G2.

Requisitos: Docker, e um token em `.sandcastle/.env` (`claude setup-token`). O token você mesmo cola; o Okeanos nunca lê.

## Skills

Todas vivem em [`skills/`](skills/) e são do Okeanos: edite direto.

- **Fluxo** (o Okeanos chama sozinho): `setup-okeanos`, `grill-with-docs`, `grill-me`, `grilling`, `domain-modeling`, `to-spec`, `to-tickets`, `implement`, `implement-spec`, `afk`, `as-built`, `tdd`, `diagnosing-bugs`, `code-review`, `pr`, `wayfinder`, `triage`, `retro`, `handoff`, `prototype`, `research`, `codebase-design`, `wizard`, `writing-for-agents`.
- **Manuais** (só você chama): `ask-okeanos` (mapa das rotas), `teach`, `wait-what`, `to-questionnaire`, `improve-codebase-architecture`.

## Instalação

```bash
claude plugin marketplace add /home/mateus/orca/projects/okeanos-agent
claude plugin install okeanos@okeanos
```

O plugin é lido direto deste diretório, então edições aqui valem na próxima sessão. Para desligar: `claude plugin disable okeanos@okeanos`.

## Licença

MIT. Veja [`LICENSE`](LICENSE).
