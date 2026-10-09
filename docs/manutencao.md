# Manutenção do Okeanos

Cada etapa do Okeanos codifica uma suposição sobre o que o modelo não faz bem sozinho: alinhar antes de codar, não afrouxar testes, não inventar pacotes, revisar o próprio trabalho. Modelos melhoram, e uma etapa que já não se paga só custa tempo e tokens. A própria Anthropic recomenda tirar peças do harness uma a uma conforme os modelos evoluem.

## Medir

Os hooks registram cada evento, com o nome do agente, em `.git/okeanos/metrics.jsonl` de cada repositório (ou na reserva em `<TMPDIR>/okeanos/` quando a pasta do git é só leitura, como na sandbox do Codex). Para ver o resumo de um repo, por tipo e por agente, somando os dois lugares:

```bash
cd <projeto> && okeanos metrics 30   # últimos 30 dias (ou <caminho-do-okeanos-agent>/hooks/run metrics 30)
```

Sinais que valem olhar:

| Sinal | O que sugere |
| :- | :- |
| `stop:block` alto e sempre pelo mesmo comando | O comando está quebrado, lento ou mal configurado em `checks.json`, não o agente. |
| `stop:escalate` frequente | Tickets grandes demais ou critérios ambíguos: reforçar `okeanos-tickets` e a pré-checagem do G1. |
| `stop:tamper` / `pre-edit:ask` frequentes | O agente está brigando com os testes: specs ou seams pouco claras. |
| `pre-bash:deny` de pacote | O modelo está inventando dependências: manter o guard. |
| Um tipo de evento zerado por muito tempo | Candidato a poda (ver abaixo). |

## Podar

A cada modelo novo (ou a cada trimestre):

1. Escolha **uma** etapa ou regra candidata: a que tem menos eventos, ou a que mais atrasa.
2. Desligue só ela por um período definido (duas semanas, ou um número fixo de features), anotando a data aqui embaixo.
3. Compare as métricas do período com as do período anterior: `stop:block`, `stop:escalate`, achados blocking no `okeanos-code-review`, G2 recusados, reverts e bugs pós-merge.
4. Se nada piorou, a remoção fica. Se piorou, a etapa volta, e o motivo fica registrado.

Nunca pode duas etapas de uma vez: sem isolar a variável, a medição não diz qual delas importava.

## Registro de podas

| Data | Etapa | Período | Resultado |
| :- | :- | :- | :- |
