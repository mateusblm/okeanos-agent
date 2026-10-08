# 03: Skills neutras

**What to build:** as skills deixam de depender de nomes de ferramentas do Claude Code. "Call the Skill tool with X" vira "use the `X` skill", e menções a ferramentas exclusivas viram descrições de capacidade (subagente, pergunta ao usuário). O comportamento no Claude Code não muda.

**Blocked by:** None

**Wave:** 1

**Status:** ready-for-agent

- [ ] Se uma skill citar uma ferramenta exclusiva de um agente, então o texto deve trazer uma forma neutra que funcione nos outros.
- [ ] Quando o Claude Code roda o fluxo de Feature numa sessão real, as skills devem continuar sendo chamadas na ordem do processo.
