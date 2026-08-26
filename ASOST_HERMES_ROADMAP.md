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

## Phase 2 — durable book/run identity

1. Add immutable `book_id`, `run_id`, `chapter_id`, and `segment_id` values.
2. Scope cached translations and terminology by book and source hashes.
3. Add versioned SQLite migrations and typed state transitions.
4. Store tool provenance without storing credentials or raw secrets.

## Phase 3 — book workflow on Hermes

1. Introduce a supervisor workflow for ingest, planning, translation, quality,
   reconstruction, and verification.
2. Activate Book Adapter and Context Keeper before the translator.
3. Add Terminologist, Translation Planner, and Quality Gate roles.
4. Use leases and checkpoints so interrupted segments can safely resume.
5. Keep deep critique conditional on risk or light-critic rejection.

## Phase 4 — unified memory

1. Replace unrelated JSON stores with repositories for working, chapter, book,
   translation, and operational memory.
2. Give terminology one canonical owner and record evidence/confidence.
3. Commit memory only from accepted revisions.
4. Prevent cross-book context leakage while retaining explicitly global TM.

## Phase 5 — deterministic document tools

1. Wrap extraction, image-flow analysis, DOCX/PDF composition, and verification
   as typed ASOST tools.
2. Establish one page/chapter/image intermediate representation.
3. Use vision agents only for geometrically ambiguous images or SFX.

## Phase 6 — reliability, security, and cost controls

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
