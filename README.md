# Okeanos

Na mitologia grega, Okeanos é o rio sem fim que circunda o mundo. Aqui é um plugin do Claude Code que conduz cada demanda de desenvolvimento por um fluxo contínuo: do alinhamento à entrega, com dois gates de aprovação. Você não chama skills: o Okeanos classifica a demanda, escolhe a rota e chama as skills sozinho.

## Instalação

Requer o [Claude Code](https://code.claude.com). No terminal:

```bash
claude plugin marketplace add mateusblm/okeanos-agent
claude plugin install okeanos@okeanos
```

Pronto: abra uma sessão nova do Claude Code em qualquer projeto. Não é preciso chamar nada; o Okeanos já roda em toda interação. Sessões abertas antes da instalação precisam ser reiniciadas.

| Para | Comando |
| :- | :- |
| Atualizar | `claude plugin marketplace update okeanos && claude plugin update okeanos@okeanos` |
| Desligar | `claude plugin disable okeanos@okeanos` |
| Religar | `claude plugin enable okeanos@okeanos` |
| Remover | `claude plugin uninstall okeanos@okeanos` |
| Pular o processo numa demanda | escreva "sem okeanos" ou "modo livre" na mensagem |

Para desenvolver o próprio Okeanos, instale a partir do clone local; edições valem na próxima sessão:

```bash
claude plugin marketplace add /caminho/para/okeanos-agent
claude plugin install okeanos@okeanos
```

## Como funciona

O núcleo é o output style [`output-styles/okeanos.md`](output-styles/okeanos.md), marcado com `force-for-plugin: true`. Ele fica ativo em toda sessão, em qualquer projeto, sempre que o plugin estiver habilitado. Também usa `keep-coding-instructions: true`, então as instruções de engenharia padrão do Claude Code continuam valendo por baixo.

Ele não é um agente de thread principal (`"agent"` no settings) porque isso substituiria o system prompt inteiro do Claude Code.

| Rota | Fluxo |
| :- | :- |
| Direto | pergunta ou mudança trivial, sem processo |
| Bug | `tdd` (regressão) ou `diagnosing-bugs` → `code-review` → **G2** |
| Feature | `grill-with-docs` → **G1** → `implement` → `as-built` → **G2** |
| Feature grande | `grill-with-docs` → `to-spec` → `to-tickets` → **G1** → `implement-spec` ou `afk` → `mutation-check` / `property-tests` → `code-review` → `as-built` → **G2** |
| Épico | `wayfinder` → `to-spec` → ... |
| Triagem | `triage` |

- **G1**: aprovação antes de escrever código de produção. Abre com uma pré-checagem de até 10 linhas: critérios de aceitação em EARS (com os casos de erro), nenhuma dúvida em aberto, fora de escopo, modelo de ameaças quando aplicável e tickets de ~200–400 linhas.
- **G2**: aprovação antes de push, PR, merge ou deploy, garantida por hook. Traz o tamanho do diff, a revisão por severidade, o doc do `as-built` e um checklist curto de estabilidade: evidência de ter rodado a aplicação, changelog, plano de rollback e remoção de feature flags.

Ao abrir uma sessão num repo sem `CLAUDE.md`, um hook avisa o Okeanos e a primeira coisa que ele faz é rodar a skill [`onboard`](skills/engineering/onboard/SKILL.md): lê o projeto (README, manifests, CI, estrutura, testes, convenções) e cria um `CLAUDE.md` enxuto com o que o projeto é, comandos, estrutura, convenções e cuidados.

Na primeira demanda de engenharia num repo sem `docs/agents/issue-tracker.md`, ele roda `setup-okeanos` (tracker padrão: markdown local em `.scratch/`).

Para fugir do processo numa demanda, escreva **"sem okeanos"** ou **"modo livre"** na mensagem.

## Verificações automáticas (hooks)

As regras que mais importam não dependem do modelo lembrar delas: o plugin as aplica com hooks (`hooks/okeanos.py`, só Python 3 da biblioteca padrão; sem `python3` na máquina, os hooks são pulados).

| Quando | O que acontece |
| :- | :- |
| Cada edição | Roda format e lint do arquivo editado (`onEdit`); erro volta para o agente na hora. |
| Edição em teste já commitado | Alterar, apagar ou desligar (`skip`) asserções e casos de teste pede a sua aprovação; adicionar testes e mexer em imports ou helpers é livre. Testes commitados são o contrato. |
| Agente vai encerrar | Se o código mudou, roda typecheck, testes e build (`onDone`). Falhou: o agente não encerra e corrige; depois de 3 tentativas, o problema vem para você. Testes alterados e diffs acima de `maxChangedLines` geram aviso. |
| `git push`, `gh pr create/merge`, merge na branch padrão | Pede a sua confirmação: é o G2, garantido mesmo em modo automático. |
| `--no-verify`, force push, `rm -r` fora do repo | Bloqueado. |
| `git commit` | Procura segredos (chaves AWS, GitHub, Stripe, Anthropic, OpenAI, chaves privadas, `.env`) e bloqueia o commit se achar. |
| `npm/pnpm/yarn/bun add`, `pip/uv/poetry add`, `cargo add` | Pacote que não existe é bloqueado (nome alucinado); pacote com menos de 30 dias, pouco baixado ou a uma letra de um popular pede confirmação. |
| Supressão nova (`eslint-disable`, `@ts-ignore`, `as any`, `# noqa`...) | Apontada no fim do turno; o agente precisa justificar para você. |
| Tudo acima | Registrado em `.git/okeanos/metrics.jsonl` (local, fora do repo), que a `retro` usa para medir em vez de opinar. |

No GitHub, o `setup-okeanos` oferece um workflow (`.github/workflows/okeanos-checks.yml`) que roda os mesmos comandos de pronto, procura segredos (gitleaks), avisa asserções removidas e roda SAST (Semgrep) em PRs, para nada chegar à `main` por fora dos hooks.

O Okeanos não depende de linguagem: os comandos de cada projeto (pytest, go test, cargo, gradle, dotnet, npm...) ficam em `docs/agents/checks.json`, que a skill `onboard` cria na primeira sessão. A detecção de testes, `skip` e supressões cobre JS/TS, Python, Go, Java/Kotlin/Scala, C#, Swift, Ruby, PHP, Elixir, Dart e Rust; o guard de pacotes verifica npm, PyPI, crates.io, RubyGems, Packagist, NuGet e módulos Go. A única exigência de linguagem fica no AFK: o runner usa o Sandcastle, uma biblioteca Node, então a máquina precisa de Node; o projeto em si pode ser de qualquer linguagem, com o runtime adicionado à imagem Docker.

Exemplo de `checks.json`:

```json
{
  "onEdit": [{ "name": "lint", "cmd": "npx eslint {file}", "ext": [".ts", ".tsx"] }],
  "onDone": [{ "name": "typecheck", "cmd": "npm run typecheck" }, { "name": "test", "cmd": "npm test" }],
  "maxChangedLines": 400
}
```

O porquê de cada regra está no relatório de pesquisa que originou esta versão: agentes reescrevem testes para passar, inventam pacotes, vazam segredos e entregam diffs grandes demais para revisar; instruções não bastam, hooks sim.

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

- **Fluxo** (o Okeanos chama sozinho): `onboard`, `setup-okeanos`, `threat-model`, `mutation-check`, `property-tests`, `grill-with-docs`, `grill-me`, `grilling`, `domain-modeling`, `to-spec`, `to-tickets`, `implement`, `implement-spec`, `afk`, `as-built`, `tdd`, `diagnosing-bugs`, `code-review`, `pr`, `wayfinder`, `triage`, `retro`, `handoff`, `prototype`, `research`, `codebase-design`, `wizard`, `writing-for-agents`.
- **Manuais** (só você chama): `ask-okeanos` (mapa das rotas), `teach`, `wait-what`, `to-questionnaire`, `improve-codebase-architecture`.

## Manutenção

Cada etapa do Okeanos é uma aposta sobre o que o modelo não faz bem sozinho. [`docs/manutencao.md`](docs/manutencao.md) descreve como medir com as métricas dos hooks (`hooks/run metrics 30`) e como podar uma etapa por vez quando os modelos melhorarem.

## Licença

MIT. Veja [`LICENSE`](LICENSE).
