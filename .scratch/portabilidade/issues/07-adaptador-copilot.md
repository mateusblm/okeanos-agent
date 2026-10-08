# 07: Adaptador Copilot

**What to build:** dialeto do Copilot (CLI, formato `version:1` com campos camelCase; "perguntar" nativo no CLI e "negar" na nuvem) e o passo do instalador para o Copilot (skills, instruções, hooks de usuário), com os caminhos conferidos na documentação oficial.

**Blocked by:** 05

**Wave:** 4

**Status:** ready-for-agent

- [ ] Quando o Copilot tenta alterar asserção de teste commitado, o sistema deve pedir aprovação (CLI) ou negar com `okeanos aprovar` (nuvem).
- [ ] Quando o instalador encontra o Copilot, o sistema deve instalar skills, instruções e hooks dele.
- [ ] Se o payload do Copilot vier no formato com nomes PascalCase, então o sistema deve tratá-lo também.
