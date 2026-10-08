# Spec: Okeanos em Codex, Copilot e Cursor

**Status:** ready-for-agent

## Problem Statement

O Okeanos só funciona no Claude Code. O dono do projeto pretende usar também Codex, GitHub Copilot e Cursor, e hoje, nesses agentes, não tem o processo (rotas, gates), nem as skills adaptadas, nem as proteções (teste protegido, definição de pronto, pacotes, segredos, publicação). Copiar o plugin para cada agente multiplicaria o trabalho de manutenção por quatro.

## Solution

Um núcleo neutro e um adaptador fino por agente. O núcleo tem o texto do processo, as skills e o motor de verificações. Cada adaptador traduz o núcleo para o formato do agente: output style e hooks no Claude Code; `AGENTS.md`, skills em `.agents/skills` e hooks no formato próprio em Codex, Copilot e Cursor. Onde o hook do agente não consegue pedir aprovação, o Okeanos bloqueia e indica um comando que só o humano consegue rodar, `okeanos aprovar <alvo>`. Git hooks por projeto e o CI já existente formam a rede comum a qualquer agente. Um instalador único detecta os agentes da máquina e instala tudo na configuração de usuário de cada um.

## User Stories

1. Como dev, quero rodar um instalador e ter o Okeanos em todos os agentes que uso, para não configurar cada um à mão.
2. Como dev, quero que o instalador detecte quais agentes existem na máquina, para não instalar o que não uso.
3. Como dev, quero rodar o instalador de novo para atualizar, sem duplicar configuração.
4. Como dev, quero desinstalar de um agente específico ou de todos, para voltar ao estado anterior.
5. Como dev que usa Codex, quero o mesmo processo (rotas, G1, G2), para trabalhar igual em qualquer agente.
6. Como dev que usa Copilot, quero o mesmo processo.
7. Como dev que usa Cursor, quero o mesmo processo.
8. Como dev, quero as skills do Okeanos disponíveis e invocadas automaticamente em todos os agentes.
9. Como dev, quero que, em qualquer agente, editar asserção de teste commitado seja barrado até eu aprovar.
10. Como dev, quero aprovar uma ação barrada com um comando curto no meu terminal, que vale por pouco tempo e só para aquele alvo.
11. Como dev, quero que o próprio agente não consiga se autoaprovar.
12. Como dev, quero que, em qualquer agente, o agente não encerre com testes falhando quando mudou código.
13. Como dev, quero que, em qualquer agente, pacote inexistente seja barrado e pacote suspeito exija aprovação.
14. Como dev, quero que, em qualquer agente, commit com segredo seja barrado.
15. Como dev, quero que push, PR e merge na branch principal exijam a minha aprovação em qualquer agente.
16. Como dev, quero git hooks opcionais por projeto que valem para qualquer agente e para humanos.
17. Como usuário do Claude Code, quero que tudo continue funcionando exatamente como hoje depois da reorganização.
18. Como mantenedor, quero corrigir uma regra do processo num lugar só e ver a correção em todos os agentes.
19. Como mantenedor, quero detectar quando um adaptador gerado ficou desatualizado em relação ao núcleo.
20. Como dev, quero que o modo AFK possa rodar com Codex, Copilot ou Cursor dentro das sandboxes.
21. Como dev, quero que o README explique a instalação em cada agente e o que muda entre eles.
22. Como dev, quero que as métricas registrem eventos de todos os agentes no mesmo arquivo, para a retro comparar.

## Acceptance Criteria

**Instalador (1-4)**
- Quando o instalador roda, o sistema deve instalar só nos agentes encontrados e listar o que instalou em cada um.
- Quando o instalador roda pela segunda vez, o sistema deve deixar a configuração idêntica à de uma instalação única (idempotente).
- Se o arquivo de configuração de um agente já tem conteúdo do usuário, então o sistema deve preservar esse conteúdo e editar só o bloco marcado do Okeanos.
- Se um arquivo de configuração existente for JSON ou TOML inválido, então o sistema deve parar sem alterá-lo e dizer qual arquivo está quebrado.
- Quando o usuário roda a desinstalação, o sistema deve remover só o que o Okeanos instalou.
- Se nenhum agente suportado for encontrado, então o sistema deve dizer isso e terminar sem alterar nada.

**Processo (5-7, 17-19)**
- O sistema deve gerar o output style do Claude Code e o bloco de instruções dos outros agentes a partir de um único texto de processo.
- Se um adaptador gerado estiver diferente do que o núcleo produziria, então a verificação de pronto deste repositório deve falhar.
- Quando o plugin do Claude Code é instalado do marketplace depois da reorganização, o sistema deve se comportar como antes: mesmas skills, mesmo output style, mesmos hooks.

**Skills (8)**
- O sistema deve instalar as skills num diretório lido nativamente por Codex, Copilot e Cursor.
- Se uma skill citar uma ferramenta exclusiva de um agente, então o texto deve trazer uma forma neutra que funcione nos outros.

**Proteções e aprovação (9-15, 22)**
- Quando um agente tenta alterar ou remover asserção de teste commitado (pelo editor ou pelo shell), o sistema deve bloquear, ou pedir aprovação onde o agente suporta, e indicar `okeanos aprovar <arquivo>`.
- Quando o usuário roda `okeanos aprovar <alvo>` num terminal interativo, o sistema deve liberar aquele alvo por 10 minutos.
- Se `okeanos aprovar` for executado sem terminal interativo (como pelo agente), então o sistema deve recusar a aprovação.
- Se o agente tentar rodar `okeanos aprovar` ou escrever no arquivo de aprovações, então o sistema deve bloquear o comando.
- Se a aprovação expirou, então o sistema deve tratar o alvo como não aprovado.
- Quando o agente vai encerrar com código alterado e testes falhando, o sistema deve impedir o encerramento em Claude Code, Codex, Copilot e Cursor (com a linha de handoff valendo em todos).
- Se o agente instala pacote inexistente, então o sistema deve bloquear em qualquer agente.
- Se o commit contém segredo, então o sistema deve bloquear em qualquer agente.
- Quando o agente tenta push, PR ou merge na branch principal, o sistema deve exigir aprovação (nativa ou por `okeanos aprovar push`).
- O sistema deve registrar os eventos de todos os agentes no mesmo arquivo de métricas, com o nome do agente.

**Git hooks (16)**
- Quando o usuário roda `okeanos githooks` num repositório, o sistema deve instalar pre-commit (segredos, testes alterados) e pre-push (comandos de pronto).
- Se o repositório já tem hooks próprios, então o sistema deve encadear os existentes em vez de sobrescrevê-los.

**AFK (20)**
- Onde o AFK estiver configurado com outro agente, o sistema deve usar a fábrica de agente correspondente do Sandcastle.
- Se o agente configurado não for suportado pelo Sandcastle, então o sistema deve falhar na partida com a lista dos suportados.

**Docs (21)**
- O README deve ter a instalação de cada agente e uma tabela do que cada um suporta.

## Security

**Fronteiras:** agente → arquivo de aprovações; agente → configs de usuário dos agentes (instalador); hook → registries de pacotes.

| Ameaça (STRIDE) | Onde | Resposta | Critério |
| :- | :- | :- | :- |
| E: agente se autoaprova rodando `okeanos aprovar` | shell do agente | mitigar: exigir TTY interativo | Se rodado sem TTY, então recusa. |
| T: agente escreve direto no arquivo de aprovações | shell/editor do agente | mitigar: hook bloqueia escrita no caminho do estado do Okeanos | Se o agente escreve em `.git/okeanos/`, então bloqueia. |
| T: aprovação reaproveitada para outro alvo ou depois | estado local | mitigar: aprovação por alvo exato com expiração | Se o alvo difere ou expirou, então não vale. |
| T: instalador corrompe config do usuário | ~/.codex, ~/.copilot, ~/.cursor | mitigar: bloco marcado, backup, parse antes de escrever | Se o parse falha, então não escreve. |
| I: hook vaza conteúdo de arquivo em mensagem | saída do hook | mitigar: mensagens citam caminho e tipo, nunca o segredo | Se acha segredo, então a mensagem mostra só arquivo e tipo. |

## Implementation Decisions

- **Núcleo e adaptadores.** O núcleo tem três partes: o texto do processo (neutro em relação ao agente), as skills e o motor de verificações. Os adaptadores são gerados ou finos: o output style do Claude Code é o texto do processo com o frontmatter do Claude; os outros recebem o mesmo texto num bloco marcado de instruções.
- **O plugin do Claude Code continua instalável do mesmo marketplace**, com o manifesto apontando para os caminhos novos. Comandos de instalação dos usuários atuais não mudam.
- **Motor de verificações com dialetos.** As regras (teste protegido, pronto, pacotes, segredos, publicação, supressões, métricas) ficam independentes do agente. Cada dialeto traduz a entrada do agente (nomes de evento, campos, ferramentas de edição e shell) para um evento normalizado, e a decisão normalizada (permitir, perguntar, negar, bloquear o fim) para a saída do agente. Onde o agente não tem "perguntar", a decisão vira "negar" com a instrução de `okeanos aprovar`.
- **Aprovações.** Guardadas no estado local do repositório (mesma área das métricas), por alvo exato e com expiração de 10 minutos. Consultadas antes de negar. A CLI `okeanos` exige TTY para aprovar.
- **CLI `okeanos`.** Um ponto de entrada com subcomandos: `aprovar`, `metrics`, `githooks`, `doctor` (mostra o que está instalado onde). O instalador coloca a CLI no PATH do usuário.
- **Instalador.** Um script único, idempotente, que detecta Claude Code, Codex, Copilot e Cursor, instala na configuração de usuário de cada um, edita só blocos marcados, faz backup e tem desinstalação. No Claude Code, delega ao marketplace.
- **Skills neutras.** A redação "call the Skill tool with X" vira uma forma neutra ("use the `X` skill"), e menções a ferramentas exclusivas viram descrições de capacidade (ex.: "subagent").
- **Git hooks** por projeto via `okeanos githooks`, encadeando hooks existentes.
- **AFK** passa a ter o agente configurável entre os que o Sandcastle suporta.
- **Gemini** fica fora.
- Os caminhos exatos de config de usuário de cada agente vêm da pesquisa de 08/10/2026 e são verificados em cada ticket de adaptador contra a documentação oficial.

## Testing Decisions

- **Seam principal: a CLI do motor.** Os testes entregam um payload no formato documentado de cada agente na entrada e conferem a saída no formato daquele agente. Uma bateria de cenários (teste protegido via editor e via shell, pronto, pacote inexistente, segredo, push, aprovação válida, expirada e sem TTY) roda contra os quatro dialetos. É o mesmo estilo de teste usado até aqui com entradas simuladas, agora versionado no repositório.
- **Instalador:** roda contra um HOME temporário, e os testes conferem os arquivos gerados, a idempotência, a preservação de conteúdo do usuário e a desinstalação.
- **Git hooks:** repositório git temporário, commit e push de verdade.
- **Paridade do Claude Code:** a bateria atual de casos, já validada, passa sem mudança de comportamento.
- **Ponta a ponta:** uma sessão real no Codex (o único instalado na máquina). Copilot e Cursor ficam cobertos pelos testes de dialeto com payloads da documentação.
- Bons testes aqui olham só entrada e saída da CLI e arquivos no disco, nunca funções internas.

## Out of Scope

- Gemini CLI e Antigravity CLI.
- opencode (hooks só via plugin JS).
- Plugins nativos de marketplace para Codex, Copilot e Cursor (a instalação é pelo instalador único).
- Hooks do Cursor CLI (instáveis segundo a documentação); o alvo é o Cursor IDE.
- Testes ponta a ponta reais em Copilot e Cursor (não instalados nesta máquina).

## Further Notes

- Copilot na nuvem trata "perguntar" como "negar"; o fluxo de `okeanos aprovar` cobre esse caso.
- O AFK continua exigindo Node e Docker.

## Open Questions

Nenhuma.
