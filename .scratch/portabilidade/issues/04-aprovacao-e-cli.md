# 04: CLI `okeanos` e aprovações

**What to build:** uma CLI `okeanos` com `aprovar`, `metrics`, `githooks` (stub até o ticket 06) e `doctor`. `okeanos aprovar <alvo>` libera aquele alvo por 10 minutos, só em terminal interativo. O motor consulta as aprovações antes de negar, e bloqueia o agente que tenta rodar `okeanos aprovar` ou escrever no estado do Okeanos.

**Blocked by:** 02

**Wave:** 2

**Status:** ready-for-agent

- [ ] Quando o usuário roda `okeanos aprovar <alvo>` num terminal interativo, o sistema deve liberar aquele alvo por 10 minutos.
- [ ] Se `okeanos aprovar` for executado sem terminal interativo, então o sistema deve recusar a aprovação.
- [ ] Se o agente tentar rodar `okeanos aprovar` ou escrever no estado do Okeanos, então o sistema deve bloquear o comando.
- [ ] Se a aprovação expirou ou o alvo difere, então o sistema deve tratar como não aprovado.
