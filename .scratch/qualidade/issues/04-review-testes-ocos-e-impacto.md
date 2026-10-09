# 04: Testes ocos e raio de impacto no review

**What to build:** `tdd` (tests.md) e o eixo Spec do `code-review` ganham a pergunta "passaria se toda função importada retornasse vazio?" e os três padrões ocos; o `code-review` ganha um bloco condicional de raio de impacto quando o diff toca código compartilhado. Crédito ao pstack.

**Blocked by:** None

**Wave:** 1

**Status:** ready-for-agent

- [ ] O `tdd` e o review devem aplicar a pergunta e os três padrões ocos.
- [ ] Quando o diff toca código compartilhado, o review deve listar usos afetados fora do diff e o fato que garante a segurança, provado.
- [ ] Se o diff não toca código compartilhado, então o review não deve gerar essa seção.
