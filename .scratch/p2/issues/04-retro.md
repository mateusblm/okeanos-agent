# 04: Retro afiada

**What to build:** na `skills/engineering/retro/SKILL.md`: escada de onde corrigir (arquitetura > tipos > lint/check com mensagem que diz a correção > teste > docs), prova de que cada check novo falha num erro real do passado (commit, revert ou evento de métricas) e a tabela "regra → o que a aplica" em `docs/agents/regras.md` (criada pela retro quando não existe; regra sem aplicação que voltou a ser violada é achado). README (Configuração) cita o arquivo. Crédito: pstack (correct).

**Blocked by:** None

**Wave:** 1

**Status:** ready-for-agent

- [ ] A `retro` deve escolher a correção pela escada.
- [ ] Se não há erro real para provar o check, então a `retro` deve dizer isso.
- [ ] A `retro` deve manter `docs/agents/regras.md`.
