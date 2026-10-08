# 05: Adaptador Codex e instalador

**What to build:** o dialeto do Codex (hooks com nomes e campos do Codex; "perguntar" vira "negar" com a instrução de `okeanos aprovar`; Stop bloqueável) e o instalador único: detecta agentes, instala skills no diretório lido nativamente, o bloco de processo nas instruções globais, os hooks na config de usuário e a CLI no PATH. Idempotente, preserva conteúdo do usuário, faz backup e tem desinstalação. No Claude Code, delega ao marketplace.

**Blocked by:** 01, 02, 03, 04

**Wave:** 3

**Status:** ready-for-agent

- [ ] Quando o instalador roda, o sistema deve instalar só nos agentes encontrados e listar o que instalou.
- [ ] Quando o instalador roda de novo, o sistema deve chegar ao mesmo estado (idempotente).
- [ ] Se a config existente tem conteúdo do usuário, então o sistema deve editar só o bloco marcado do Okeanos.
- [ ] Se a config existente for inválida, então o sistema deve parar sem alterá-la e dizer qual arquivo.
- [ ] Quando o Codex tenta alterar asserção de teste commitado, o sistema deve negar e indicar `okeanos aprovar <arquivo>`.
- [ ] Quando o Codex vai encerrar com testes falhando, o sistema deve impedir o encerramento.
