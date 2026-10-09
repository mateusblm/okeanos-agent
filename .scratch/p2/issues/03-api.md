# 03: Referência de API pública (`codebase-design/API.md`)

**What to build:** `skills/engineering/codebase-design/API.md` (lei de Hyrum e One-Version, formato único de erro e mapeamento de status, validação na fronteira e resposta de terceiro como não confiável, mudanças aditivas, paginação desde o início, idempotency key: derivada da intenção, claim atômico por constraint única, hash do payload, decisão para duplicata em voo, retenção maior que a cadeia de retries). O `codebase-design`, o `grill-with-docs` e o `threat-model` consultam quando a mudança toca contrato público; a pré-checagem do G1 em `core/process.md` ganha o item condicional; rebuild. Crédito: agent-skills (api-and-interface-design).

**Blocked by:** None

**Wave:** 1

**Status:** ready-for-agent

- [ ] Quando a mudança toca contrato público, o alinhamento deve consultar `API.md`.
- [ ] Quando a mudança toca contrato público, a pré-checagem do G1 deve ter o item de API.
- [ ] Se a mudança quebra compatibilidade, então o G1 deve dizer isso e propor caminho aditivo ou de versão.
