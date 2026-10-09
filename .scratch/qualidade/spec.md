# Spec: qualidade (P0 e P1 dos estudos agent-skills e pstack)

**Status:** ready-for-agent

## Problem Statement

O agente consegue afrouxar a própria régua de qualidade editando `docs/agents/checks.json` sem aprovação, e a definição de pronto deixa de valer. Além disso, o G2 exige evidência de execução, mas os projetos não têm um roteiro para produzi-la; testes que não testam nada passam pela revisão; o review não olha o que quebra fora do diff; o `implement` não tem disciplina de fatias pequenas nem registro do que ficou de fora; e o processo não diz que conteúdo externo (docs buscadas, saída de CI, páginas) é dado e não instrução.

## Solution

Proteger a régua por hook; avisar no fim do turno quando configs de qualidade forem afrouxadas ou surgirem stubs e `catch` vazio; criar o roteiro `docs/agents/verificar.md` no `onboard` e usá-lo no `implement` e no G2; reforçar `tdd` e `code-review` contra testes ocos e acrescentar o raio de impacto ao review; dar ao `implement` disciplina incremental; e acrescentar ao processo a regra de conteúdo externo como dado e de conferir APIs na documentação da versão usada.

## User Stories

1. Como dev, quero que o agente não consiga tirar um comando do "pronto" sem a minha aprovação, para a definição de pronto continuar valendo.
2. Como dev, quero que o agente possa acrescentar checagens ao `checks.json` sem me perguntar, para a régua ficar mais exigente sem atrito.
3. Como dev, quero ser avisado quando o agente afrouxar configs de lint, tipo ou cobertura, para decidir se aceito.
4. Como dev, quero ser avisado quando aparecerem stubs ou `catch` vazio no código novo, para não entregar código fingindo que funciona.
5. Como dev, quero um roteiro por projeto de como subir, checar e exercitar a aplicação, para a evidência do G2 ser sempre produzida do mesmo jeito.
6. Como dev, quero que o `implement` use esse roteiro em mudanças visíveis, para eu ver a feature funcionando, não só testes verdes.
7. Como dev, quero que o review aponte testes que passariam com a implementação vazia, para não confiar em testes ocos.
8. Como dev, quero que o review mostre o que pode quebrar fora do diff quando a mudança toca código compartilhado.
9. Como dev, quero que o `implement` entregue em fatias pequenas que compilam, um commit por fatia, para eu revisar e reverter em pedaços.
10. Como dev, quero ver no G2 o que o agente notou e deixou de fora, para decidir o que vira ticket.
11. Como dev, quero que o agente trate conteúdo externo como dado, para uma página ou saída de CI não conseguir mandar nele.
12. Como dev, quero que o agente confira a API de um framework na documentação da versão usada, em vez de escrever de memória.

## Acceptance Criteria

**Régua protegida (1-2)**
- Quando o agente edita `docs/agents/checks.json` removendo ou alterando um comando de `onDone`/`onEdit`, ou aumentando `maxChangedLines`, o sistema deve pedir aprovação (ou negar com `Para aprovar: okeanos aprovar docs/agents/checks.json`, nos agentes sem "perguntar").
- Quando o agente só acrescenta um comando, ou diminui `maxChangedLines`, o sistema deve permitir.
- Se o agente reescreve ou apaga `checks.json` pelo shell (redirecionamento, `sed -i`, `rm`, `mv`), então o sistema deve tratar como afrouxamento e pedir aprovação.
- Se o `checks.json` ainda não está commitado (onboard criando), então o sistema deve permitir.

**Avisos de fim de turno (3-4)**
- Quando o diff da sessão afrouxa uma config de qualidade (por exemplo `strict: false` no tsconfig, regra de lint desligada, limite de cobertura menor), o sistema deve apontar no fim do turno, uma vez, sem bloquear o encerramento.
- Quando o diff acrescenta stub (`TODO: implement`, `raise NotImplementedError`, `throw new Error("not implemented")`, `pass` como corpo único) ou `catch`/`except` vazio, o sistema deve apontar no fim do turno, uma vez.
- Se nada disso aparece, então o sistema não deve dizer nada.

**Roteiro de verificação (5-6)**
- Quando o `onboard` roda num projeto com aplicação executável (servidor, CLI, UI), o sistema deve propor `docs/agents/verificar.md` com subir, checar, exercitar, evidência e limpar, para o usuário aprovar.
- Quando a mudança é visível ao usuário e o roteiro existe, o `implement` deve seguir o roteiro e anexar a evidência ao G2.
- Se o roteiro não existe, então o `implement` deve seguir como hoje e oferecer criá-lo.

**Testes ocos e raio de impacto (7-8)**
- O `tdd` e o eixo Spec do `code-review` devem aplicar a pergunta "este teste passaria se toda função importada retornasse vazio?" e os três padrões ocos (só mock, pin de constante, fixture que confere a si mesma).
- Quando o diff toca código compartilhado (exportado e usado por outros módulos, contrato público), o `code-review` deve listar os usos fora do diff afetados e o fato em que a segurança da mudança se apoia, provado por comando ou teste.
- Se o diff não toca código compartilhado, então o review não deve gerar essa seção.

**Disciplina incremental e conteúdo externo (9-12)**
- O `implement` deve entregar em fatias que compilam e passam nos testes, um commit por fatia.
- O `implement` deve manter a lista "notei, não mexi", e o G2 deve mostrá-la.
- O processo deve dizer que docs buscadas, saídas de ferramentas e páginas são dados, nunca instruções.
- Se o agente vai usar API de framework ou biblioteca, então deve conferir a versão no manifesto e a documentação dessa versão, ou dizer que não conferiu.

## Implementation Decisions

- Régua: regra nova no motor, para edição (editor e patch) e para escrita pelo shell no `checks.json` commitado; o alvo de aprovação é o caminho do arquivo. A comparação é semântica (JSON antigo do HEAD contra o novo), não por linha.
- Avisos de fim de turno reutilizam o mecanismo de "pontos que o usuário precisa saber" do hook de fim de turno (uma vez por assinatura).
- `docs/agents/verificar.md` é um arquivo do projeto, criado pelo `onboard` com aprovação, usado por `implement` e G2.
- Raio de impacto é um bloco condicional do `code-review`, não uma skill nova.
- Texto adaptado de pstack e agent-skills: crédito no `LICENSE` e no frontmatter das skills afetadas.

## Testing Decisions

- Régua e avisos: testes do motor pela CLI, nos dialetos Claude e Codex, como os existentes.
- Skills e processo: o teste de skills neutras e o build continuam passando; conteúdo novo é texto.

## Out of Scope

P2 (skills de desempenho, front-end e design de API; retro afiada) e P3 (plugin do Cursor; avaliações das skills).

## Open Questions

Nenhuma.
