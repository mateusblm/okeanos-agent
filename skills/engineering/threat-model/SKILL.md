---
name: threat-model
description: Lightweight threat model for a change, in at most 15 lines - the four Threat Modeling Manifesto questions with STRIDE as the prompt list, each mitigation turned into a testable acceptance criterion. Use when a change touches authentication or authorization, external input, persisted or personal data, secrets, third-party network calls, or LLM calls, or when the user asks about the security of a design.
---

# Threat model

A threat model is cheap when it's done while the design is still words, and expensive after the code exists. Keep it short enough to be read: at most 15 lines in the spec. Do it with the user during alignment, not alone at the end.

## When it applies

Run it when the change touches any of:

- authentication, sessions, authorization, roles;
- input that crosses a trust boundary (HTTP, CLI args from others, files, webhooks, queues);
- persisted data, personal data, payments;
- secrets, tokens, keys;
- calls to third-party services;
- LLM calls (prompts built from user input, tool use, model output used as code or commands).

If none applies, say so in one line and skip it.

When the change also alters a public contract (HTTP route or payload, CLI flags or output, persisted or wire schema), read `API.md` in the `codebase-design` skill for boundary validation, untrusted third-party responses and idempotency.

## The four questions

Work through them using the C4 diagram from `docs/architecture.md` when it exists (it shows the boundaries), otherwise a quick list of the components the change touches.

1. **What are we working on?** The elements the change adds or alters and the trust boundaries data crosses (user → API, API → database, service → third party, prompt → model).
2. **What can go wrong?** Walk STRIDE over each boundary crossing and keep only threats that are plausible for this change:
   - **S**poofing: someone pretends to be another user or service.
   - **T**ampering: data altered in transit or at rest.
   - **R**epudiation: an action with no trace of who did it.
   - **I**nformation disclosure: data or secrets reaching who shouldn't see them (logs, errors, responses).
   - **D**enial of service: unbounded input, loops, missing limits.
   - **E**levation of privilege: doing what your role doesn't allow; injection (SQL, command, prompt).
3. **What are we going to do about it?** One mitigation per threat kept: mitigate, accept (with who accepted it), or move out of scope.
4. **Did we do a good enough job?** Every mitigation becomes an **If ... then** acceptance criterion in the spec, so a test proves it. A mitigation with no test is a wish.

## Output

```markdown
**Fronteiras:** <boundaries crossed, one line>

| Ameaça (STRIDE) | Onde | Resposta | Critério |
| :- | :- | :- | :- |
| <E: usuário edita pedido de outro> | <API → banco> | mitigar: checar dono do pedido | Se o pedido é de outro usuário, então o sistema deve responder 404. |
```

At most 15 lines. Write it in the user's language. Accepted risks name who accepted them. The rows feed the spec's **Security** section and its acceptance criteria, and the reviewer checks the tests exist.
