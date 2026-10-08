# Operações matemáticas (math-ops)

A calculadora de linha de comando, que antes só somava, agora também subtrai e divide. Divisão por zero é recusada com uma mensagem no stderr e código de saída `2`, em vez de imprimir `Infinity`.

**Status:** entregue em `okeanos/math-ops` · **Spec:** nenhuma · **ADRs:** nenhum

## O que foi construído

- `node src/cli.js sub <a> <b>` imprime `a - b`.
- `node src/cli.js div <a> <b>` imprime `a / b`.
- `node src/cli.js div <a> 0` escreve `cannot divide by zero` no stderr e sai com código `2`.
- `add` continua funcionando como antes.
- A CLI passou a despachar operações por uma tabela (`add`, `sub`, `div`) em vez de um `if` por operação.
- O núcleo `math` exporta `subtract`, `divide` e o erro de domínio `DivisionByZeroError`.

Sem spec registrada, não há desvios a apontar.

## Onde se encaixa na arquitetura

Verde = elemento novo; amarelo = elemento alterado.

```mermaid
C4Component
  title Componentes da CLI calc após math-ops
  Person(usuario, "Usuário", "Roda a calculadora no terminal")
  Container_Boundary(calc, "CLI calc") {
    Component(cli, "CLI", "Node.js, ES module", "Lê argv, despacha pela tabela de operações, imprime o resultado ou o erro")
    Component(math, "Math", "Node.js, ES module", "Funções puras add, subtract, divide")
    Component(divErr, "DivisionByZeroError", "Classe de erro", "Sinaliza divisão por zero")
  }
  Rel(usuario, cli, "Executa com operação e operandos", "argv, stdout, stderr")
  Rel(cli, math, "Chama a operação", "função")
  Rel(math, divErr, "Lança quando o divisor é zero")
  Rel(cli, divErr, "Captura e converte em saída 2")
  UpdateRelStyle(usuario, cli, $offsetX="-130", $offsetY="-20")
  UpdateRelStyle(cli, math, $offsetX="-45", $offsetY="-55")
  UpdateRelStyle(math, divErr, $offsetX="30", $offsetY="10")
  UpdateRelStyle(cli, divErr, $offsetX="-110", $offsetY="0")
  UpdateElementStyle(cli, $bgColor="#f9a825", $fontColor="#1d2330", $borderColor="#b8860b")
  UpdateElementStyle(math, $bgColor="#f9a825", $fontColor="#1d2330", $borderColor="#b8860b")
  UpdateElementStyle(divErr, $bgColor="#2e7d32", $fontColor="#ffffff", $borderColor="#1b5e20")
```

## Como funciona

```mermaid
sequenceDiagram
  actor U as Usuário
  participant CLI
  participant Math
  U->>CLI: node src/cli.js op a b
  CLI->>CLI: ops[op] e Number(a), Number(b)
  alt op é add, sub ou div com divisor diferente de zero
    CLI->>Math: add / subtract / divide(a, b)
    Math-->>CLI: resultado
    CLI-->>U: resultado no stdout, saída 0
  else div com divisor zero
    CLI->>Math: divide(a, 0)
    Math-->>CLI: lança DivisionByZeroError
    CLI-->>U: "cannot divide by zero" no stderr, saída 2
  else op desconhecida
    CLI-->>U: TypeError não tratado com stack trace, saída 1
  end
```

## Componentes

| Componente | Responsabilidade | Mudança |
| :- | :- | :- |
| CLI (`src/cli.js`) | Lê `argv`, escolhe a operação, imprime resultado, traduz `DivisionByZeroError` em saída `2` | Alterado: tabela de operações e tratamento de erro |
| Math (`src/math.js`) | Funções aritméticas puras | Alterado: `subtract` e `divide` |
| DivisionByZeroError | Erro de domínio da divisão por zero | Novo |

## Testes

Seam testada: as funções puras do módulo Math, com `node:test`, em `test/`. Cobertura: `subtract`, `divide` e o lançamento de `DivisionByZeroError`. Rode com `npm test`.

A CLI não tem teste: o mapeamento de `DivisionByZeroError` para saída `2` e o despacho pela tabela não são verificados automaticamente. `add` também não tem teste.

## Limites e próximos passos

- **Operação desconhecida derruba a CLI.** `ops[op]` é `undefined` para qualquer operação fora da tabela (inclusive a ausência de argumentos), e a chamada lança `TypeError` com stack trace, sem mensagem de uso.
- **Chaves herdadas de `Object.prototype` passam pela tabela.** `ops` é um objeto literal, então operações como `constructor` ou `toString` resolvem para funções herdadas e produzem saída sem sentido em vez de erro.
- **Operandos não numéricos viram `NaN`.** `Number("x")` não é validado; a CLI imprime `NaN` com saída `0`.
- **Sem teste da CLI.** O contrato de saída (stdout, stderr, código `2`) não tem teste.

Os mesmos itens estão na [seção 11 do architecture.md](../architecture.md#11-riscos-e-débitos-técnicos).

## Impacto na arquitetura

Primeira execução do as-built neste repositório: o [architecture.md](../architecture.md) foi criado, e esta feature aparece em [§1](../architecture.md#1-introdução-e-objetivos), [§5](../architecture.md#5-visão-de-blocos-de-construção), [§6](../architecture.md#6-visão-de-tempo-de-execução), [§8](../architecture.md#8-conceitos-transversais) e [§11](../architecture.md#11-riscos-e-débitos-técnicos).
