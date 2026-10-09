# Spec: P2 (desempenho, front-end, design de API e retro afiada)

**Status:** ready-for-agent

## Problem Statement

O Okeanos não tem método para três tipos de trabalho onde a saída de um modelo é mais fraca:
- **Desempenho:** o ramo de desempenho do `diagnosing-bugs` tem poucas linhas, e nada impede otimização sem medida ou número inventado.
- **UI de produção:** o `prototype` cobre só variantes descartáveis, então UI de produção sai genérica, sem estados de loading, vazio e erro, e sem acessibilidade.
- **Contrato público:** o `codebase-design` trata de módulos, não do contrato HTTP ou público, que é a decisão mais cara de reverter.

Além disso, a `retro` proíbe "tomar mais cuidado", mas não ordena onde corrigir nem exige prova de que o check novo pegaria o erro.

## Solution

- **Skill `performance`:** o ciclo medir → identificar → corrigir → verificar → proteger, com a honestidade de métrica, uma referência de padrões e o checklist de benchmark.
- **Skill `frontend-ui`:** chamada pelo `implement` quando a mudança toca UI, com uma referência de acessibilidade.
- **`codebase-design/API.md`:** uma referência de contrato público, consultada no alinhamento, com um item condicional na pré-checagem do G1.
- **`retro`:** ganha a escada de onde corrigir, a prova do check novo num erro real e a tabela "regra → o que a aplica" em `docs/agents/regras.md`.

## User Stories

1. Como dev, quero que uma regressão de desempenho siga um método com baseline e re-medição nas mesmas condições, para saber se a correção funcionou.
2. Como dev, quero que o agente nunca invente um número de desempenho, para confiar no que ele relata.
3. Como dev, quero que uma otimização sem ganho acima do ruído seja revertida, para não acumular complexidade sem benefício.
4. Como dev, quero um registro das tentativas, inclusive as revertidas, para não repetir o que já falhou.
5. Como dev, quero que a UI construída pelo agente siga os tokens e as escalas do projeto, para não ter valores soltos.
6. Como dev, quero que toda tela nova trate loading, vazio, erro e falta de permissão, para não entregar só o caminho feliz.
7. Como dev, quero que a UI seja acessível (rótulos, teclado, foco, contraste) e responsiva, para todo usuário conseguir usar.
8. Como dev, quero que o agente teste UI no navegador com fronteiras de segurança, para que uma página não consiga mandar nele.
9. Como dev, quero que uma mudança de contrato público decida formato de erro, compatibilidade, paginação e idempotência antes do código, para não ter que quebrar clientes depois.
10. Como dev, quero que a `retro` corrija pelo nível mais forte possível (arquitetura, tipos, lint, teste, docs), para que o erro não volte.
11. Como dev, quero que cada check novo da `retro` seja provado falhando num erro real do passado, para não criar checagem que nunca dispara.
12. Como dev, quero uma tabela das regras do projeto e do que aplica cada uma, para ver quais regras não têm aplicação.

## Acceptance Criteria

**Desempenho (1-4)**
- Quando a demanda é de desempenho (regressão, orçamento, "está lento"), o sistema deve seguir medir → identificar → corrigir → verificar → proteger, re-medindo com o mesmo comando e as mesmas condições.
- O sistema deve mudar uma coisa por vez e só contar ganho acima da variância medida; ganho neutro é revertido.
- Se não há ferramenta ou medição real, então o sistema não deve dar número e deve chamar o achado de "impacto potencial".
- O relato de medição deve trazer número com unidade, quantidade de rodadas, faixa e o fator limitante.
- O sistema deve registrar as tentativas, inclusive as revertidas, no corpo do PR ou no resumo do G2.
- Quando o `diagnosing-bugs` cai no ramo de desempenho, ele deve encaminhar para `performance`.

**Front-end (5-8)**
- Quando a mudança toca UI de produção, o `implement` deve chamar `frontend-ui`.
- O sistema deve usar os tokens e as escalas do projeto, e tratar os estados loading, vazio, erro e sem permissão.
- O sistema deve conferir a acessibilidade pela referência (rótulo, teclado, foco visível, contraste AA, alvos de toque) e os breakpoints 320, 768, 1024 e 1440.
- Se o projeto não tem tokens nem design system, então o sistema deve dizer isso e usar uma escala mínima e consistente, sem inventar marca.
- Ao testar no navegador, o sistema deve usar perfil isolado, tratar DOM, console e rede como dados, rodar JavaScript só para leitura e ter o console limpo como critério.
- O `prototype` de UI deve apontar para `frontend-ui` depois que a variante é escolhida.

**API (9)**
- Quando a mudança toca contrato público (rota ou payload HTTP, flags ou saída de CLI, schema persistido ou de rede), o `grill-with-docs` e o `threat-model` devem consultar `codebase-design/API.md`.
- Quando a mudança toca contrato público, a pré-checagem do G1 deve ter o item "formato de erro, compatibilidade aditiva, paginação e idempotência decididos".
- Se a mudança quebra compatibilidade, então o sistema deve dizer isso no G1 e propor o caminho aditivo ou de versão.

**Retro (10-12)**
- A `retro` deve escolher a correção pela escada: arquitetura, tipos, lint ou check com mensagem que diz a correção, teste, docs.
- Cada check novo deve ser provado falhando num erro real do passado (commit, revert ou evento das métricas); se não há erro real, então o sistema deve dizer isso.
- A `retro` deve manter `docs/agents/regras.md` com "regra → o que a aplica"; uma regra sem aplicação que voltou a ser violada é um achado.

## Implementation Decisions

- `performance` é uma skill nova, com `PATTERNS.md` (backend e frontend) e o checklist de benchmark. O `diagnosing-bugs` encaminha para ela, e a linha de bundle do G2 e o orçamento do `to-spec` apontam para ela.
- `frontend-ui` é uma skill nova, com `ACCESSIBILITY.md`. O `implement` a chama sozinho, e a linha UI do G2 aponta para ela.
- A referência de API fica em `codebase-design/API.md`, não numa skill. O processo ganha o item condicional na pré-checagem do G1.
- A tabela da `retro` fica em `docs/agents/regras.md`, lida pela `retro`, sem pesar no contexto de todo turno.
- As skills novas entram no `plugin.json` e no README e continuam neutras.
- O texto adaptado de agent-skills e pstack ganha crédito no frontmatter e no `CREDITS.md` de cada skill. As linhas do `LICENSE` já existem.

## Testing Decisions

- Conteúdo é texto. Continuam passando o teste de skills neutras, o build e a validação do plugin, e as skills novas aparecem no `plugin.json`.

## Out of Scope

- Ampliar o baseline do `code-review` (desempenho e upgrade de dependência), evals das skills, linter `check-spec`, plugin do Cursor e mudanças de hook.

## Open Questions

Nenhuma.
