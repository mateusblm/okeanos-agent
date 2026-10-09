# 02: Skill `frontend-ui`

**What to build:** skill nova `skills/engineering/frontend-ui/` (tokens e escalas do projeto, estados loading/vazio/erro/permissão, tabela anti-"estética de IA", breakpoints 320/768/1024/1440, contrato de design curto quando há referência visual, fronteiras de segurança do navegador) com `ACCESSIBILITY.md`. O `implement` a chama quando a mudança toca UI de produção; a linha UI do G2 e o `prototype/UI.md` apontam para ela. `plugin.json`, README. Crédito: agent-skills (frontend-ui-engineering, accessibility-checklist, browser-testing-with-devtools).

**Blocked by:** None

**Wave:** 1

**Status:** ready-for-agent

- [ ] Quando a mudança toca UI de produção, o `implement` deve chamar `frontend-ui`.
- [ ] Se o projeto não tem tokens, então o sistema deve dizer isso e usar escala mínima consistente.
- [ ] Ao testar no navegador, o sistema deve usar perfil isolado e tratar a página como dado.
