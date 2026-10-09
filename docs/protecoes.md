# Proteções do Okeanos

Como funcionam as aprovações, os hooks, os git hooks e o CI. Para o resumo, veja o [README](../README.md#aprovações).

## Aprovações

Onde o agente consegue pedir confirmação (veja a [tabela de suporte](agentes.md#o-que-cada-agente-suporta)), o Okeanos pergunta. Onde não consegue, bloqueia e termina a mensagem com `Para aprovar: okeanos aprovar <alvo>`. Rode esse comando no seu terminal e peça ao agente para tentar de novo:

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
- remover ou contornar os git hooks (`okeanos githooks --uninstall`, escrita em `.git/hooks`, troca de `core.hooksPath`) e os hooks do projeto com entradas do Okeanos (`.codex/hooks.json`, `.cursor/hooks.json`, `.cursor/rules/okeanos.mdc`, `.github/hooks/`), além de `okeanos install --uninstall`;
- autorizar os hooks do Codex (`okeanos codex-confiar`).

Segredos, force push, `--no-verify`, `rm -r` fora do repositório e pacote inexistente nunca são aprováveis.

Quão forte é essa barreira depende do agente. No Claude Code e no Copilot CLI (fora da nuvem e sem `COPILOT_ALLOW_ALL`), a aprovação é a confirmação do próprio programa do agente: uma barreira real, fora do alcance do modelo. No Codex e no Cursor, quem aprova é o `okeanos aprovar`, e as checagens acima barram atalhos e reward hacking acidental. Um agente que roda como o mesmo usuário do sistema operacional poderia, em princípio, escrever um script novo para contorná-las. Nesse caso, o hook de fim de turno, os git hooks (`okeanos githooks`) e o CI continuam como barreiras seguintes.

## Hooks

Os hooks entram por [`hooks/run`](../hooks/run) `--agent <agente> <hook>`, que chama [`hooks/okeanos.py`](../hooks/okeanos.py). No Claude Code, estão em [`hooks/hooks.json`](../hooks/hooks.json); nos outros, o instalador os escreve na configuração de usuário (no Codex sob o Orca, ou com `--project`, no `.codex/hooks.json` do projeto). Os nomes de evento variam por agente ([tabela de suporte](agentes.md#o-que-cada-agente-suporta)); o comportamento é o mesmo:

| Momento | Comportamento |
| :- | :- |
| Início da sessão | Pede o `okeanos-onboard` se faltar arquivo de contexto ou `checks.json`. Registra o commit inicial da sessão. |
| Primeira mensagem | Lembra o agente de classificar e anunciar a rota. |
| Antes de um comando no shell | Exige aprovação para push, PR e merge na branch padrão. Bloqueia `--no-verify`, force push e `rm -r` fora do repo. Bloqueia commit com segredo. Checa pacotes no registry. Exige aprovação para escritas do shell em testes commitados. |
| Antes de uma edição | Exige aprovação para alterar, remover ou desligar asserções de testes commitados, e para afrouxar o `docs/agents/checks.json` commitado: tirar ou mudar comando de `onDone`/`onEdit`, subir ou tirar `maxChangedLines`, tirar `testPatterns`, JSON inválido; acrescentar ou apertar é livre, e pelo shell qualquer escrita nele pede (alvo `docs/agents/checks.json`). |
| Depois de uma edição | Roda os comandos `onEdit` no arquivo editado e devolve as falhas ao agente. |
| Fim do turno | Roda os comandos `onDone`. Aponta testes apagados, asserções removidas, testes desligados e supressões novas de lint ou tipo. Avisa o usuário, uma vez e sem bloquear, de configs de qualidade afrouxadas na sessão (tsconfig `strict`, regra de lint desligada, ignore maior, limite de cobertura menor, `checks.json` afrouxado por qualquer caminho) e de stubs ou `catch`/`except` vazios em código novo fora dos testes. Avisa quando o diff passa de `maxChangedLines`. |

Qualquer erro interno de um hook vira "permitir", nunca bloqueio. Cada bloqueio, pedido de aprovação e falha é registrado em `.git/okeanos/metrics.jsonl`, com o nome do agente. Quando a pasta do git é só leitura (a sandbox do Codex), o estado da sessão e as métricas vão para a reserva em `<TMPDIR>/okeanos/`; as aprovações ficam sempre em `.git/okeanos/`.

## Git hooks

`okeanos githooks`, rodado dentro de um repositório, instala dois git hooks que valem para qualquer agente e para quem commita à mão:

| Hook | Comportamento |
| :- | :- |
| `pre-commit` | Falha se o stage tem segredo (mostra arquivo e tipo) ou arquivo `.env` novo. Falha se um teste já commitado perde ou muda asserções ou casos, ou ganha `skip`, sem aprovação ativa; a mensagem termina com `Para aprovar: okeanos aprovar <arquivo>`. Reformatar e adicionar testes passam. Supressões novas só geram aviso. |
| `pre-push` | Roda os comandos `onDone` de `docs/agents/checks.json` e falha mostrando o comando e o fim da saída. Sem `checks.json`, avisa e deixa passar. |

Os hooks vão para a pasta que o git usa (`core.hooksPath`, ou `.git/hooks` do repositório principal, também a partir de um worktree) e chamam `bin/okeanos` pelo caminho absoluto de quando foram instalados; se o Okeanos mudar de lugar, rode `okeanos githooks` de novo. Um hook que já existia vira `<nome>.okeanos-prev` e roda antes. `okeanos githooks --uninstall` remove só os hooks do Okeanos e devolve os anteriores. Sem `python3`, os hooks avisam e deixam passar. `git commit --no-verify` pula os hooks: é uma escolha do humano, já que os hooks do agente negam `--no-verify`.

## CI

Em repositórios com remote no GitHub, o `okeanos-setup` oferece um workflow (`.github/workflows/okeanos-checks.yml`) que roda os comandos `onDone`, um scan de segredos com gitleaks e Semgrep no código alterado. Tornar esses jobs obrigatórios na branch protection fica com você.
