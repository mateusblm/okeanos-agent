# Okeanos

**Processo de engenharia de verdade para o Claude Code, sem você precisar lembrar de nada.**

Você pede uma feature. O Okeanos mede o tamanho do pedido, pergunta o que só você sabe, escreve o teste antes do código, não deixa o agente afrouxar esse teste e para duas vezes para você aprovar: antes de escrever código e antes de publicar. Tudo isso numa sessão normal do Claude Code, sem comandos novos para decorar.

O nome vem do Okeanos da mitologia grega, o rio que dá a volta no mundo e nunca para.

```bash
claude plugin marketplace add mateusblm/okeanos-agent
claude plugin install okeanos@okeanos
```

Abra uma sessão nova em qualquer projeto. Ele já está rodando.

---

## Como é usar

Um pedido de verdade, numa API de tarefas em TypeScript (trecho resumido de uma sessão real):

```text
você     Quero adicionar data de vencimento nas tarefas e poder listar só as atrasadas.

okeanos  Okeanos · rota: Feature · campo novo + filtro, cabe numa sessão

         Q1 · Data ou data com hora?
              → Recomendo só a data (YYYY-MM-DD). Evita fuso e horário.
         Q3 · "Atrasada" = não concluída e com vencimento antes de hoje.
              Vence hoje não conta. Confere?
         ...

         G1 · pré-checagem
         ✅ critérios de aceitação, com os casos de erro
         ❌ dúvida em aberto: "hoje" em qual fuso? Às 22h em Brasília já é amanhã em UTC.
         ✅ fora de escopo definido
         ✅ modelo de ameaças (a API recebe entrada externa)

você     Usa UTC. Pode seguir.

okeanos  [3 ciclos de teste → código, cada teste commitado antes da implementação]
         [revisão em dois eixos, documentação com diagramas, resumo para aprovar]
```

Repare no ❌. O Okeanos achou a ambiguidade do fuso antes de existir código, quando resolver custa uma frase. Sem ele, ela aparece como bug numa terça à noite.

## O que ele não deixa passar

Agentes de código têm vícios conhecidos e medidos. O Okeanos bloqueia os principais com hooks, que rodam fora do modelo. Pedir com jeitinho no prompt não funciona; hook funciona.

**Mexer no teste para o código passar.** Em pesquisa recente, modelos editaram os testes em mais de 70% das tarefas impossíveis. No Okeanos, alterar ou apagar uma asserção de um teste já commitado pede a sua aprovação, seja pelo editor ou por `sed` no terminal. Adicionar testes continua livre.

**Dizer que terminou com o teste vermelho.** Se o código mudou, o agente só encerra com typecheck, testes e build passando. Se não conseguir, ele explica por quê e devolve a decisão para você.

**Instalar pacote que não existe.** Quase 20% dos trechos gerados por LLM citam pacotes inexistentes, e atacantes registram esses nomes. O Okeanos consulta o registry antes de instalar: nome inexistente é bloqueado; pacote novo, pouco usado ou com nome a uma letra de um famoso (`axois`) pede confirmação.

**Commitar segredo.** Chaves da AWS, GitHub, Stripe, OpenAI, Anthropic, chaves privadas e arquivos `.env` barram o commit.

**Publicar sem você ver.** `git push`, abrir ou fazer merge de PR e merge na branch principal sempre pedem a sua confirmação, inclusive no modo automático.

**Atalhos perigosos.** `--no-verify`, force push e `rm -r` fora do projeto são bloqueados.

**Diff gigante.** Os pedidos são quebrados em pedaços de 200 a 400 linhas, o tamanho que uma pessoa consegue revisar de verdade. Passou disso, você recebe um aviso.

## Testado antes de chegar em você

Rodamos o Okeanos em 5 situações reais, em Python e TypeScript, com um usuário simulado respondendo às perguntas:

| Situação | O que aconteceu |
| :- | :- |
| Abrir um projeto desconhecido | Leu o código, propôs um `CLAUDE.md` curto com as armadilhas reais do projeto e ainda achou um bug que ninguém tinha pedido para procurar. US$ 0,54. |
| Corrigir um bug | Escreveu o teste que reproduz o bug antes do fix, subiu a API para conferir e trouxe uma decisão de produto em vez de chutar. |
| Feature média | Fluxo completo, do alinhamento à documentação, em 7 minutos. |
| Feature grande (login multiusuário) | 3 tickets em paralelo, 57 testes. O teste de mutação achou bordas sem cobertura, e a revisão pegou um bug de Unicode: um nome com o símbolo Kelvin virava `k` e burlava a validação. 19 minutos, US$ 17. |
| Mudar uma regra protegida por teste | O agente tentou editar o teste pelo terminal. O hook barrou, e ele parou para pedir aprovação em vez de contornar. |

A simulação também achou falhas no próprio Okeanos, como a proteção de testes que dava para burlar com `sed`. Todas foram corrigidas antes desta versão.

## Ele mede o tamanho antes de agir

Nem todo pedido merece o mesmo processo. Uma pergunta não abre entrevista; uma feature grande não vai direto para o código.

| Pedido | O que o Okeanos faz |
| :- | :- |
| Pergunta ou ajuste trivial | Responde ou faz, e pronto. |
| Bug | Teste que reproduz o bug primeiro, depois o fix, revisão e aprovação. |
| Feature | Entrevista curta, **aprovação**, implementação com testes, revisão, docs, **aprovação**. |
| Feature grande | Entrevista, spec, tickets em ondas, **aprovação**, implementação em paralelo, teste de mutação, revisão, docs, **aprovação**. |
| Épico nebuloso | Mapeia as decisões antes de qualquer código. |

Você sempre manda. "Pula a entrevista", "só faz" ou "sem okeanos" na mensagem e ele obedece.

## Funciona com a sua stack

O Okeanos não depende de linguagem. Na primeira sessão em um projeto ele descobre os comandos que você já usa (`pytest`, `go test`, `cargo test`, `gradle`, `dotnet test`, `npm test`...) e mostra para você aprovar. Os hooks reconhecem testes e supressões de lint em JS/TS, Python, Go, Java, Kotlin, Scala, C#, Swift, Ruby, PHP, Elixir, Dart e Rust, e checam pacotes em npm, PyPI, crates.io, RubyGems, Packagist, NuGet e módulos Go.

## E mais

- **Documentação que acompanha o código.** A cada entrega ele atualiza a arquitetura no padrão arc42, com diagramas C4 que o GitHub renderiza, e escreve um doc da feature a partir do que foi construído, não do que foi planejado. [Veja um exemplo](examples/calc/docs/architecture.md).
- **Segurança desde o desenho.** Quando a mudança toca login, dados, segredos ou entrada externa, ele faz um modelo de ameaças de 15 linhas, e cada mitigação vira um teste.
- **Testes que pegam bug de verdade.** Em lógica crítica, o teste de mutação injeta bugs de propósito para ver se os testes percebem. Os que passam despercebidos viram testes novos.
- **Trabalho enquanto você está fora.** Em features grandes, os tickets podem rodar em containers Docker isolados, em paralelo, e você volta para um relatório. Começa por uma rodada piloto de dois tickets, para um erro de configuração custar minutos e não a tarde.
- **CI no mesmo padrão.** No GitHub, ele oferece um workflow que roda as mesmas checagens, para nada chegar na `main` por fora.
- **Aprende com os próprios erros.** Cada bloqueio fica registrado localmente. Quando algo dá errado, a retrospectiva usa esses números e termina em uma mudança concreta no processo, nunca em "tomar mais cuidado".

## Quando ele não vale a pena

- **Exploração e protótipos rápidos.** As paradas para aprovação atrapalham. Use "sem okeanos".
- **Orçamento apertado em features grandes.** O processo completo custa mais tokens que um pedido direto: no teste acima, US$ 17 numa feature de login multiusuário. Em troca, o bug de Unicode não foi para produção.
- **Máquina sem Python 3.** As verificações automáticas usam Python. Sem ele, o fluxo continua, mas os hooks ficam desligados.

## Comandos

| Para | Comando |
| :- | :- |
| Atualizar | `claude plugin marketplace update okeanos && claude plugin update okeanos@okeanos` |
| Desligar | `claude plugin disable okeanos@okeanos` |
| Religar | `claude plugin enable okeanos@okeanos` |
| Remover | `claude plugin uninstall okeanos@okeanos` |
| Pular o processo num pedido | escreva "sem okeanos" na mensagem |

Sessões abertas antes de instalar ou atualizar precisam ser reiniciadas.

---

## Por dentro

Para quem quer entender ou mexer.

- **O processo** vive num output style ([`output-styles/okeanos.md`](output-styles/okeanos.md)) que o plugin ativa em toda sessão. Ele soma às instruções padrão do Claude Code em vez de substituí-las.
- **As verificações** são hooks em Python puro ([`hooks/okeanos.py`](hooks/okeanos.py)). Os comandos de cada projeto ficam em `docs/agents/checks.json`:

  ```json
  {
    "onEdit": [{ "name": "lint", "cmd": "ruff check {file}", "ext": [".py"] }],
    "onDone": [{ "name": "test", "cmd": "pytest -q" }],
    "maxChangedLines": 400
  }
  ```

- **As skills** ficam em [`skills/`](skills/). O Okeanos chama a maioria sozinho; `ask-okeanos` (o mapa das rotas), `teach`, `wait-what`, `to-questionnaire` e `improve-codebase-architecture` são para você chamar quando quiser.
- **O modo AFK** usa o Sandcastle, que exige Node e Docker na sua máquina e um token do Claude que você mesmo cola em `.sandcastle/.env`.
- **Manutenção.** Cada etapa do Okeanos é uma aposta sobre o que o modelo ainda não faz bem sozinho. [`docs/manutencao.md`](docs/manutencao.md) explica como medir e remover etapas conforme os modelos melhoram.

Para desenvolver o próprio Okeanos, instale a partir do clone:

```bash
claude plugin marketplace add /caminho/para/okeanos-agent
claude plugin install okeanos@okeanos
```

## Licença

MIT. Veja [`LICENSE`](LICENSE).
