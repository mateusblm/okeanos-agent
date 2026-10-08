Este repo é o plugin **Okeanos** do Claude Code. Veja `README.md`.

- O processo vive em `output-styles/okeanos.md`. Mudanças de rota, gates ou regras vão lá.
- As skills em `skills/` são do Okeanos e se editam direto. Ao adicionar, remover ou renomear uma skill, atualize o array `skills` em `.claude-plugin/plugin.json`, a lista em `README.md` e o mapa em `skills/engineering/ask-okeanos/SKILL.md`.
- Skills que o Okeanos chama sozinho não têm `disable-model-invocation`. Skills manuais têm `disable-model-invocation: true`.
- Dependências entre skills: escreva `call the Skill tool with "<nome>"`, nunca links entre pastas de skills.
- O formato de ticket local (`**Status:**`, `**Blocked by:**` com números de dois dígitos) é lido por `skills/engineering/afk/scaffold/main.mts`. Mudou um, mude o outro.
- Depois de mexer nos manifests, rode `claude plugin validate .claude-plugin/plugin.json --strict` e `claude plugin validate . --strict`.
