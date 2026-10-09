# 02: Avisos de fim de turno (configs afrouxadas, stubs, catch vazio)

**What to build:** o hook de fim de turno aponta, uma vez e sem bloquear, configs de qualidade afrouxadas no diff da sessão (tsconfig strict, regras de lint desligadas, cobertura menor) e stubs ou `catch`/`except` vazios em código novo.

**Blocked by:** 01

**Wave:** 2

**Status:** ready-for-agent

- [ ] Quando o diff afrouxa uma config de qualidade, o sistema deve apontar no fim do turno, uma vez.
- [ ] Quando o diff acrescenta stub ou catch vazio, o sistema deve apontar no fim do turno, uma vez.
- [ ] Se nada disso aparece, então o sistema não deve dizer nada.
