# Guia do Okeanos

O que o Okeanos faz em cada sessão, as rotas e os gates, as aprovações, a configuração por projeto e as skills. Para instalar, veja o [README](../README.md).

## Problemas que o Okeanos trata

### Código escrito antes de alinhar o que construir

O agente começa a codar com uma ideia vaga do pedido. Nas rotas Feature e maiores, o Okeanos faz uma entrevista curta ([`okeanos-grill-with-docs`](../skills/engineering/okeanos-grill-with-docs/SKILL.md)) e para no G1. O G1 abre com uma pré-checagem: critérios de aceitação com casos de erro, nenhuma dúvida em aberto, fora de escopo definido e modelo de ameaças quando a mudança toca um gatilho de segurança.

### Testes reescritos para passar

O agente altera a asserção para o teste passar. Editar, apagar ou desligar (`skip`, `only`) linhas de um teste já commitado exige a sua aprovação. A checagem cobre as ferramentas de edição e também escritas pelo shell (`sed -i`, redirecionamento, `mv`, `rm`, `git rm`). Adicionar testes continua livre.

### "Pronto" com teste vermelho

O agente encerra o turno dizendo que terminou. Se o código mudou na sessão, o hook de fim de turno roda os comandos `onDone` (typecheck, testes, build) e impede o encerramento enquanto falharem. Quando a correção depende de uma decisão sua, o agente explica e termina com a linha `[Okeanos] precisa de você`, que libera o encerramento. Depois de 3 bloqueios seguidos, a falha passa para você do mesmo jeito.

### Pacotes alucinados

O agente instala um pacote que não existe, ou um nome parecido com um popular. Antes da instalação, o hook consulta o registry. Nome inexistente é bloqueado. Pacote publicado há menos de 30 dias, com poucos downloads ou a uma letra de um nome popular exige aprovação. Sem rede, a checagem não bloqueia.

### Segredos no commit

Antes de `git commit`, o hook procura chaves da AWS, GitHub, Slack, Stripe, Google, OpenAI e Anthropic, chaves privadas e arquivos `.env` não ignorados. Se achar, o commit é bloqueado. A mensagem mostra arquivo e tipo, nunca o valor.

### Publicar sem revisão humana

`git push`, `gh pr create/merge`, `glab mr create/merge` e merge na branch padrão sempre exigem aprovação. Essa aprovação é o G2. `--no-verify`, force push e `rm -r` fora do repositório são bloqueados.

### Diffs grandes demais para revisar

O trabalho é planejado em tickets de 200 a 400 linhas. Acima de `maxChangedLines` linhas alteradas na sessão (padrão 400), o hook avisa para dividir.

### Documentação que não acompanha o código

Antes do G2, o agente oferece a skill [`okeanos-as-built`](../skills/engineering/okeanos-as-built/SKILL.md), que atualiza um documento de arquitetura arc42 com diagramas C4 e escreve um doc da feature a partir do que foi construído. Ela gasta bastante token, então só roda se você aceitar; o agente recomenda gerar quando a mudança altera a arquitetura e pular em ajustes internos. Exemplo: [`docs/architecture.md`](architecture.md), a arquitetura do próprio Okeanos.

## Como funciona

O processo vive em [`core/process.md`](../core/process.md), neutro em relação ao agente. [`scripts/build.py`](../scripts/build.py) gera dele o output style do Claude Code ([`output-styles/okeanos.md`](../output-styles/okeanos.md), que soma às instruções padrão) e o bloco de instruções dos outros agentes ([`adapters/agents-md/okeanos.md`](../adapters/agents-md/okeanos.md)).

| Rota | Quando | Fluxo |
| :- | :- | :- |
| Direto | Pergunta ou mudança trivial | Responde ou faz, verifica. Sem gates. |
| Bug | Algo quebrado | `okeanos-tdd` com teste de regressão (ou `okeanos-diagnose` se for difícil), `okeanos-code-review`, `okeanos-as-built` se você quiser, G2 |
| Feature | Cabe numa sessão | `okeanos-grill-with-docs`, G1, `okeanos-implement`, `okeanos-as-built` se você quiser, G2 |
| Feature grande | Várias sessões, caminho claro | `okeanos-grill-with-docs`, `okeanos-spec`, `okeanos-tickets`, G1, execução na sessão ou AFK, `okeanos-mutation-check`, `okeanos-property-tests` se há lógica de domínio, `okeanos-code-review`, `okeanos-as-built` se você quiser, G2 |
| Épico | Grande e nebuloso | `okeanos-wayfinder` até o caminho clarear, depois segue como Feature grande |
| Triagem | Issues ou pedidos de terceiros | `okeanos-triage` |

Mudanças que tocam autenticação, entrada externa, dados persistidos, segredos ou chamadas a terceiros passam por [`okeanos-threat-model`](../skills/engineering/okeanos-threat-model/SKILL.md) no alinhamento. Lógica crítica passa por `okeanos-mutation-check` em qualquer rota.

**G1** fica antes de qualquer código de produção. Mostra a pré-checagem, o que será construído, as seams de teste e os tickets.

**G2** fica antes de push, PR, merge na branch padrão ou deploy. Mostra o tamanho do diff, os achados do `okeanos-code-review` por severidade, o estado de testes e typecheck, o link do doc do `okeanos-as-built` (quando você pediu os docs) e um checklist de estabilidade (evidência de execução, changelog, rollback, observabilidade, entre outros, conforme o caso).

Você pode pular etapas ("pula a entrevista", "só faz"). Os gates continuam valendo, a menos que você os dispense para aquele pedido.

## Aprovações

Onde o agente consegue pedir confirmação, o Okeanos pergunta. Onde não consegue, bloqueia e diz o comando para liberar, que você roda no seu terminal:

```bash
okeanos aprovar tests/test_calc.py   # mudar um teste já commitado
okeanos aprovar push                 # push, PR ou merge na branch principal
```

A aprovação vale 10 minutos e só para aquele alvo. Só você aprova: o comando exige o seu terminal, e o agente é barrado se tentar rodá-lo. Segredos, force push e pacote inexistente nunca são aprováveis.

Detalhes e quão forte é essa barreira em cada agente: [docs/protecoes.md](protecoes.md).

## Hooks

Os hooks rodam em momentos fixos da sessão, em qualquer agente:

| Momento | Comportamento |
| :- | :- |
| Início da sessão | Pede o `okeanos-onboard` se faltar arquivo de contexto ou `checks.json`. Registra o commit inicial da sessão. |
| Primeira mensagem | Lembra o agente de classificar e anunciar a rota. |
| Antes de um comando no shell | Exige aprovação para push, PR e merge na branch padrão. Bloqueia `--no-verify`, force push e `rm -r` fora do repo. Bloqueia commit com segredo. Checa pacotes no registry. Exige aprovação para escritas do shell em testes commitados. |
| Antes de uma edição | Exige aprovação para alterar, remover ou desligar asserções de testes commitados. |
| Depois de uma edição | Roda os comandos `onEdit` no arquivo editado e devolve as falhas ao agente. |
| Fim do turno | Roda os comandos `onDone`. Aponta testes apagados, asserções removidas, testes desligados e supressões novas de lint ou tipo. Avisa quando o diff passa de `maxChangedLines`. |

Para valer também fora dos agentes, por exemplo em commits feitos à mão, `okeanos githooks` instala git hooks com as mesmas checagens, e no GitHub o `okeanos-setup` oferece um workflow de CI. Detalhes: [docs/protecoes.md](protecoes.md).

## Configuração

Os comandos de cada projeto ficam em `docs/agents/checks.json`. O `okeanos-onboard` cria o arquivo a partir do que o projeto já usa e mostra para você aprovar.

```json
{
  "onEdit": [{ "name": "lint", "cmd": "ruff check {file}", "ext": [".py"] }],
  "onDone": [{ "name": "test", "cmd": "pytest -q" }],
  "maxChangedLines": 400,
  "testPatterns": ["(^|/)checks/.*_check\\.py$"]
}
```

- `onEdit`: roda após cada edição, nos arquivos com as extensões de `ext`. `{file}` vira o caminho editado.
- `onDone`: roda no fim do turno quando o código mudou, e no `pre-push`. É a definição de pronto.
- `maxChangedLines`: limite do aviso de tamanho. Padrão 400.
- `testPatterns`: regexes extras para reconhecer arquivos de teste em layouts fora do comum.

Cada comando aceita `timeout` em segundos.

Em projetos com algo para rodar (servidor, CLI, UI, worker), o `okeanos-onboard` também propõe `docs/agents/verificar.md`: como subir, checar, exercitar o caminho principal, que evidência guardar e como limpar. O `okeanos-implement` segue esse roteiro para produzir a evidência de execução do G2.

A `okeanos-retro` mantém `docs/agents/regras.md`: cada regra do projeto e o que a aplica (hook, check, lint, tipo, teste ou nada). Ela propõe o arquivo na primeira vez, para você aprovar, e trata como achado uma regra sem aplicação que voltou a ser violada.

### Linguagens

O processo não depende de linguagem. Os hooks reconhecem testes, `skip` e supressões de lint em JS/TS, Python, Go, Java, Kotlin, Scala, C#, Swift, Ruby, PHP, Elixir, Dart e Rust. A checagem de pacotes cobre npm, PyPI, crates.io, RubyGems, Packagist, NuGet e módulos Go. Testes inline em código-fonte (módulos `#[cfg(test)]` do Rust) não são reconhecidos como arquivos de teste.

## Skills

O agente chama a maioria das skills sozinho, conforme a rota. As marcadas como **manuais** só rodam quando você as chama.

### Fluxo

- **[okeanos-setup](../skills/engineering/okeanos-setup/SKILL.md)**: configura o repo: issue tracker, labels de triagem, layout dos docs de domínio e, no GitHub, um workflow de CI.
- **[okeanos-onboard](../skills/engineering/okeanos-onboard/SKILL.md)**: lê um projeto sem contexto e escreve um arquivo de contexto curto, o `docs/agents/checks.json` e, se há app para rodar, o `docs/agents/verificar.md`.
- **[okeanos-grill-with-docs](../skills/engineering/okeanos-grill-with-docs/SKILL.md)**: entrevista para afiar um plano, criando ADRs e glossário no caminho.
- **[okeanos-spec](../skills/engineering/okeanos-spec/SKILL.md)**: transforma a conversa numa spec e publica no tracker.
- **[okeanos-tickets](../skills/engineering/okeanos-tickets/SKILL.md)**: quebra um plano ou spec em tickets tracer-bullet com dependências explícitas.
- **[okeanos-implement](../skills/engineering/okeanos-implement/SKILL.md)**: implementa um trabalho a partir de uma spec ou de tickets.
- **[okeanos-implement-spec](../skills/engineering/okeanos-implement-spec/SKILL.md)**: implementa o resultado de `okeanos-spec` e `okeanos-tickets`, com subagentes em paralelo.
- **[okeanos-afk](../skills/engineering/okeanos-afk/SKILL.md)**: implementa os tickets em sandboxes Docker paralelas enquanto você está fora.
- **[okeanos-tdd](../skills/engineering/okeanos-tdd/SKILL.md)**: desenvolvimento guiado por testes, red-green-refactor.
- **[okeanos-diagnose](../skills/engineering/okeanos-diagnose/SKILL.md)**: loop de diagnóstico para bugs difíceis. Lentidão vai para o `okeanos-performance`.
- **[okeanos-performance](../skills/engineering/okeanos-performance/SKILL.md)**: medir, identificar, corrigir, verificar e proteger. Muda uma coisa por vez, reverte o ganho que não passa do ruído e nunca dá número sem medição.
- **[okeanos-mutation-check](../skills/engineering/okeanos-mutation-check/SKILL.md)**: teste de mutação restrito às linhas alteradas. Cada mutante sobrevivente vira um teste.
- **[okeanos-property-tests](../skills/engineering/okeanos-property-tests/SKILL.md)**: testes baseados em propriedades derivados dos invariantes da spec, escritos por um agente que vê só a spec e a interface pública.
- **[okeanos-threat-model](../skills/engineering/okeanos-threat-model/SKILL.md)**: modelo de ameaças em até 15 linhas, com STRIDE. Cada mitigação vira critério de aceitação testável.
- **[okeanos-code-review](../skills/engineering/okeanos-code-review/SKILL.md)**: revisão em dois eixos, padrões do repo e aderência à spec, em subagentes paralelos.
- **[okeanos-as-built](../skills/engineering/okeanos-as-built/SKILL.md)**: documenta o que foi construído: arc42 com diagramas C4 e um doc por feature.
- **[okeanos-pr](../skills/engineering/okeanos-pr/SKILL.md)**: escreve o corpo de um PR.
- **[okeanos-wayfinder](../skills/engineering/okeanos-wayfinder/SKILL.md)**: planeja trabalho grande demais para uma sessão como um mapa de tickets de decisão.
- **[okeanos-triage](../skills/engineering/okeanos-triage/SKILL.md)**: move issues e PRs externos por uma máquina de estados de triagem.
- **[okeanos-retro](../skills/engineering/okeanos-retro/SKILL.md)**: retrospectiva de uma sessão a partir das métricas dos hooks.

### Apoio

- **[okeanos-prototype](../skills/engineering/okeanos-prototype/SKILL.md)**: protótipo descartável para responder uma pergunta de design.
- **[okeanos-research](../skills/engineering/okeanos-research/SKILL.md)**: pesquisa em fontes primárias, salva como Markdown no repo.
- **[okeanos-wizard](../skills/engineering/okeanos-wizard/SKILL.md)**: gera um wizard em bash para passos que só uma pessoa pode fazer (credenciais, dashboards, provisionamento).
- **[okeanos-domain-modeling](../skills/engineering/okeanos-domain-modeling/SKILL.md)**: constrói o modelo de domínio do projeto: `GLOSSARY.md` e ADRs.
- **[okeanos-frontend-ui](../skills/engineering/okeanos-frontend-ui/SKILL.md)**: constrói UI de produção com os tokens do projeto, todos os estados (loading, vazio, erro, sem permissão), acessibilidade e breakpoints, conferida no navegador com perfil isolado.
- **[okeanos-codebase-design](../skills/engineering/okeanos-codebase-design/SKILL.md)**: vocabulário para desenhar módulos profundos e decidir onde ficam as seams.
- **[okeanos-grill](../skills/productivity/okeanos-grill/SKILL.md)**: entrevista implacável sobre um plano, decisão ou ideia ("grill me"), sem gerar docs. Base das outras skills de entrevista.
- **[okeanos-writing-for-agents](../skills/productivity/okeanos-writing-for-agents/SKILL.md)**: como escrever skills, `CLAUDE.md` e `AGENTS.md`.

### Manual

- **[okeanos-ask](../skills/engineering/okeanos-ask/SKILL.md)**: pergunta qual skill ou rota serve para a sua situação.

No Claude Code, ela tem `disable-model-invocation`. O Codex não lê esse campo e pode escolhê-la sozinho.

## Modo AFK

Na Feature grande, o G1 pergunta como executar os tickets. No modo AFK, a skill [`okeanos-afk`](../skills/engineering/okeanos-afk/SKILL.md) usa o Sandcastle para rodar cada ticket numa sandbox Docker própria, com um implementador e um revisor, e junta as branches numa branch de integração. Toda execução começa com uma rodada piloto. Para features críticas, dá para ligar testes de aceitação ocultos, escritos por outro agente a partir dos critérios.

O agente das sandboxes é escolhido na configuração (`AGENT` em `.sandcastle/main.mts`): Claude Code (padrão), Codex, Copilot ou Cursor. Outro valor falha na partida com a lista dos suportados. Requisitos: Node, Docker e a credencial do agente escolhido (`claude setup-token`, `OPENAI_API_KEY`, `GITHUB_TOKEN` ou `CURSOR_API_KEY`), que você mesmo cola em `.sandcastle/.env`. O agente não lê nem grava a credencial. O AFK só é usado quando você pede.

## Métricas e manutenção

A skill [`okeanos-retro`](../skills/engineering/okeanos-retro/SKILL.md) usa `.git/okeanos/metrics.jsonl` (e a reserva em `<TMPDIR>/okeanos/`) e termina em 1 a 3 mudanças concretas no processo. O agente oferece a retro depois de eventos como um G2 recusado ou uma definição de pronto escalada para você. Para ver o resumo de um repo, por tipo de evento e por agente:

```bash
okeanos metrics 30   # últimos 30 dias
```

Cada etapa do processo é uma suposição sobre o que o modelo ainda não faz bem sozinho. [`docs/manutencao.md`](manutencao.md) descreve como medir as etapas e removê-las uma a uma conforme os modelos melhoram.

## Limitações

- Copilot e Cursor ainda não rodaram numa sessão real com o Okeanos; parte do formato dos dados foi tirada da documentação. Detalhes em [docs/agentes.md](agentes.md).
- Os hooks precisam de `python3`; o modo AFK precisa de Node e Docker; a checagem de pacotes precisa de rede.
- Gemini CLI e opencode não são suportados.
- As paradas para aprovação atrapalham exploração rápida. Nesses casos, use "sem okeanos".
