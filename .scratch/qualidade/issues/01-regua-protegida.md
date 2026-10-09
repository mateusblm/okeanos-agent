# 01: Régua protegida (checks.json)

**What to build:** afrouxar o `docs/agents/checks.json` commitado (remover ou alterar comando de `onDone`/`onEdit`, aumentar `maxChangedLines`, reescrever ou apagar pelo shell) passa a pedir aprovação, com alvo `docs/agents/checks.json`. Acrescentar comandos ou apertar o limite fica livre.

**Blocked by:** None

**Wave:** 1

**Status:** ready-for-agent

- [ ] Quando o agente remove ou altera um comando, ou aumenta `maxChangedLines`, o sistema deve pedir aprovação.
- [ ] Quando o agente só acrescenta comando ou diminui o limite, o sistema deve permitir.
- [ ] Se o agente reescreve ou apaga o arquivo pelo shell, então o sistema deve pedir aprovação.
- [ ] Se o arquivo não está commitado, então o sistema deve permitir.
