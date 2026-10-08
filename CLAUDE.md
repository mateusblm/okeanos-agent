Este repo é o plugin **Okeanos** do Claude Code. Veja `README.md`.

- O processo vive em `output-styles/okeanos.md`. Mudanças de rota, gates ou regras vão lá.
- `hooks/onboard-check.sh` (SessionStart) avisa quando o repo não tem `CLAUDE.md` ou `docs/agents/checks.json`; a skill `onboard` cria os dois.
- `hooks/okeanos.py` concentra os hooks determinísticos (pre-bash, pre-edit, post-edit, stop), chamados via `hooks/run`. Só biblioteca padrão do Python; qualquer erro interno vira "permitir", nunca bloqueio. Teste mudanças nele com entradas JSON simuladas antes de commitar.
- As skills em `skills/` são do Okeanos e se editam direto. Ao adicionar, remover ou renomear uma skill, atualize o array `skills` em `.claude-plugin/plugin.json`, a lista em `README.md` e o mapa em `skills/engineering/ask-okeanos/SKILL.md`.
- Skills que o Okeanos chama sozinho não têm `disable-model-invocation`. Skills manuais têm `disable-model-invocation: true`.
- Dependências entre skills: escreva ``use the `<nome>` skill`` (em sequência: ``use the `<a>` skill, then the `<b>` skill``; ao mesmo tempo: ``use the `<a>` skill and the `<b>` skill together``), nunca links entre pastas de skills. As skills rodam em Claude Code, Codex, Copilot e Cursor: nada de nome de ferramenta exclusiva (Skill/Agent/Task tool, AskUserQuestion, TodoWrite, `/clear`, `/compact`, `${CLAUDE_PLUGIN_ROOT}`); descreva a capacidade ("a subagent", "ask the user", "start a fresh context"). Nota só do Claude Code vai numa linha começando com "In Claude Code:". `tests/test_skills_neutral.py` confere (`python3 -m pytest -q`).
- O formato de ticket local (`**Status:**`, `**Blocked by:**` com números de dois dígitos) é lido por `skills/engineering/afk/scaffold/main.mts`. Mudou um, mude o outro.
- Mudanças no processo seguem `docs/manutencao.md`: adicionar ou podar uma etapa por vez, medindo com `hooks/run metrics`.
- Depois de mexer nos manifests, rode `claude plugin validate .claude-plugin/plugin.json --strict` e `claude plugin validate . --strict`.
