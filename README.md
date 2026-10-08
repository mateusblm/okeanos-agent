# Okeanos

Um plugin para o Claude Code que conduz cada sessão por um processo de engenharia.

O plugin força um output style que classifica cada pedido numa rota (Direto, Bug, Feature, Feature grande, Épico, Triagem) e segue o fluxo dessa rota. Há duas paradas obrigatórias para aprovação: **G1**, antes de escrever código de produção, e **G2**, antes de publicar. As skills são chamadas pelo próprio agente conforme a rota. Hooks determinísticos, em Python, aplicam as regras que não podem depender do modelo lembrar.

O nome vem do Okeanos da mitologia grega, o rio que dá a volta no mundo.

## Instalação

```bash
claude plugin marketplace add mateusblm/okeanos-agent
claude plugin install okeanos@okeanos
```

Sessões abertas antes de instalar ou atualizar precisam ser reiniciadas.

Na primeira sessão num repositório sem `CLAUDE.md` ou sem `docs/agents/checks.json`, o agente roda a skill [`onboard`](skills/engineering/onboard/SKILL.md): lê o projeto, propõe um `CLAUDE.md` curto para você aprovar e grava os comandos que os hooks executam. Na primeira rota de engenharia, roda [`setup-okeanos`](skills/engineering/setup-okeanos/SKILL.md) para configurar o issue tracker (por padrão, markdown local em `.scratch/`).

| Para | Comando |
| :- | :- |
| Atualizar | `claude plugin marketplace update okeanos && claude plugin update okeanos@okeanos` |
| Desligar | `claude plugin disable okeanos@okeanos` |
| Religar | `claude plugin enable okeanos@okeanos` |
| Remover | `claude plugin uninstall okeanos@okeanos` |

Para tratar um pedido sem o processo, escreva "sem okeanos" (ou "modo livre") na mensagem.

## Problemas que o Okeanos trata

### Código escrito antes de alinhar o que construir

O agente começa a codar com uma ideia vaga do pedido. Nas rotas Feature e maiores, o Okeanos faz uma entrevista curta ([`grill-with-docs`](skills/engineering/grill-with-docs/SKILL.md)) e para no G1. O G1 abre com uma pré-checagem: critérios de aceitação com casos de erro, nenhuma dúvida em aberto, fora de escopo definido e modelo de ameaças quando a mudança toca um gatilho de segurança.

### Testes reescritos para passar

O agente altera a asserção para o teste passar. Editar, apagar ou desligar (`skip`, `only`) linhas de um teste já commitado pede a sua aprovação. A checagem cobre o editor e também escritas pelo shell (`sed -i`, redirecionamento, `mv`, `rm`, `git rm`). Adicionar testes continua livre.

### "Pronto" com teste vermelho

O agente encerra o turno dizendo que terminou. Se o código mudou na sessão, o hook `Stop` roda os comandos `onDone` (typecheck, testes, build) e bloqueia o encerramento enquanto falharem. Quando a correção depende de uma decisão sua, o agente explica e termina com a linha `**Okeanos** · precisa de você`, que libera o encerramento e mostra a falha. Depois de 3 bloqueios seguidos, a falha passa para você do mesmo jeito.

### Pacotes alucinados

O agente instala um pacote que não existe, ou um nome parecido com um popular. Antes da instalação, o hook consulta o registry. Nome inexistente é bloqueado. Pacote publicado há menos de 30 dias, com poucos downloads ou a uma letra de um nome popular pede confirmação. Sem rede, a checagem não bloqueia.

### Segredos no commit

Antes de `git commit`, o hook procura chaves da AWS, GitHub, Slack, Stripe, Google, OpenAI e Anthropic, chaves privadas e arquivos `.env` não ignorados. Se achar, o commit é bloqueado.

### Publicar sem revisão humana

`git push`, `gh pr create/merge`, `glab mr create/merge` e merge na branch padrão sempre pedem confirmação. Essa confirmação é o G2. `--no-verify`, force push e `rm -r` fora do repositório são bloqueados.

### Diffs grandes demais para revisar

O trabalho é planejado em tickets de 200 a 400 linhas. Acima de `maxChangedLines` linhas alteradas na sessão (padrão 400), o hook avisa para dividir.

### Documentação que não acompanha o código

Antes do G2, a skill [`as-built`](skills/engineering/as-built/SKILL.md) atualiza um documento de arquitetura arc42 com diagramas C4 e escreve um doc da feature a partir do que foi construído. Exemplo: [`examples/calc/docs/architecture.md`](examples/calc/docs/architecture.md).

## Como funciona

O processo vive em [`output-styles/okeanos.md`](output-styles/okeanos.md). Ele soma às instruções padrão do Claude Code (`keep-coding-instructions: true`).

| Rota | Quando | Fluxo |
| :- | :- | :- |
| Direto | Pergunta ou mudança trivial | Responde ou faz, verifica. Sem gates. |
| Bug | Algo quebrado | `tdd` com teste de regressão (ou `diagnosing-bugs` se for difícil), `code-review`, `as-built` se mudou comportamento documentado, G2 |
| Feature | Cabe numa sessão | `grill-with-docs`, G1, `implement`, `as-built`, G2 |
| Feature grande | Várias sessões, caminho claro | `grill-with-docs`, `to-spec`, `to-tickets`, G1, execução na sessão ou AFK, `mutation-check`, `property-tests` se há lógica de domínio, `code-review`, `as-built`, G2 |
| Épico | Grande e nebuloso | `wayfinder` até o caminho clarear, depois segue como Feature grande |
| Triagem | Issues ou pedidos de terceiros | `triage` |

Mudanças que tocam autenticação, entrada externa, dados persistidos, segredos ou chamadas a terceiros passam por [`threat-model`](skills/engineering/threat-model/SKILL.md) no alinhamento. Lógica crítica passa por `mutation-check` em qualquer rota.

**G1** fica antes de qualquer código de produção. Mostra a pré-checagem, o que será construído, as seams de teste e os tickets.

**G2** fica antes de push, PR, merge na branch padrão ou deploy. Mostra o tamanho do diff, os achados do `code-review` por severidade, o estado de testes e typecheck, o link do doc do `as-built` e um checklist de estabilidade (evidência de execução, changelog, rollback, observabilidade, entre outros, conforme o caso).

Você pode pular etapas ("pula a entrevista", "só faz"). Os gates continuam valendo, a menos que você os dispense para aquele pedido.

## Hooks

Definidos em [`hooks/hooks.json`](hooks/hooks.json) e implementados em [`hooks/okeanos_engine/`](hooks/okeanos_engine/) (regras neutras e um dialeto por agente), com entrada em [`hooks/okeanos.py`](hooks/okeanos.py).

| Evento | Comportamento |
| :- | :- |
| `SessionStart` | Pede o `onboard` se faltar `CLAUDE.md` ou `checks.json`. Registra o commit inicial da sessão. |
| `UserPromptSubmit` | Na primeira mensagem, lembra o agente de classificar a rota. |
| `PreToolUse` (Bash) | Pede confirmação para push, PR e merge na branch padrão. Bloqueia `--no-verify`, force push e `rm -r` fora do repo. Bloqueia commit com segredo. Checa pacotes no registry. Pede aprovação para escritas do shell em testes commitados. |
| `PreToolUse` (Edit, Write) | Pede aprovação para alterar, remover ou desligar asserções de testes commitados. |
| `PostToolUse` (Edit, Write) | Roda os comandos `onEdit` no arquivo editado e devolve as falhas ao agente. |
| `Stop` | Roda os comandos `onDone`. Aponta testes apagados, asserções removidas, testes desligados e supressões novas de lint ou tipo. Avisa quando o diff passa de `maxChangedLines`. |

Cada bloqueio, pedido de aprovação e falha é registrado em `.git/okeanos/metrics.jsonl`.

## Configuração

Os comandos de cada projeto ficam em `docs/agents/checks.json`. O `onboard` cria o arquivo a partir do que o projeto já usa e mostra para você aprovar.

```json
{
  "onEdit": [{ "name": "lint", "cmd": "ruff check {file}", "ext": [".py"] }],
  "onDone": [{ "name": "test", "cmd": "pytest -q" }],
  "maxChangedLines": 400,
  "testPatterns": ["(^|/)checks/.*_check\\.py$"]
}
```

- `onEdit`: roda após cada edição, nos arquivos com as extensões de `ext`. `{file}` vira o caminho editado.
- `onDone`: roda no fim do turno quando o código mudou. É a definição de pronto.
- `maxChangedLines`: limite do aviso de tamanho. Padrão 400.
- `testPatterns`: regexes extras para reconhecer arquivos de teste em layouts fora do comum.

Cada comando aceita `timeout` em segundos.

### Linguagens

O processo não depende de linguagem. Os hooks reconhecem testes, `skip` e supressões de lint em JS/TS, Python, Go, Java, Kotlin, Scala, C#, Swift, Ruby, PHP, Elixir, Dart e Rust. A checagem de pacotes cobre npm, PyPI, crates.io, RubyGems, Packagist, NuGet e módulos Go. Testes inline em código-fonte (módulos `#[cfg(test)]` do Rust) não são reconhecidos como arquivos de teste.

## Skills

O agente chama a maioria das skills sozinho, conforme a rota. As marcadas como **manuais** só rodam quando você as chama.

### Fluxo

- **[setup-okeanos](skills/engineering/setup-okeanos/SKILL.md)**: configura o repo: issue tracker, labels de triagem, layout dos docs de domínio e, no GitHub, um workflow de CI.
- **[onboard](skills/engineering/onboard/SKILL.md)**: lê um projeto sem contexto e escreve um `CLAUDE.md` curto e o `docs/agents/checks.json`.
- **[grill-with-docs](skills/engineering/grill-with-docs/SKILL.md)**: entrevista para afiar um plano, criando ADRs e glossário no caminho.
- **[to-spec](skills/engineering/to-spec/SKILL.md)**: transforma a conversa numa spec e publica no tracker.
- **[to-tickets](skills/engineering/to-tickets/SKILL.md)**: quebra um plano ou spec em tickets tracer-bullet com dependências explícitas.
- **[implement](skills/engineering/implement/SKILL.md)**: implementa um trabalho a partir de uma spec ou de tickets.
- **[implement-spec](skills/engineering/implement-spec/SKILL.md)**: implementa o resultado de `to-spec` e `to-tickets`, com subagentes em paralelo.
- **[afk](skills/engineering/afk/SKILL.md)**: implementa os tickets em sandboxes Docker paralelas enquanto você está fora.
- **[tdd](skills/engineering/tdd/SKILL.md)**: desenvolvimento guiado por testes, red-green-refactor.
- **[diagnosing-bugs](skills/engineering/diagnosing-bugs/SKILL.md)**: loop de diagnóstico para bugs difíceis e regressões de desempenho.
- **[mutation-check](skills/engineering/mutation-check/SKILL.md)**: teste de mutação restrito às linhas alteradas. Cada mutante sobrevivente vira um teste.
- **[property-tests](skills/engineering/property-tests/SKILL.md)**: testes baseados em propriedades derivados dos invariantes da spec, escritos por um agente que vê só a spec e a interface pública.
- **[threat-model](skills/engineering/threat-model/SKILL.md)**: modelo de ameaças em até 15 linhas, com STRIDE. Cada mitigação vira critério de aceitação testável.
- **[code-review](skills/engineering/code-review/SKILL.md)**: revisão em dois eixos, padrões do repo e aderência à spec, em subagentes paralelos.
- **[as-built](skills/engineering/as-built/SKILL.md)**: documenta o que foi construído: arc42 com diagramas C4 e um doc por feature.
- **[pr](skills/engineering/pr/SKILL.md)**: escreve o corpo de um PR.
- **[wayfinder](skills/engineering/wayfinder/SKILL.md)**: planeja trabalho grande demais para uma sessão como um mapa de tickets de decisão.
- **[triage](skills/engineering/triage/SKILL.md)**: move issues e PRs externos por uma máquina de estados de triagem.
- **[retro](skills/engineering/retro/SKILL.md)**: retrospectiva de uma sessão a partir das métricas dos hooks.

### Apoio

- **[prototype](skills/engineering/prototype/SKILL.md)**: protótipo descartável para responder uma pergunta de design.
- **[research](skills/engineering/research/SKILL.md)**: pesquisa em fontes primárias, salva como Markdown no repo.
- **[wizard](skills/engineering/wizard/SKILL.md)**: gera um wizard em bash para passos que só uma pessoa pode fazer (credenciais, dashboards, provisionamento).
- **[domain-modeling](skills/engineering/domain-modeling/SKILL.md)**: constrói o modelo de domínio do projeto: `GLOSSARY.md` e ADRs.
- **[codebase-design](skills/engineering/codebase-design/SKILL.md)**: vocabulário para desenhar módulos profundos e decidir onde ficam as seams.
- **[grilling](skills/productivity/grilling/SKILL.md)**: entrevista sobre um plano, decisão ou ideia. Base das outras skills de entrevista.
- **[grill-me](skills/productivity/grill-me/SKILL.md)**: entrevista para afiar um plano, sem gerar docs.
- **[handoff](skills/productivity/handoff/SKILL.md)**: compacta a conversa num documento para outro agente continuar.
- **[writing-for-agents](skills/productivity/writing-for-agents/SKILL.md)**: como escrever skills, `CLAUDE.md` e `AGENTS.md`.

### Manuais

- **[ask-okeanos](skills/engineering/ask-okeanos/SKILL.md)**: pergunta qual skill ou rota serve para a sua situação.
- **[improve-codebase-architecture](skills/engineering/improve-codebase-architecture/SKILL.md)**: procura oportunidades de aprofundar módulos, gera um relatório HTML e entrevista sobre a que você escolher.
- **[teach](skills/productivity/teach/SKILL.md)**: ensina um conceito ou habilidade dentro do workspace.
- **[to-questionnaire](skills/productivity/to-questionnaire/SKILL.md)**: transforma uma decisão que você não consegue fechar sozinho num questionário para outra pessoa.
- **[wait-what](skills/productivity/wait-what/SKILL.md)**: pede ao agente que reformule a última mensagem que não ficou clara.

## Modo AFK

Na Feature grande, o G1 pergunta como executar os tickets. No modo AFK, a skill [`afk`](skills/engineering/afk/SKILL.md) usa o Sandcastle para rodar cada ticket numa sandbox Docker própria, com um implementador e um revisor, e junta as branches numa branch de integração. Toda execução começa com uma rodada piloto. Para features críticas, dá para ligar testes de aceitação ocultos, escritos por outro agente a partir dos critérios.

Requisitos: Node, Docker e um token do Claude (`claude setup-token`) que você mesmo cola em `.sandcastle/.env`. O agente não lê nem grava o token. O AFK só é usado quando você pede.

## CI

Em repositórios com remote no GitHub, o `setup-okeanos` oferece um workflow (`.github/workflows/okeanos-checks.yml`) que roda os comandos `onDone`, um scan de segredos com gitleaks e Semgrep no código alterado. Tornar esses jobs obrigatórios na branch protection fica com você.

## Métricas e manutenção

A skill [`retro`](skills/engineering/retro/SKILL.md) usa `.git/okeanos/metrics.jsonl` e termina em 1 a 3 mudanças concretas no processo. O agente oferece a retro depois de eventos como um G2 recusado ou uma definição de pronto escalada para você. Para ver o resumo de um repo:

```bash
cd <projeto> && <caminho-do-okeanos-agent>/hooks/run metrics 30   # últimos 30 dias
```

Cada etapa do processo é uma suposição sobre o que o modelo ainda não faz bem sozinho. [`docs/manutencao.md`](docs/manutencao.md) descreve como medir as etapas e removê-las uma a uma conforme os modelos melhoram.

## Limitações

- Os hooks precisam de `python3`. Sem ele, o processo continua e os hooks ficam desligados.
- O modo AFK precisa de Node e Docker.
- Funciona só no Claude Code. Suporte a outros agentes está em desenvolvimento.
- A checagem de pacotes precisa de rede. Offline, ela não bloqueia.
- As paradas para aprovação atrapalham exploração rápida. Nesses casos, use "sem okeanos".

## Desenvolvimento

Instale a partir de um clone local:

```bash
claude plugin marketplace add /caminho/para/okeanos-agent
claude plugin install okeanos@okeanos
```

O próprio repo usa o Okeanos. As checagens dele estão em [`docs/agents/checks.json`](docs/agents/checks.json) e validam os manifestos do plugin e do marketplace.

## Licença

MIT. Veja [`LICENSE`](LICENSE).
