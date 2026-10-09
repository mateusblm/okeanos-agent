# 02: Motor de verificações com dialetos (paridade Claude Code)

**What to build:** as regras dos hooks ficam independentes do agente, com um evento e uma decisão normalizados, e o Claude Code vira o primeiro dialeto. A bateria de casos atual vira uma suíte de testes versionada que passa sem mudança de comportamento. Os eventos de métricas ganham o nome do agente.

**Blocked by:** None

**Wave:** 1

**Status:** ready-for-agent

- [ ] Quando o Claude Code chama qualquer hook com os payloads atuais, o sistema deve responder exatamente como antes (suíte de paridade).
- [ ] O sistema deve registrar o nome do agente em cada evento de métrica.
- [ ] Se o payload vier de um agente desconhecido, então o sistema deve permitir a ação sem erro (fail-open, como hoje).
