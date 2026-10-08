Este repo é o plugin **Okeanos** do Claude Code. Veja `README.md`.

- O processo vive em `core/process.md`, neutro em relação ao agente (descreva capacidades, não nomes de ferramentas do Claude Code). Mudanças de rota, gates ou regras vão lá; depois rode `python3 scripts/build.py`. `output-styles/okeanos.md` (frontmatter do Claude em `scripts/build.py`) e `adapters/agents-md/okeanos.md` são gerados: nunca edite à mão. `python3 scripts/build.py --check` falha se algum estiver desatualizado.
- Testes em `tests/`, rodados com `python3 -m pytest -q` da raiz.
- `hooks/onboard-check.sh` (SessionStart) avisa quando o repo não tem `CLAUDE.md` ou `docs/agents/checks.json`; a skill `onboard` cria os dois.
- `hooks/okeanos.py` concentra os hooks determinísticos (pre-bash, pre-edit, post-edit, stop), chamados via `hooks/run`. Só biblioteca padrão do Python; qualquer erro interno vira "permitir", nunca bloqueio. Teste mudanças nele com entradas JSON simuladas antes de commitar.
- As skills em `skills/` são do Okeanos e se editam direto. Ao adicionar, remover ou renomear uma skill, atualize o array `skills` em `.claude-plugin/plugin.json`, a lista em `README.md` e o mapa em `skills/engineering/ask-okeanos/SKILL.md`.
- Skills que o Okeanos chama sozinho não têm `disable-model-invocation`. Skills manuais têm `disable-model-invocation: true`.
- Dependências entre skills: escreva `call the Skill tool with "<nome>"`, nunca links entre pastas de skills.
- O formato de ticket local (`**Status:**`, `**Blocked by:**` com números de dois dígitos) é lido por `skills/engineering/afk/scaffold/main.mts`. Mudou um, mude o outro.
- Mudanças no processo seguem `docs/manutencao.md`: adicionar ou podar uma etapa por vez, medindo com `hooks/run metrics`.
- Depois de mexer nos manifests, rode `claude plugin validate .claude-plugin/plugin.json --strict` e `claude plugin validate . --strict`.
