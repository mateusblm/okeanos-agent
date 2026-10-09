# 06: Git hooks por projeto

**What to build:** `okeanos githooks` instala pre-commit (segredos, asserções alteradas em teste commitado sem aprovação) e pre-push (comandos `onDone`) no repositório atual, encadeando hooks existentes.

**Blocked by:** 04

**Wave:** 3

**Status:** ready-for-agent

- [ ] Quando o usuário roda `okeanos githooks`, o sistema deve instalar pre-commit e pre-push.
- [ ] Se o repositório já tem hooks próprios, então o sistema deve encadeá-los em vez de sobrescrever.
- [ ] Se o commit contém segredo, então o pre-commit deve falhar mostrando só arquivo e tipo.
