# 01: Skill `performance`

**What to build:** skill nova `skills/engineering/performance/` (SKILL.md com o ciclo medir → identificar → corrigir → verificar → proteger, uma mudança por vez, ganho acima da variância, "neutro é revert", registro de tentativas e honestidade de métrica) com `PATTERNS.md` (backend: N+1, `EXPLAIN` antes de índice, pool, chave de cache e staleness; frontend: CWV, imagens, code splitting) e o checklist de benchmark (número com unidade, rodadas, faixa, limitador). Ligações: ramo de desempenho do `diagnosing-bugs`, linha de bundle do G2 e orçamento do `to-spec`. `plugin.json`, README. Crédito: agent-skills (performance-optimization, web-performance-auditor) e pstack (perf-issue, benchmark-checklist).

**Blocked by:** None

**Wave:** 1

**Status:** ready-for-agent

- [ ] Quando a demanda é de desempenho, o sistema deve seguir o ciclo com re-medição nas mesmas condições.
- [ ] Se não há medição real, então o sistema não deve dar número ("impacto potencial").
- [ ] Quando o `diagnosing-bugs` cai no ramo de desempenho, deve encaminhar para `performance`.
