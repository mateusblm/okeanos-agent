# Codex hook trust: how installers get hooks trusted (research 2026-10-09)
Source checked: openai/codex main @ 0ada5d88 (2026-10-09), cloned to scratchpad/src/codex (sparse).

## Official docs (learn.chatgpt.com/docs/hooks, formerly developers.openai.com/codex/hooks)
- "Before a non-managed hook can run, Codex requires you to review and trust the exact hook definition." Trust recorded against current hash.
- "Installing or enabling a plugin doesn't automatically trust its hooks."
- Managed (system, MDM, cloud, requirements.toml) hooks are "marked as managed, trusted by policy, and can't be disabled from the user hook browser."
- `--dangerously-bypass-hook-trust`: run enabled hooks without persisted trust for that invocation.
- Docs do NOT document hooks.state / trusted_hash or any programmatic trust API.

## Source facts
- hooks/src/engine/discovery.rs: hook_metadata_for_config_layer_source -> System (/etc/codex/config.toml), Mdm, EnterpriseManaged, LegacyManagedConfig* = managed (is_managed=true); User/Project/SessionFlags/plugins = not managed. Requirements hooks (/etc/codex/requirements.toml, MDM, cloud) also managed.
- trust status: builtin -> Trusted; managed -> Managed; else trusted_hash==current_hash ? Trusted : Modified/Untrusted.
- hash = "sha256:" + sha256(sorted-keys JSON of {event_name, ...matcher group with single normalized handler}) (config/src/fingerprint.rs version_for_toml).
- key = "<key_source>:<event_snake>:<group_idx>:<handler_idx>"; key_source = hooks file path, or "<plugin>@<marketplace>:<relative hooks path>" for plugins (hooks/src/declarations.rs).
- TUI /hooks = tui/src/hooks_rpc.rs: hooks/list then config/batchWrite {keyPath:"hooks.state", value:{key:{trusted_hash}}, mergeStrategy: upsert, reloadUserConfig:true}.
- TUI startup_hooks_review.rs: at startup, if hooks need review, shows a prompt: Review hooks / Trust all and continue / Continue without trusting.
- app-server/src/effective_plugin_change.rs: AUTO-TRUSTS hooks of remote plugins materialized with scope=Workspace + discoverability=Listed for the current account (admin-published workspace plugins). Local marketplace plugins: no auto trust.
- No `codex hooks trust` subcommand; no config option/env var other than bypass (bypass_hook_trust override = the CLI flag; app-server rejects it per agentihooks PR).

## Open feature request
- openai/codex#21615 "Provide a supported way for local IDE/wrapper installers to request trust for installed hooks" - OPEN, no maintainer reply, 5 comments (as of 2026-10-07).

## Third-party practice
A) Use app-server hooks/list + config/batchWrite (Codex computes hash): spaces#845 (consent sheet listing exact commands), dibs#131 (`dibs codex-hooks --trust`), hide#670, limit-lifeboat#116 (setting toggle = consent), ANOLISA (#2281/#4631), agentihooks#1784, Orca proposal #16428.
B) Reimplement hash, write config.toml directly: llm-router#129, confab hookconfig (Go), phren#245, glmn comment in #21615 (passes -c hooks.state...).
C) Never write trust, tell user to run /hooks: foom#181, session-orchestrator, NeuralTrust TrustGuard, teamai.
Pitfalls: positional keys (group index shifts), stale hash after any field change (timeout, path), orphaned entries on uninstall (batchWrite rejects null -> need replace w/ expectedVersion), CODEX_HOME mismatch (Desktop vs CLI / isolated homes), Windows path separator variants in keys.

## Recommendation
Installer: write hooks to ~/.codex/hooks.json (or as plugin), show consent listing exact commands, then spawn `codex app-server` (stdio), hooks/list (cwd), select only own entries by exact command+event+matcher with trustStatus untrusted|modified, config/batchWrite hooks.state.<key>.trusted_hash = currentHash (upsert), re-list to verify. Fall back to Codex's own startup "Hooks need review" prompt. Avoid: hand-computed hashes, /etc/codex managed (requires root, semantically admin policy, undisableable), bypass flag.
