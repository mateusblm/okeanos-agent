# Okeanos

Okeanos conduz cada sessão de um agente de código por um processo de engenharia. São três partes: o texto do processo, que classifica cada pedido numa rota e define duas paradas para aprovação; um conjunto de skills que o agente chama conforme a rota; e hooks determinísticos, em Python, que aplicam as regras que não podem depender do modelo lembrar.

Funciona no Claude Code, no Codex, no GitHub Copilot (CLI) e no Cursor (IDE). O processo, as skills e o motor das regras são um núcleo só; cada agente recebe um adaptador fino que traduz esse núcleo para o formato dele.

O nome vem do Okeanos da mitologia grega, o rio que dá a volta no mundo.

## Instalação

### Claude Code

```bash
claude plugin marketplace add mateusblm/okeanos-agent
claude plugin install okeanos@okeanos
```

| Para | Comando |
| :- | :- |
| Atualizar | `claude plugin marketplace update okeanos && claude plugin update okeanos@okeanos` |
| Desligar | `claude plugin disable okeanos@okeanos` |
| Religar | `claude plugin enable okeanos@okeanos` |
| Remover | `claude plugin uninstall okeanos@okeanos` |

Sessões abertas antes de instalar ou atualizar precisam ser reiniciadas.

### Codex, Copilot e Cursor

```bash
curl -fsSL https://raw.githubusercontent.com/mateusblm/okeanos-agent/main/install.sh | sh
```

O script precisa de `git` e `python3`. Ele clona o repositório em `~/.local/share/okeanos` (ou o atualiza) e roda `okeanos install`, que detecta os agentes no PATH e instala em cada um, inclusive no Claude Code, pelo marketplace. Também liga a CLI `okeanos` em `~/.local/bin` e avisa se essa pasta não está no PATH.

| Para | Comando |
| :- | :- |
| Só alguns agentes | `okeanos install --agent codex,cursor` (ou `--agent` repetido): `claude`, `codex`, `copilot`, `cursor` |
| Ver sem mudar nada | `okeanos install --dry-run` |
| Atualizar | rode `install.sh` de novo (`git pull` e reinstalação idempotente) |
| Remover | `okeanos install --uninstall [--agent ...]` |
| Confiar nos hooks do Codex | `okeanos codex-confiar [--project] [--sim]`, num terminal seu (o `install` já pergunta) |
| Diagnosticar | `okeanos doctor`: onde o Okeanos está, o que o repositório tem, quais agentes estão no PATH e o que está instalado em cada um |

O instalador só mexe no que é do Okeanos: o bloco entre `<!-- okeanos:start -->` e `<!-- okeanos:end -->` nos arquivos de instruções, os handlers de hook cujo comando é o do Okeanos e os links para o clone. Antes de mudar um arquivo, guarda a versão anterior em `<arquivo>.okeanos-bak`. Se um arquivo de configuração existente não for JSON ou TOML válido, aquele agente é pulado sem nenhuma escrita e a mensagem diz qual arquivo corrigir. As skills ficam em `~/.agents/skills` como links para o clone; uma skill com o mesmo nome e outro conteúdo é pulada, com aviso. Desinstalar um agente mantém as skills enquanto outro ainda usa o Okeanos.

**Codex.** Hooks em `~/.codex/hooks.json` (ou, com `--codex-hooks toml`, em tabelas `[hooks]` no fim do `config.toml`, entre `# okeanos:start` e `# okeanos:end`) e o bloco do processo no `AGENTS.md` global (`$CODEX_HOME`, padrão `~/.codex`). O Codex só roda hooks que você confiou. No fim de `okeanos install`, num terminal seu, o instalador lista os hooks do Okeanos (evento, matcher e comando exato; eles rodam fora do sandbox do Codex) e pergunta "Autorizar esses hooks no Codex agora? [s/N]". Com `s`, ele pede ao próprio Codex (`codex app-server`: `hooks/list`, depois `config/batchWrite` em `hooks.state`) que confie só nos hooks do Okeanos que precisam de revisão, nunca nos de outras ferramentas, e confere com o Codex hook por hook; o hash é sempre o que o Codex calcula. Sem terminal, dentro de um agente ou com `N`, nada é escrito: depois de cada atualização, ou quando quiser, rode `okeanos codex-confiar` (`--sim` responde sim à pergunta dos hooks, mas ainda exige terminal e recusa sessão de agente), ou escolha "Trust all and continue" quando o Codex pedir ao iniciar (ou `/hooks`). Se o Codex falhar, a mensagem traz o motivo e o caminho pelo `/hooks`, e a instalação segue. Desinstalar também tira de `hooks.state` as entradas dos hooks do Okeanos (as outras ficam). Se existir `~/.codex/AGENTS.override.md`, o Codex lê ele no lugar do `AGENTS.md` global e o processo não carrega; o instalador avisa, e também avisa se o `config.toml` desliga os hooks.

*Hooks por projeto.* `okeanos install --agent codex --project`, de dentro de um repositório git, junta os hooks do Okeanos ao `.codex/hooks.json` do projeto (os hooks que o projeto já tinha ficam; `--project --uninstall` tira só os do Okeanos). A confiança é pedida no fim, como nos hooks de usuário (depois: `okeanos codex-confiar --project`); ela fica no `hooks.state` do `config.toml` do usuário. O Codex só carrega o `.codex/` de pastas confiáveis: se a raiz do repositório ainda não é, vem uma segunda pergunta [s/N], separada, para marcá-la como confiável (`projects."<raiz>".trust_level = "trusted"`, a mesma escrita do "Trust this folder" do Codex; isso também faz o Codex carregar o resto do `.codex/` do repositório). Essa pergunta é sempre feita, também com `--sim`. Com `N`, nada é escrito; num worktree ligado (o Codex guarda a confiança na pasta principal) ela não é oferecida. A desinstalação nunca tira a confiança da pasta. Commite `.codex/hooks.json` se o time deve compartilhar os hooks (os caminhos apontam para o seu clone do Okeanos). Não use junto com os hooks de usuário: rodariam duas vezes, e o instalador avisa.

*Orca.* Sob o Orca, o `CODEX_HOME` é uma pasta que o Orca regenera (tem o arquivo `.orca-managed-home`) e reescreve `hooks.json` e `config.toml` a cada partida, então hooks de usuário somem. Nesse caso `okeanos install` não escreve hooks de usuário (ignora `--codex-hooks` e remove o bloco do `config.toml` de instalações antigas), instala skills e o bloco do `AGENTS.md`, que sobrevivem, e manda instalar os hooks por projeto: rode `okeanos install --agent codex --project` em cada projeto. A confiança dos hooks de projeto fica no `config.toml` do `CODEX_HOME` do Orca e sobreviveu à regeneração nos testes ao vivo; se o Codex voltar a pedir revisão, rode `okeanos codex-confiar --project` de novo. `okeanos doctor` mostra se o Codex é gerenciado pelo Orca e se o repositório atual tem os hooks do projeto.

**Copilot.** Hooks em `~/.copilot/hooks/okeanos.json` (um arquivo só do Okeanos) e o bloco do processo em `~/.copilot/copilot-instructions.md` (`$COPILOT_HOME`, padrão `~/.copilot`). Reinicie o Copilot CLI depois de instalar ou atualizar. Se `~/.copilot/settings.json` tiver `disableAllHooks: true`, o instalador avisa. Com a sandbox de sessão do Copilot ligada, inclua o clone do Okeanos em `sandbox.userPolicy`, ou os hooks falham.

**Cursor.** Detectado por `cursor`, `cursor-agent` ou pela pasta `~/.cursor`. Hooks em `~/.cursor/hooks.json`. O Cursor não tem arquivo para regras globais, então o processo entra por projeto: na raiz de cada repositório, rode `okeanos install --agent cursor --project`, que escreve `.cursor/rules/okeanos.mdc` (`alwaysApply: true`); commite o arquivo ou ponha no `.gitignore`, e rode de novo depois de atualizar o Okeanos (`--project --uninstall` remove). Outra opção é colar [`adapters/agents-md/okeanos.md`](adapters/agents-md/okeanos.md) em Customize → Rules. Confira em Cursor Settings → Hooks que os hooks aparecem.

### Primeira sessão num projeto

Num repositório sem arquivo de contexto (`CLAUDE.md` no Claude Code, `AGENTS.md` nos outros) ou sem `docs/agents/checks.json`, o agente roda a skill [`onboard`](skills/engineering/onboard/SKILL.md): lê o projeto, propõe um arquivo de contexto curto para você aprovar e grava os comandos que os hooks executam. Na primeira rota de engenharia, roda [`setup-okeanos`](skills/engineering/setup-okeanos/SKILL.md) para configurar o issue tracker (por padrão, markdown local em `.scratch/`).

Para tratar um pedido sem o processo, escreva "sem okeanos" (ou "modo livre") na mensagem.

## O que cada agente suporta

| | Claude Code | Codex | Copilot (CLI) | Cursor (IDE) |
| :- | :- | :- | :- | :- |
| Processo | output style do plugin | bloco no `~/.codex/AGENTS.md` | bloco no `~/.copilot/copilot-instructions.md` | regra por projeto, `.cursor/rules/okeanos.mdc` |
| Skills | plugin | `~/.agents/skills` | `~/.agents/skills` | `~/.agents/skills` |
| Hooks | `SessionStart`, `UserPromptSubmit`, `PreToolUse` (Bash, Edit, Write, MultiEdit), `PostToolUse` (Edit, Write, MultiEdit), `Stop` | `SessionStart`, `UserPromptSubmit`, `PreToolUse` (Bash, apply_patch), `PostToolUse` (apply_patch), `Stop` | `sessionStart`, `preToolUse` (bash, powershell, edit, create, write, str_replace_editor, apply_patch), `postToolUse` (as de edição), `agentStop` | `sessionStart`, `beforeShellExecution`, `preToolUse` e `postToolUse` (Write, StrReplace, Delete, Edit, MultiEdit), `afterAgentResponse`, `stop` |
| Aprovação | confirmação nativa | bloqueia e indica `okeanos aprovar` | confirmação nativa; bloqueia e indica `okeanos aprovar` na nuvem ou com `COPILOT_ALLOW_ALL` | confirmação nativa no shell; nas edições, bloqueia e indica `okeanos aprovar` |
| Pronto ao encerrar | `Stop` bloqueia | `Stop` bloqueia e o turno continua | `agentStop` bloqueia e roda outro turno | `stop` devolve a falha como `followup_message` |
| Limitações | nenhuma conhecida | só `apply_patch` passa pelo `PostToolUse`; `disable-model-invocation` é ignorado | lembrete de rota vai no início da sessão; avisos só para você não aparecem; hooks de usuário não valem na nuvem | sem lembrete de rota; avisos só para você não aparecem; edição por ferramenta desconhecida não é barrada antes |

"Avisos só para você" são a escalada depois de 3 bloqueios, a falha com a linha de handoff e o aviso de tamanho do diff; nesses agentes, veja-os em `okeanos metrics`. O Copilot na nuvem trata "perguntar" como "negar" e só lê hooks de `.github/hooks/` do repositório. No Cursor, o turno continua com a mensagem de falha como se fosse sua, até 3 vezes (o `loop_limit` padrão do Cursor é 5); turno cancelado ou com erro não continua.

## Problemas que o Okeanos trata

### Código escrito antes de alinhar o que construir

O agente começa a codar com uma ideia vaga do pedido. Nas rotas Feature e maiores, o Okeanos faz uma entrevista curta ([`grill-with-docs`](skills/engineering/grill-with-docs/SKILL.md)) e para no G1. O G1 abre com uma pré-checagem: critérios de aceitação com casos de erro, nenhuma dúvida em aberto, fora de escopo definido e modelo de ameaças quando a mudança toca um gatilho de segurança.

### Testes reescritos para passar

O agente altera a asserção para o teste passar. Editar, apagar ou desligar (`skip`, `only`) linhas de um teste já commitado exige a sua aprovação. A checagem cobre as ferramentas de edição e também escritas pelo shell (`sed -i`, redirecionamento, `mv`, `rm`, `git rm`). Adicionar testes continua livre.

### "Pronto" com teste vermelho

O agente encerra o turno dizendo que terminou. Se o código mudou na sessão, o hook de fim de turno roda os comandos `onDone` (typecheck, testes, build) e impede o encerramento enquanto falharem. Quando a correção depende de uma decisão sua, o agente explica e termina com a linha `**Okeanos** · precisa de você`, que libera o encerramento. Depois de 3 bloqueios seguidos, a falha passa para você do mesmo jeito.

### Pacotes alucinados

O agente instala um pacote que não existe, ou um nome parecido com um popular. Antes da instalação, o hook consulta o registry. Nome inexistente é bloqueado. Pacote publicado há menos de 30 dias, com poucos downloads ou a uma letra de um nome popular exige aprovação. Sem rede, a checagem não bloqueia.

### Segredos no commit

Antes de `git commit`, o hook procura chaves da AWS, GitHub, Slack, Stripe, Google, OpenAI e Anthropic, chaves privadas e arquivos `.env` não ignorados. Se achar, o commit é bloqueado. A mensagem mostra arquivo e tipo, nunca o valor.

### Publicar sem revisão humana

`git push`, `gh pr create/merge`, `glab mr create/merge` e merge na branch padrão sempre exigem aprovação. Essa aprovação é o G2. `--no-verify`, force push e `rm -r` fora do repositório são bloqueados.

### Diffs grandes demais para revisar

O trabalho é planejado em tickets de 200 a 400 linhas. Acima de `maxChangedLines` linhas alteradas na sessão (padrão 400), o hook avisa para dividir.

### Documentação que não acompanha o código

Antes do G2, o agente oferece a skill [`as-built`](skills/engineering/as-built/SKILL.md), que atualiza um documento de arquitetura arc42 com diagramas C4 e escreve um doc da feature a partir do que foi construído. Ela gasta bastante token, então só roda se você aceitar; o agente recomenda gerar quando a mudança altera a arquitetura e pular em ajustes internos. Exemplos: [`docs/architecture.md`](docs/architecture.md), a arquitetura do próprio Okeanos, e [`examples/calc/docs/architecture.md`](examples/calc/docs/architecture.md).

## Como funciona

O processo vive em [`core/process.md`](core/process.md), neutro em relação ao agente. [`scripts/build.py`](scripts/build.py) gera dele o output style do Claude Code ([`output-styles/okeanos.md`](output-styles/okeanos.md), que soma às instruções padrão) e o bloco de instruções dos outros agentes ([`adapters/agents-md/okeanos.md`](adapters/agents-md/okeanos.md)).

| Rota | Quando | Fluxo |
| :- | :- | :- |
| Direto | Pergunta ou mudança trivial | Responde ou faz, verifica. Sem gates. |
| Bug | Algo quebrado | `tdd` com teste de regressão (ou `diagnosing-bugs` se for difícil), `code-review`, `as-built` se você quiser, G2 |
| Feature | Cabe numa sessão | `grill-with-docs`, G1, `implement`, `as-built` se você quiser, G2 |
| Feature grande | Várias sessões, caminho claro | `grill-with-docs`, `to-spec`, `to-tickets`, G1, execução na sessão ou AFK, `mutation-check`, `property-tests` se há lógica de domínio, `code-review`, `as-built` se você quiser, G2 |
| Épico | Grande e nebuloso | `wayfinder` até o caminho clarear, depois segue como Feature grande |
| Triagem | Issues ou pedidos de terceiros | `triage` |

Mudanças que tocam autenticação, entrada externa, dados persistidos, segredos ou chamadas a terceiros passam por [`threat-model`](skills/engineering/threat-model/SKILL.md) no alinhamento. Lógica crítica passa por `mutation-check` em qualquer rota.

**G1** fica antes de qualquer código de produção. Mostra a pré-checagem, o que será construído, as seams de teste e os tickets.

**G2** fica antes de push, PR, merge na branch padrão ou deploy. Mostra o tamanho do diff, os achados do `code-review` por severidade, o estado de testes e typecheck, o link do doc do `as-built` (quando você pediu os docs) e um checklist de estabilidade (evidência de execução, changelog, rollback, observabilidade, entre outros, conforme o caso).

Você pode pular etapas ("pula a entrevista", "só faz"). Os gates continuam valendo, a menos que você os dispense para aquele pedido.

## Aprovações

Onde o agente consegue pedir confirmação (veja a tabela de suporte), o Okeanos pergunta. Onde não consegue, bloqueia e termina a mensagem com `Para aprovar: okeanos aprovar <alvo>`. Rode esse comando no seu terminal e peça ao agente para tentar de novo:

```bash
okeanos aprovar tests/test_calc.py   # um teste commitado (caminho relativo ao repo)
okeanos aprovar push                 # git push, PR, merge na branch padrão
okeanos aprovar pacote:expresss      # um pacote suspeito, mas existente
okeanos aprovacoes                   # lista as ativas
okeanos revogar [alvo]               # remove uma, ou todas sem alvo
```

A aprovação vale 10 minutos, só para aquele alvo exato, e fica em `.git/okeanos/approvals.json`. Os hooks consultam as aprovações antes de perguntar ou bloquear.

As aprovações são do humano. `aprovar` e `revogar` exigem um terminal interativo e recusam rodar num shell de agente (com `CLAUDECODE`, as variáveis `CODEX_*` que o Codex põe no shell das ferramentas ou `CURSOR_AGENT`). Os hooks negam ao agente:

- rodar esses comandos, inclusive por um interpretador ou wrapper (`python -c`, `node -e`, `perl -e`, `sh -c`, `xargs`, heredoc), num pseudo-terminal (`pty.spawn`, `script`, `expect`, `unbuffer`, `tmux`, `socat ... pty`) ou com as variáveis de sessão de agente removidas (`env -u`, `env -i`, `unset`);
- escrever no estado do Okeanos, em `.git/okeanos/` ou no reserva em `<TMPDIR>/okeanos/`;
- remover ou contornar os git hooks (`okeanos githooks --uninstall`, escrita em `.git/hooks`, troca de `core.hooksPath`) e os hooks do projeto com entradas do Okeanos (`.codex/hooks.json`, `.cursor/hooks.json`, `.cursor/rules/okeanos.mdc`, `.github/hooks/`), além de `okeanos install --uninstall`.

Segredos, force push, `--no-verify`, `rm -r` fora do repositório e pacote inexistente nunca são aprováveis.

Quão forte é essa barreira depende do agente. No Claude Code e no Copilot CLI (fora da nuvem e sem `COPILOT_ALLOW_ALL`), a aprovação é a confirmação do próprio programa do agente: uma barreira real, fora do alcance do modelo. No Codex e no Cursor, quem aprova é o `okeanos aprovar`, e as checagens acima barram atalhos e reward hacking acidental. Um agente que roda como o mesmo usuário do sistema operacional poderia, em princípio, escrever um script novo para contorná-las. Nesse caso, o hook de fim de turno, os git hooks (`okeanos githooks`) e o CI continuam como barreiras seguintes.

## Hooks

Os hooks entram por [`hooks/run`](hooks/run) `--agent <agente> <hook>`, que chama [`hooks/okeanos.py`](hooks/okeanos.py). No Claude Code, estão em [`hooks/hooks.json`](hooks/hooks.json); nos outros, o instalador os escreve na configuração de usuário (no Codex sob o Orca, ou com `--project`, no `.codex/hooks.json` do projeto). Os nomes de evento variam por agente (tabela de suporte); o comportamento é o mesmo:

| Momento | Comportamento |
| :- | :- |
| Início da sessão | Pede o `onboard` se faltar arquivo de contexto ou `checks.json`. Registra o commit inicial da sessão. |
| Primeira mensagem | Lembra o agente de classificar e anunciar a rota. |
| Antes de um comando no shell | Exige aprovação para push, PR e merge na branch padrão. Bloqueia `--no-verify`, force push e `rm -r` fora do repo. Bloqueia commit com segredo. Checa pacotes no registry. Exige aprovação para escritas do shell em testes commitados. |
| Antes de uma edição | Exige aprovação para alterar, remover ou desligar asserções de testes commitados. |
| Depois de uma edição | Roda os comandos `onEdit` no arquivo editado e devolve as falhas ao agente. |
| Fim do turno | Roda os comandos `onDone`. Aponta testes apagados, asserções removidas, testes desligados e supressões novas de lint ou tipo. Avisa quando o diff passa de `maxChangedLines`. |

Qualquer erro interno de um hook vira "permitir", nunca bloqueio. Cada bloqueio, pedido de aprovação e falha é registrado em `.git/okeanos/metrics.jsonl`, com o nome do agente. Quando a pasta do git é só leitura (a sandbox do Codex), o estado da sessão e as métricas vão para a reserva em `<TMPDIR>/okeanos/`; as aprovações ficam sempre em `.git/okeanos/`.

### Git hooks

`okeanos githooks`, rodado dentro de um repositório, instala dois git hooks que valem para qualquer agente e para quem commita à mão:

| Hook | Comportamento |
| :- | :- |
| `pre-commit` | Falha se o stage tem segredo (mostra arquivo e tipo) ou arquivo `.env` novo. Falha se um teste já commitado perde ou muda asserções ou casos, ou ganha `skip`, sem aprovação ativa; a mensagem termina com `Para aprovar: okeanos aprovar <arquivo>`. Reformatar e adicionar testes passam. Supressões novas só geram aviso. |
| `pre-push` | Roda os comandos `onDone` de `docs/agents/checks.json` e falha mostrando o comando e o fim da saída. Sem `checks.json`, avisa e deixa passar. |

Os hooks vão para a pasta que o git usa (`core.hooksPath`, ou `.git/hooks` do repositório principal, também a partir de um worktree) e chamam `bin/okeanos` pelo caminho absoluto de quando foram instalados; se o Okeanos mudar de lugar, rode `okeanos githooks` de novo. Um hook que já existia vira `<nome>.okeanos-prev` e roda antes. `okeanos githooks --uninstall` remove só os hooks do Okeanos e devolve os anteriores. Sem `python3`, os hooks avisam e deixam passar. `git commit --no-verify` pula os hooks: é uma escolha do humano, já que os hooks do agente negam `--no-verify`.

### CI

Em repositórios com remote no GitHub, o `setup-okeanos` oferece um workflow (`.github/workflows/okeanos-checks.yml`) que roda os comandos `onDone`, um scan de segredos com gitleaks e Semgrep no código alterado. Tornar esses jobs obrigatórios na branch protection fica com você.

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
- `onDone`: roda no fim do turno quando o código mudou, e no `pre-push`. É a definição de pronto.
- `maxChangedLines`: limite do aviso de tamanho. Padrão 400.
- `testPatterns`: regexes extras para reconhecer arquivos de teste em layouts fora do comum.

Cada comando aceita `timeout` em segundos.

### Linguagens

O processo não depende de linguagem. Os hooks reconhecem testes, `skip` e supressões de lint em JS/TS, Python, Go, Java, Kotlin, Scala, C#, Swift, Ruby, PHP, Elixir, Dart e Rust. A checagem de pacotes cobre npm, PyPI, crates.io, RubyGems, Packagist, NuGet e módulos Go. Testes inline em código-fonte (módulos `#[cfg(test)]` do Rust) não são reconhecidos como arquivos de teste.

## Skills

O agente chama a maioria das skills sozinho, conforme a rota. As marcadas como **manuais** só rodam quando você as chama.

### Fluxo

- **[setup-okeanos](skills/engineering/setup-okeanos/SKILL.md)**: configura o repo: issue tracker, labels de triagem, layout dos docs de domínio e, no GitHub, um workflow de CI.
- **[onboard](skills/engineering/onboard/SKILL.md)**: lê um projeto sem contexto e escreve um arquivo de contexto curto e o `docs/agents/checks.json`.
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

No Claude Code, as manuais têm `disable-model-invocation`. O Codex não lê esse campo e pode escolhê-las sozinho.

## Modo AFK

Na Feature grande, o G1 pergunta como executar os tickets. No modo AFK, a skill [`afk`](skills/engineering/afk/SKILL.md) usa o Sandcastle para rodar cada ticket numa sandbox Docker própria, com um implementador e um revisor, e junta as branches numa branch de integração. Toda execução começa com uma rodada piloto. Para features críticas, dá para ligar testes de aceitação ocultos, escritos por outro agente a partir dos critérios.

O agente das sandboxes é escolhido na configuração (`AGENT` em `.sandcastle/main.mts`): Claude Code (padrão), Codex, Copilot ou Cursor. Outro valor falha na partida com a lista dos suportados. Requisitos: Node, Docker e a credencial do agente escolhido (`claude setup-token`, `OPENAI_API_KEY`, `GITHUB_TOKEN` ou `CURSOR_API_KEY`), que você mesmo cola em `.sandcastle/.env`. O agente não lê nem grava a credencial. O AFK só é usado quando você pede.

## Métricas e manutenção

A skill [`retro`](skills/engineering/retro/SKILL.md) usa `.git/okeanos/metrics.jsonl` (e a reserva em `<TMPDIR>/okeanos/`) e termina em 1 a 3 mudanças concretas no processo. O agente oferece a retro depois de eventos como um G2 recusado ou uma definição de pronto escalada para você. Para ver o resumo de um repo, por tipo de evento e por agente:

```bash
okeanos metrics 30   # últimos 30 dias
```

Cada etapa do processo é uma suposição sobre o que o modelo ainda não faz bem sozinho. [`docs/manutencao.md`](docs/manutencao.md) descreve como medir as etapas e removê-las uma a uma conforme os modelos melhoram.

## Limitações

- Copilot e Cursor não tiveram nenhuma sessão real com o Okeanos: os dialetos foram testados com payloads montados a partir da documentação. Partes do formato são inferidas:
  - Copilot: os argumentos das ferramentas de edição (`edit`, `create`, `str_replace_editor`) não estão documentados, então o dialeto aceita as duas grafias; o `agentStop` não traz a última mensagem, e o dialeto a procura no transcript, cujo formato não é documentado.
  - Cursor: o `tool_input` das ferramentas de arquivo (`StrReplace`, `path` ou `file_path`, `content`) vem de relatos, não da documentação; o que o dialeto não consegue ler conta como reescrita do arquivo inteiro. A variável `CURSOR_AGENT`, usada para recusar `okeanos aprovar` no shell do agente, também não é documentada.
- O Copilot não põe no shell das ferramentas uma variável que identifique a sessão; ali, a recusa de `okeanos aprovar` depende só da exigência de terminal interativo e do bloqueio pelos hooks.
- No Cursor, os hooks do Cursor CLI ficam de fora; o alvo é o agente do Cursor IDE.
- Os hooks precisam de `python3`. Sem ele, o processo continua e os hooks ficam desligados.
- O modo AFK precisa de Node e Docker.
- A checagem de pacotes precisa de rede. Offline, ela não bloqueia.
- Gemini CLI e opencode não são suportados.
- As paradas para aprovação atrapalham exploração rápida. Nesses casos, use "sem okeanos".

## Desenvolvimento

| Caminho | O que tem |
| :- | :- |
| [`core/process.md`](core/process.md) | o texto do processo, neutro em relação ao agente |
| [`scripts/build.py`](scripts/build.py) | gera `output-styles/okeanos.md` e `adapters/agents-md/okeanos.md`; `--check` falha se estiverem desatualizados |
| [`skills/`](skills/) | as skills, com texto neutro em relação ao agente |
| [`hooks/okeanos_engine/`](hooks/okeanos_engine/) | o motor: regras neutras em `rules.py`, um dialeto por agente em `dialects/`, aprovações, git hooks e o instalador (`installer.py`) |
| [`bin/okeanos`](bin/okeanos) | a CLI: `install`, `codex-confiar`, `doctor`, `aprovar`, `aprovacoes`, `revogar`, `githooks`, `metrics` |
| [`tests/`](tests/) | testes do motor, dos dialetos, do instalador, dos git hooks e do build |
| [`docs/architecture.md`](docs/architecture.md) | a arquitetura (arc42 com diagramas C4) e, em [`docs/features/`](docs/features/), um doc por feature |

Para mudar o processo, edite `core/process.md` e rode `python3 scripts/build.py`; os arquivos gerados nunca se editam à mão. Para suportar outro agente, escreva um dialeto em `hooks/okeanos_engine/dialects/` e o plano dele no instalador; as regras não mudam. Rode os testes da raiz:

```bash
python3 -m pytest -q
```

Para instalar a partir de um clone local:

```bash
claude plugin marketplace add /caminho/para/okeanos-agent   # Claude Code
claude plugin install okeanos@okeanos
bin/okeanos install --dry-run                               # todos os agentes; sem --dry-run para aplicar
```

O próprio repo usa o Okeanos. As checagens dele estão em [`docs/agents/checks.json`](docs/agents/checks.json): validam os manifestos do plugin e do marketplace, conferem os arquivos gerados e rodam os testes.

## Licença

MIT. Veja [`LICENSE`](LICENSE).
