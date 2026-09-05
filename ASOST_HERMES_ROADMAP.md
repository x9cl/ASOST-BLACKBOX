# ASOST on Hermes — Integration Roadmap

## Architectural decision

Hermes remains the agent runtime. ASOST extends it with book-translation
roles, tools, state, and workflows rather than rebuilding agent management.

- OpenRouter models provide the reasoning agents.
- Hermes owns credential selection, cooldown, failover, and agent sessions.
- Gemini is a bounded literary tool that agents may invoke.
- PDF extraction, image placement, and document composition remain
  deterministic tools.
- Accepted translations, terminology, and narrative context are committed only
  after a quality gate.

## Phase 1 — integration foundation (implemented)

- Portable project, Hermes-home, and ASOST-memory paths.
- Environment-configurable Gemini input and pool-failover limits.
- `asost_gemini_task` registered as a Hermes tool with four bounded tasks:
  translation, critique, terminology extraction, and continuity summaries.
- Gemini credentials selected by Hermes' existing `gemini` credential pool;
  failed credentials are cooled down and rotated by Hermes.
- Least-privilege toolset assignment: the light critic remains tool-free while
  literary agents may use Gemini and ASOST memory.
- Atomic JSON memory replacement for crash-safe writes.
- Correct quality-gate behavior: a light-critic acceptance no longer invokes
  the deep critic, and provided context reaches the translator prompt.

## Phase 2 — durable book/run identity (implemented)

1. Add immutable `book_id`, `run_id`, `chapter_id`, and `segment_id` values.
2. Scope cached translations and terminology by book and source hashes.
3. Add versioned SQLite migrations and typed state transitions.
4. Store tool provenance without storing credentials or raw secrets.

## Phase 3 — book workflow on Hermes (implemented)

1. Introduce a supervisor workflow for ingest, planning, translation, quality,
   reconstruction, and verification.
2. Activate Book Adapter and Context Keeper before the translator.
3. Add Terminologist, Translation Planner, and Quality Gate roles.
4. Use leases and checkpoints so interrupted segments can safely resume.
5. Keep deep critique conditional on risk or light-critic rejection.

## Phase 4 — unified memory (implemented foundation)

1. Replace unrelated JSON stores with repositories for working, chapter, book,
   translation, and operational memory.
2. Give terminology one canonical owner and record evidence/confidence.
3. Commit memory only from accepted revisions.
4. Prevent cross-book context leakage while retaining explicitly global TM.

## Phase 5 — deterministic document tools (implemented adapters)

1. Wrap extraction, image-flow analysis, DOCX/PDF composition, and verification
   as typed ASOST tools.
2. Establish one page/chapter/image intermediate representation.
3. Use vision agents only for geometrically ambiguous images or SFX.

## Phase 6 — reliability, security, and cost controls (implemented foundation)

1. Add upload limits, dashboard authentication, retention rules, and job quotas.
2. Add per-run token/request budgets and bounded provider fallback.
3. Add offline fake-provider tests, crash/resume tests, rate-limit simulation,
   and deterministic end-to-end fixtures.
4. Export structured progress events instead of parsing log strings.

## Credential policy

The pool is for legitimate capacity, reliability, and rate-limit-aware routing.
Every configured account must be authorized for the deployment. ASOST must
honor provider limits and must not use pool rotation to evade provider policy.
Credentials belong in Hermes' credential store or an external secret manager,
never in source control, reports, prompts, or logs.

## Runtime configuration

Set `ASOST_HERMES_WORKFLOW=1` to route dashboard book jobs through
`BookSupervisor`; omit it to keep the legacy PF workflow as a rollback path.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ASOST_PROJECT_ROOT` | checkout root | Portable project location |
| `HERMES_HOME` | `<root>/hermes-home` | Hermes state and credential home |
| `ASOST_STATE_DB` | `<root>/asost_state.db` | Transactional workflow state |
| `ASOST_API_TOKEN` | none | Required dashboard/API write token |
| `ASOST_MAX_UPLOAD_BYTES` | 104857600 | Streaming upload limit |
| `ASOST_MAX_AGENT_ITERATIONS` | 12 | Per-agent tool/turn ceiling |
| `ASOST_MAX_AGENT_CALLS_PER_RUN` | 1000 | Whole-workflow agent-call budget |
| `ASOST_GEMINI_MODEL` | `gemini-3.5-flash` | Default Gemini tool model |
| `ASOST_GEMINI_MODEL_<TASK>` | default model | Per-task Gemini override |
| `ASOST_GEMINI_TIMEOUT_SECONDS` | 300 | Per-request timeout |
| `ASOST_GEMINI_MAX_INPUT_CHARS` | 20000 | Tool input ceiling |
| `ASOST_GEMINI_POOL_FAILOVERS` | 3 | Cross-credential attempt ceiling |

Add legitimate OpenRouter and Gemini credentials through the existing Hermes
authentication commands/store. Copy `hermes-home/auth.sample.json` only as a
schema reference; never place a real `access_token` in source control.

## Completed integration checklist

1. OpenRouter agents use Hermes' native credential pool.
2. A durable Hermes-driven full-book supervisor is available.
3. Book Adapter, Context Keeper, Terminologist, Planner, Translator, critics,
   Reviser, and Quality Gate participate under explicit conditions.
4. Full segments—not fixed prefixes—reach deterministic and agent quality gates.
5. Gemini failures are classified before credential rotation.
6. Gemini task results are validated against task-specific contracts.
7. Gemini is registered with a genuinely asynchronous Hermes handler.
8. Agent sessions are isolated by book, run, and role.
9. SQLite provides transactional, book-scoped memory and checkpoints.
10. Sensitive ASOST and dashboard APIs require constant-time token checks.
11. Page API jobs are durable, owned, bounded, and safely pruned.
12. Runtime settings have one portable, validated source.
13. Gemini models can be selected globally or per task.
14. Agent iterations, whole-run calls, and provider failovers are bounded.
15. Offline tests cover pools, contracts, state, concurrency, resume, quality,
    document adapters, image placement, and the complete workflow.
16. Secrets, databases, uploads, logs, and generated state are excluded from
    source control; only a redacted authentication schema sample remains.
