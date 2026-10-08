# 09: AFK com agente configurável

**What to build:** o runner do AFK aceita Claude Code, Codex, Copilot ou Cursor como agente das sandboxes, usando a fábrica correspondente do Sandcastle, com o Dockerfile instalando o CLI escolhido.

**Blocked by:** None

**Wave:** 1

**Status:** ready-for-agent

- [ ] Onde o AFK estiver configurado com outro agente, o sistema deve usar a fábrica correspondente do Sandcastle.
- [ ] Se o agente configurado não for suportado, então o sistema deve falhar na partida com a lista dos suportados.
