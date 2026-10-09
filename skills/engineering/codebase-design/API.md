# Public contracts

How to design an interface that callers outside this codebase depend on. Assumes the vocabulary in [SKILL.md](SKILL.md): a public contract is an **interface** whose callers you don't control, so you can't fix them when it changes. It is the most expensive design decision to reverse; settle it during alignment, before code.

## When it applies

The change adds or alters any of:

- an HTTP route, its request or response payload, headers, or status codes;
- CLI flags, arguments, exit codes, or output that scripts parse;
- a persisted schema (database, files on disk) or a wire schema (queue messages, events, webhooks);
- a config file format that users write;
- the exported surface of a library or SDK.

Internal modules that ship together with all their callers are not public contracts: change them and their callers in one commit.

## Hyrum's law and One-Version

With enough callers, every observable behaviour is depended on by somebody, whatever the documentation promises: error text, field order, timing, default sort, the quirk you never meant to ship.

- Expose on purpose. Don't leak implementation details (internal ids, stack traces, raw upstream errors) into responses or output.
- Plan removal at design time: anything you expose, you will have to deprecate one day.
- Contract tests are necessary and not enough: a "safe" change can still break a caller who relied on unspecified behaviour.
- **One-Version:** keep one live version of the contract and extend it, rather than maintaining parallel versions that callers must choose between. A second version is a last resort for a break you can't avoid.

## One error format

Pick one error shape and use it on every route or command. Callers can't handle errors they can't predict.

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "email is required", "details": {} } }
```

`code` is machine-readable and stable (part of the contract); `message` is for humans and may change; `details` is optional. Map status consistently:

| Status | Meaning |
| :- | :- |
| 400 | malformed request |
| 401 | not authenticated |
| 403 | authenticated, not allowed |
| 404 | not found (also for "exists but not yours", to avoid leaking existence) |
| 409 | conflict: duplicate, version mismatch, idempotent request still in flight |
| 422 | well-formed but semantically invalid |
| 429 | rate limited, with `Retry-After` |
| 500 | server error, never with internal details |

For a CLI, the same idea: one error line format on stderr, documented exit codes, stdout reserved for the result.

## Validate at the boundary

Validate where outside data enters: request handlers, CLI argument parsing, config and environment loading, message consumers, and **responses from third-party services**. A third-party response is untrusted input: check its shape and content before using it in logic, rendering, or a prompt, because a broken or compromised service can return wrong types, hostile content, or text that reads like instructions.

Past the boundary, internal code trusts the parsed types. Don't re-validate between internal functions or on data you just read from your own store.

## Change additively

- New fields and parameters are **optional**, with a default that keeps the old behaviour.
- Never rename, remove, or change the type or meaning of an existing field, flag, code, or exit status in place.
- Readers ignore unknown fields; writers don't depend on readers knowing new ones.
- Persisted and wire schemas migrate by expand, migrate, contract: add the new shape, move data and callers, remove the old shape last.
- **Deprecation path:** mark it deprecated (docs, a response header, a warning on stderr), say what replaces it and from when, measure who still uses it, and remove it only after that reaches zero or the announced date.
- When a break is unavoidable, say so plainly and **version** it (`/v2/`, a new event type, a new major of the package), with the old version kept for a stated window.

## Paginate from the start

Every list endpoint or command that can grow paginates from its first release; adding pagination later is a breaking change.

- Prefer **cursor** pagination (`?cursor=<opaque>&limit=50`, response with `next_cursor`, null at the end): stable under inserts and cheap at any depth. Offset pagination skips or repeats items when data changes and gets slow deep in the set.
- The cursor is opaque to callers; you may change what it encodes.
- Set a default limit and a maximum, and enforce the maximum server-side.
- Fix a deterministic sort with a unique tie-breaker (for example `created_at, id`).

## Idempotency keys

A state-changing operation that callers may retry (payment, order, message send, any non-idempotent POST or command) either honours an idempotency key or is documented as unsafe to retry. Accepting a key without honouring it is worse than no key: the caller now believes retrying is safe.

- **Derive the key from the intent, not the attempt.** Stable across retries of one intent, different across distinct intents. A client-generated key reused on retry, or one built from an immutable id (`charge:v1:<order_id>`), works. A random id per attempt, a timestamp, or a key built from mutable values (`<user>:<amount>`, which merges two real payments of the same amount) doesn't. The key comes from the caller or the initiating event, never from the layer that retries.
- **Claim atomically.** "Check if the key exists, then act" is a race: two concurrent retries both see nothing and both act. Insert the key with state `in_progress` under a **unique constraint** and let the constraint pick the winner; the loser reads the existing record. A store that can't enforce uniqueness in one operation can't back this.
- **Hash the payload.** Store a hash of the request with the key. Same key with a different payload is a client bug: reject it (422), never replay the first response to a different request.
- **Decide what an in-flight duplicate gets**, explicitly: `409` (caller retries later; simplest), **wait** for the first result with a bound (caller needs it synchronously), or `202` with a status URL (long-running effect). Never let the duplicate through because the first attempt "seems stuck".
- **Three outcomes, not two:** success, failure, and unknown (a timeout says nothing about whether the effect applied). Record the intent before calling out, so a crash leaves a record that a reconciliation step resolves instead of a silent second effect.
- **Retention outlives the retry chain.** Keep keys longer than every path that can redeliver the same intent: client retries, queue redelivery, a dead-letter queue replayed days later, a provider's dispute window. A 24-hour key behind a 7-day DLQ is a duplicate waiting to happen.

The test for any state-changing step: what happens if it runs twice in a row, and if the previous run crashed at each possible point? If the answer depends on what was left behind, it needs a reconciliation step.

## Decision checklist

Settle these during alignment; they feed the G1 pre-check item on public contracts.

- [ ] Which public contract the change touches, and who its callers are.
- [ ] Error format and status (or exit code) mapping: the existing one reused, or the one chosen.
- [ ] Compatibility: every change additive and optional, or the break named, with its additive alternative or version and deprecation window.
- [ ] Inputs validated at the boundary, third-party responses included.
- [ ] Lists paginated: cursor or offset, default and maximum limit, stable sort.
- [ ] State-changing operations: idempotency key source, atomic claim, payload hash, in-flight duplicate response, retention; or documented as unsafe to retry.
