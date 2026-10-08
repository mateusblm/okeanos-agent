Este repo é o plugin **Okeanos** do Claude Code. Veja `README.md`.

- O processo vive em `output-styles/okeanos.md`. Mudanças de rota, gates ou regras vão lá.
- `hooks/onboard-check.sh` (SessionStart) avisa quando o repo não tem `CLAUDE.md` ou `docs/agents/checks.json`; a skill `onboard` cria os dois.
- Os hooks determinísticos (pre-bash, pre-edit, post-edit, stop) entram por `hooks/okeanos.py`, chamado via `hooks/run --agent <agente>`. As regras ficam em `hooks/okeanos_engine/rules.py` e não conhecem agente; cada agente tem um dialeto em `hooks/okeanos_engine/dialects/` que traduz o payload para o evento normalizado e a decisão para a saída dele. Só biblioteca padrão do Python; qualquer erro interno vira "permitir", nunca bloqueio. Rode `python3 -m pytest -q` antes de commitar mudanças no motor.
- As skills em `skills/` são do Okeanos e se editam direto. Ao adicionar, remover ou renomear uma skill, atualize o array `skills` em `.claude-plugin/plugin.json`, a lista em `README.md` e o mapa em `skills/engineering/ask-okeanos/SKILL.md`.
- Skills que o Okeanos chama sozinho não têm `disable-model-invocation`. Skills manuais têm `disable-model-invocation: true`.
- Dependências entre skills: escreva `call the Skill tool with "<nome>"`, nunca links entre pastas de skills.
- O formato de ticket local (`**Status:**`, `**Blocked by:**` com números de dois dígitos) é lido por `skills/engineering/afk/scaffold/main.mts`. Mudou um, mude o outro.
- Mudanças no processo seguem `docs/manutencao.md`: adicionar ou podar uma etapa por vez, medindo com `hooks/run metrics`.
- Depois de mexer nos manifests, rode `claude plugin validate .claude-plugin/plugin.json --strict` e `claude plugin validate . --strict`.
