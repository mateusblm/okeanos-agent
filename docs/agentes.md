# Okeanos em cada agente

Detalhes de instalação e de comportamento por agente. Para o resumo, veja o [README](../README.md#instalação).

## Como o instalador mexe nos arquivos

O instalador só mexe no que é do Okeanos: o bloco entre `<!-- okeanos:start -->` e `<!-- okeanos:end -->` nos arquivos de instruções, os handlers de hook cujo comando é o do Okeanos e os links para o clone. Antes de mudar um arquivo, guarda a versão anterior em `<arquivo>.okeanos-bak`. Se um arquivo de configuração existente não for JSON ou TOML válido, aquele agente é pulado sem nenhuma escrita e a mensagem diz qual arquivo corrigir. As skills ficam em `~/.agents/skills` como links para o clone; uma skill com o mesmo nome e outro conteúdo é pulada, com aviso. Desinstalar um agente mantém as skills enquanto outro ainda usa o Okeanos.

## Codex

Hooks em `~/.codex/hooks.json` (ou, com `--codex-hooks toml`, em tabelas `[hooks]` no fim do `config.toml`, entre `# okeanos:start` e `# okeanos:end`) e o bloco do processo no `AGENTS.md` global (`$CODEX_HOME`, padrão `~/.codex`). O Codex só roda hooks que você confiou. No fim de `okeanos install`, num terminal seu, o instalador lista os hooks do Okeanos (evento, matcher e comando exato; eles rodam fora do sandbox do Codex) e pergunta "Autorizar esses hooks no Codex agora? [s/N]". Com `s`, ele pede ao próprio Codex (`codex app-server`: `hooks/list`, depois `config/batchWrite` em `hooks.state`) que confie só nos hooks do Okeanos que precisam de revisão, nunca nos de outras ferramentas, e confere com o Codex hook por hook; o hash é sempre o que o Codex calcula. Sem terminal, dentro de um agente ou com `N`, nada é escrito: depois de cada atualização, ou quando quiser, rode `okeanos codex-confiar` (`--sim` responde sim à pergunta dos hooks, mas ainda exige terminal e recusa sessão de agente), ou escolha "Trust all and continue" quando o Codex pedir ao iniciar (ou `/hooks`). Se o Codex falhar, a mensagem traz o motivo e o caminho pelo `/hooks`, e a instalação segue. Desinstalar também tira de `hooks.state` as entradas dos hooks do Okeanos (as outras ficam). Se existir `~/.codex/AGENTS.override.md`, o Codex lê ele no lugar do `AGENTS.md` global e o processo não carrega; o instalador avisa, e também avisa se o `config.toml` desliga os hooks.

### Hooks por projeto

`okeanos install --agent codex --project`, de dentro de um repositório git, junta os hooks do Okeanos ao `.codex/hooks.json` do projeto (os hooks que o projeto já tinha ficam; `--project --uninstall` tira só os do Okeanos). A confiança é pedida no fim, como nos hooks de usuário (depois: `okeanos codex-confiar --project`); ela fica no `hooks.state` do `config.toml` do usuário. O Codex só carrega o `.codex/` de pastas confiáveis: se a raiz do repositório ainda não é, vem uma segunda pergunta [s/N], separada, para marcá-la como confiável (`projects."<raiz>".trust_level = "trusted"`, a mesma escrita do "Trust this folder" do Codex; isso também faz o Codex carregar o resto do `.codex/` do repositório). Essa pergunta é sempre feita, também com `--sim`. Com `N`, nada é escrito; num worktree ligado (o Codex guarda a confiança na pasta principal) ela não é oferecida. A desinstalação nunca tira a confiança da pasta. Commite `.codex/hooks.json` se o time deve compartilhar os hooks (os caminhos apontam para o seu clone do Okeanos). Não use junto com os hooks de usuário: rodariam duas vezes, e o instalador avisa.

### Orca

Sob o Orca, o `CODEX_HOME` é uma pasta que o Orca regenera (tem o arquivo `.orca-managed-home`) e reescreve `hooks.json` e `config.toml` a cada partida, então hooks de usuário somem. Nesse caso `okeanos install` não escreve hooks de usuário (ignora `--codex-hooks` e remove o bloco do `config.toml` de instalações antigas), instala skills e o bloco do `AGENTS.md`, que sobrevivem, e manda instalar os hooks por projeto: rode `okeanos install --agent codex --project` em cada projeto. A confiança dos hooks de projeto fica no `config.toml` do `CODEX_HOME` do Orca e sobreviveu à regeneração nos testes ao vivo; se o Codex voltar a pedir revisão, rode `okeanos codex-confiar --project` de novo. `okeanos doctor` mostra se o Codex é gerenciado pelo Orca e se o repositório atual tem os hooks do projeto.

## Copilot

Hooks em `~/.copilot/hooks/okeanos.json` (um arquivo só do Okeanos) e o bloco do processo em `~/.copilot/copilot-instructions.md` (`$COPILOT_HOME`, padrão `~/.copilot`). Reinicie o Copilot CLI depois de instalar ou atualizar. Se `~/.copilot/settings.json` tiver `disableAllHooks: true`, o instalador avisa. Com a sandbox de sessão do Copilot ligada, inclua o clone do Okeanos em `sandbox.userPolicy`, ou os hooks falham.

## Cursor

Detectado por `cursor`, `cursor-agent` ou pela pasta `~/.cursor`. Hooks em `~/.cursor/hooks.json`. O Cursor não tem arquivo para regras globais, então o processo entra por projeto: na raiz de cada repositório, rode `okeanos install --agent cursor --project`, que escreve `.cursor/rules/okeanos.mdc` (`alwaysApply: true`); commite o arquivo ou ponha no `.gitignore`, e rode de novo depois de atualizar o Okeanos (`--project --uninstall` remove). Outra opção é colar [`adapters/agents-md/okeanos.md`](../adapters/agents-md/okeanos.md) em Customize → Rules. Confira em Cursor Settings → Hooks que os hooks aparecem.

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

## Limitações por agente

- Copilot e Cursor não tiveram nenhuma sessão real com o Okeanos: os dialetos foram testados com payloads montados a partir da documentação. Partes do formato são inferidas:
  - Copilot: os argumentos das ferramentas de edição (`edit`, `create`, `str_replace_editor`) não estão documentados, então o dialeto aceita as duas grafias; o `agentStop` não traz a última mensagem, e o dialeto a procura no transcript, cujo formato não é documentado.
  - Cursor: o `tool_input` das ferramentas de arquivo (`StrReplace`, `path` ou `file_path`, `content`) vem de relatos, não da documentação; o que o dialeto não consegue ler conta como reescrita do arquivo inteiro. A variável `CURSOR_AGENT`, usada para recusar `okeanos aprovar` no shell do agente, também não é documentada.
- O Copilot não põe no shell das ferramentas uma variável que identifique a sessão; ali, a recusa de `okeanos aprovar` depende só da exigência de terminal interativo e do bloqueio pelos hooks.
- No Cursor, os hooks do Cursor CLI ficam de fora; o alvo é o agente do Cursor IDE.
- Sem `python3`, o processo continua e os hooks ficam desligados. Offline, a checagem de pacotes não bloqueia.
