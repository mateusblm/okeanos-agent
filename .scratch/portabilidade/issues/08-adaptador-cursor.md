# 08: Adaptador Cursor

**What to build:** dialeto do Cursor IDE (campo `permission`; "perguntar" vira "negar" com `okeanos aprovar`; `stop` com `followup_message`) e o passo do instalador para o Cursor (skills, regras, hooks de usuário), com os caminhos conferidos na documentação oficial.

**Blocked by:** 05

**Wave:** 4

**Status:** ready-for-agent

- [ ] Quando o Cursor tenta alterar asserção de teste commitado, o sistema deve negar e indicar `okeanos aprovar <arquivo>`.
- [ ] Quando o Cursor vai encerrar com testes falhando, o sistema deve devolver a falha como mensagem de continuação.
- [ ] Se o Cursor não tiver onde instalar as regras globais, então o instalador deve dizer como ativar por projeto.
