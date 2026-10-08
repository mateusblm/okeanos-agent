# Exemplo: calc

Uma calculadora de linha de comando mínima, usada para mostrar o que a skill `as-built` gera ao fim de um fluxo do Okeanos.

A feature **math-ops** (subtração e divisão com erro de divisão por zero) foi implementada numa branch, e o `as-built` gerou:

- [`docs/architecture.md`](docs/architecture.md): arquitetura no padrão **arc42**, com diagramas **C4** de contexto, containers, componentes e implantação, mais o fluxo de execução;
- [`docs/features/math-ops.md`](docs/features/math-ops.md): o doc da feature, com o diagrama de componentes destacando o que é novo (verde) e o que mudou (amarelo).

Os riscos que o `as-built` encontrou lendo o código (operação desconhecida derruba a CLI, entrada não numérica vira `NaN`) foram mantidos de propósito, para mostrar a seção 11 do arc42 em uso.
