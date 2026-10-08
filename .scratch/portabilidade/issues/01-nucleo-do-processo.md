# 01: Núcleo do processo e output style gerado

**What to build:** o texto do processo sai do output style do Claude e vira um texto neutro no núcleo. Um gerador produz o output style do Claude Code (texto + frontmatter) e o bloco de instruções para os outros agentes. A verificação de pronto do repositório falha se um gerado estiver desatualizado. O plugin do Claude continua instalável do mesmo marketplace, com o manifesto apontando para os caminhos novos.

**Blocked by:** None

**Wave:** 1

**Status:** ready-for-agent

- [ ] O sistema deve gerar o output style do Claude Code e o bloco de instruções dos outros agentes a partir de um único texto de processo.
- [ ] Se um adaptador gerado estiver diferente do que o núcleo produziria, então a verificação de pronto deste repositório deve falhar.
- [ ] Quando o plugin do Claude Code é instalado depois da reorganização, o sistema deve se comportar como antes (mesmo output style, skills e hooks).
