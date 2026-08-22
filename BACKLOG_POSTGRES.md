# PostgreSQL Gold Sync Backlog

This backlog extension is the implementation source of truth for the PostgreSQL Gold serving-plane work in `market-regime-loader`. It preserves the repository's one-PR/one-task delivery discipline and the root `BACKLOG.md` Git conventions.

The PostgreSQL target is `10.10.1.3:54321`. Only the canonical Gold dataset is replicated. Parquet Gold remains the source of truth; PostgreSQL is a rebuildable serving-plane replica. The repository application role is exactly `market-regime-loader` and uses its own protected password. No PostgreSQL password, administrator credential, or credential-bearing DSN may be committed, logged, or persisted in sync metadata.

The Gold temporal key is `timestamp_m1`. PostgreSQL stores it as `TIMESTAMPTZ(6)` and every application session uses timezone `UTC`; a Gold UTC-midnight observation-day identity therefore round-trips as e.g. `2026-08-22 00:00:00+00`. It is not provider publication time.

Synchronization semantics are state-reconciliation semantics, not a timestamp-watermark feed: the first successful sync inserts the complete current Gold history; every later sync compares the complete current canonical Gold row-digest set with the complete PostgreSQL digest state and applies the complete accumulated INSERT/UPDATE/DELETE delta. Missed weekly runs and historical Gold corrections must be caught up on the next successful sync.

Operational PostgreSQL sync logs use the existing project logging path `${PROJECT_ROOT}/.logs/market-regime-loader.log`; there is no PostgreSQL-specific logging subsystem.

## Dependency Graph

```text
PR-31 backlog-postgres-sync-plan
  |\
  | +---------------------> PR-35 postgres-service-role-provisioning
  | +---------------------> PR-36 postgres-sync-operational-config
  v
PR-32 postgres-gold-sync-contracts
  |\
  | +--> PR-33 gold-row-delta-planner
  +----> PR-34 postgres-gold-sync-adapter
           \             /
            +-----+-----+
                  v
                PR-37 gold-postgres-delta-sync
                  |
        PR-35 + PR-36 + PR-37
                  |
                  v
                PR-38 postgres-gold-sync-cli
                  |
                  v
                PR-39 sunday-postgres-gold-sync-cron
```

---

## PR-31: Backlog PostgreSQL Sync Plan

PR name: `backlog-postgres-sync-plan`
Status: In Progress
Updated: 2026-08-22
PR: none
Git branch: `pr-31/backlog-postgres-sync-plan`
Git status: `active-clean`
Agent lane: Governance; one agent only
Depends on: none
Commit: `docs(pr-31): backlog-postgres-sync-plan add postgres sync backlog`
Design patterns: Specification/Policy Object; Architectural baseline only.

Description:
- R1: Define this PostgreSQL backlog extension with PR-31 through PR-39, exact dependencies, branch names, Git states, PR names, commits, and one-to-one requirements/acceptance criteria.
- R2: Define the serving-plane contract: only current canonical `regime_features_daily` Gold is replicated to PostgreSQL `10.10.1.3:54321`; Parquet Gold remains authoritative.
- R3: Define credential ownership: runtime role exactly `market-regime-loader`, with a dedicated protected password that is never committed or logged.
- R4: Define temporal storage: `timestamp_m1` -> PostgreSQL `TIMESTAMPTZ(6)`, UTC session timezone, UTC-midnight observation-day identity.
- R5: Define sync semantics: first sync is complete Gold load; every later sync computes the complete accumulated full-state delta rather than relying on last timestamp or immediately previous Gold build.
- R6: Define logging: PostgreSQL sync uses the same project `.logs/market-regime-loader.log` stream.
- R7: Add an executable offline contract test validating PR-31..PR-39 metadata, PR-name presence in branch and commit, sequential PR IDs, valid status, and equal R/A counts.

Acceptance:
- A1 (verifies R1): the extension contains exactly PR-31 through PR-39 once each and every entry contains all required metadata.
- A2 (verifies R2): the document contains exactly the Gold-only serving target and states PostgreSQL is not canonical storage.
- A3 (verifies R3): the role identity is exactly `market-regime-loader` and no literal runtime/admin password is present.
- A4 (verifies R4): the timestamp contract is exactly `TIMESTAMPTZ(6)` plus UTC session timezone and observation-day semantics.
- A5 (verifies R5): bootstrap/full-load, accumulated-delta, missed-run, and historical-revision behavior are explicitly stated.
- A6 (verifies R6): the only declared project sync log path is `${PROJECT_ROOT}/.logs/market-regime-loader.log`.
- A7 (verifies R7): the offline contract test fails deterministically for missing PR-name/branch/commit metadata or R/A count mismatch.

## PR-32: PostgreSQL Gold Sync Contracts

PR name: `postgres-gold-sync-contracts`
Status: Planned
Updated: 2026-08-22
PR: none
Git branch: `pr-32/postgres-gold-sync-contracts`
Git status: `not-started (branch absent)`
Agent lane: Foundation; one weak agent
Depends on: PR-31
Commit: `feat(pr-32): postgres-gold-sync-contracts define gold sync boundary`
Design patterns: Ports and Adapters, Repository, Value Object, Dependency Injection.

Description:
- R1: Define exactly one published dataset contract: source `regime_features_daily` -> PostgreSQL `market_regime.regime_features_daily`; Bronze and Silver are not publishable.
- R2: Define internal synchronization identities `market_regime_sync.gold_sync_state` and `market_regime_sync.gold_row_hashes`, separate from the consumer Gold table.
- R3: Define immutable `GoldSyncState`, `GoldRowDigest`, `GoldDeltaPlan`, and `GoldSyncResult` contracts including inserted/updated/deleted/unchanged counts.
- R4: Define a narrow application-layer `GoldSyncRepository` Protocol for reading state/digests, applying an atomic delta, and post-write summary verification; application code must not import psycopg.
- R5: Define compatibility policy requiring exact source `schema_version` and `feature_version`; mismatch fails instead of silently performing a full rebuild.
- R6: Define source-selection policy requiring the catalog-selected current complete non-pruned Gold build and forbidding filesystem recency selection.
- R7: Define PostgreSQL temporal type contract `timestamp_m1 TIMESTAMPTZ(6) PRIMARY KEY` and mandatory UTC session timezone.

Acceptance:
- A1 (verifies R1): contract tests expose exactly one publishable Gold dataset and no Bronze/Silver dataset.
- A2 (verifies R2): exact consumer/internal table identities are constants and tested separately.
- A3 (verifies R3): all four immutable contracts expose exact deterministic fields/count semantics.
- A4 (verifies R4): a fake repository satisfies the Protocol with no psycopg import in `application/`.
- A5 (verifies R5): equal versions pass; schema or feature mismatch fails deterministically.
- A6 (verifies R6): only current complete non-pruned compatible Gold is selectable.
- A7 (verifies R7): timestamp contract is exactly `TIMESTAMPTZ(6)`/UTC and keyed by `timestamp_m1`.

## PR-33: Deterministic Gold Row Delta Planner

PR name: `gold-row-delta-planner`
Status: Planned
Updated: 2026-08-22
PR: none
Git branch: `pr-33/gold-row-delta-planner`
Git status: `not-started (branch absent)`
Agent lane: Agent A; pure logic
Depends on: PR-32
Commit: `feat(pr-33): gold-row-delta-planner compute complete gold delta`
Design patterns: Strategy/Policy Object; functional core.

Description:
- R1: Implement deterministic SHA-256 per canonical Gold row using exact `GOLD_COLUMNS` order, exact UTC epoch-microsecond timestamp encoding, explicit null markers, canonical finite Float64 encoding, and `-0.0 -> 0.0` normalization; reject NaN/infinity.
- R2: Implement pure complete-state comparison by `timestamp_m1` producing disjoint insert/update/delete/unchanged key sets.
- R3: If authoritative sync state and PostgreSQL digest state are both empty, classify every current Gold row as insert and no rows as update/delete.
- R4: Reject ambiguous bootstrap when sync state is absent but PostgreSQL digest state is non-empty.
- R5: Identical key/hash pairs must be unchanged only and never appear in write/delete sets.
- R6: Do not use a last-sync timestamp watermark or only the immediately preceding Gold build; historical changes and missed runs must remain discoverable.
- R7: Add deterministic tests for bootstrap, no-op, insert, update, delete, multiple missed runs, historical revision, nulls, zero/-zero, timestamp, and invalid floats.

Acceptance:
- A1 (verifies R1): equal canonical rows hash identically; one payload change changes the digest; null/value differ; `-0.0` and `0.0` match; NaN/infinity fail.
- A2 (verifies R2): fixtures produce exact mutually exclusive ordered delta sets.
- A3 (verifies R3): empty target plus N source rows yields exactly N inserts.
- A4 (verifies R4): non-empty digest state without sync state fails before a plan is emitted.
- A5 (verifies R5): unchanged rows never leak into mutation sets.
- A6 (verifies R6): an old-row correction and accumulated missed-week inserts are detected independent of prior build/time.
- A7 (verifies R7): all stated cases pass offline and repeated planning is deterministic.

## PR-34: PostgreSQL Gold Sync Adapter

PR name: `postgres-gold-sync-adapter`
Status: Planned
Updated: 2026-08-22
PR: none
Git branch: `pr-34/postgres-gold-sync-adapter`
Git status: `not-started (branch absent)`
Agent lane: Agent B; PostgreSQL persistence
Depends on: PR-32
Commit: `feat(pr-34): postgres-gold-sync-adapter implement transactional repository`
Design patterns: Adapter, Repository, Unit of Work, Dependency Injection.

Description:
- R1: Add psycopg as the only PostgreSQL runtime client; do not add SQLAlchemy or another ORM/client.
- R2: Implement connection configuration for exact host `10.10.1.3`, port `54321`, runtime role exactly `market-regime-loader`, configured database, and injected protected password; force PostgreSQL session timezone UTC.
- R3: Implement idempotent DDL for `market_regime.regime_features_daily` with exact canonical Gold columns, `timestamp_m1 TIMESTAMPTZ(6) PRIMARY KEY`, and all feature columns `DOUBLE PRECISION NULL`; no sync metadata columns belong in the consumer table.
- R4: Implement idempotent internal tables `market_regime_sync.gold_sync_state` and `market_regime_sync.gold_row_hashes` keyed by dataset and timestamp; state stores build/data/version/count/bounds/sync metadata.
- R5: Implement repository reads of state plus `(timestamp_m1,row_sha256)` digests only for delta calculation; do not fetch all target feature values.
- R6: Implement atomic `apply_delta` under a dataset-scoped advisory transaction lock: INSERT new rows, UPDATE changed rows, DELETE stale rows, mutate digest rows, write sync state last, then commit.
- R7: Allow complete-row insertion only for validated first bootstrap; non-bootstrap synchronization writes exactly supplied delta rows and never `TRUNCATE`, `DROP`, delete-all, or table replacement.
- R8: Roll back Gold rows, digests, and state together on any error.
- R9: Redact protected password and credential-bearing DSN from errors, repr, logging, and persisted metadata.
- R10: Add offline adapter tests using deterministic fakes/mocks for DDL, connection identity/timezone, transaction ordering, mutation counts, rollback, and redaction.

Acceptance:
- A1 (verifies R1): dependency inspection finds psycopg and no newly introduced ORM/second client.
- A2 (verifies R2): connection spy observes host `10.10.1.3`, port `54321`, user `market-regime-loader`, injected database/password, and UTC session timezone.
- A3 (verifies R3): consumer DDL has exact canonical column order/types and no sync columns.
- A4 (verifies R4): internal DDL and keys/fields are exact and idempotent.
- A5 (verifies R5): comparison reads fetch state and timestamp/hash pairs only.
- A6 (verifies R6): trace is advisory lock -> exact row mutations -> digest mutations -> sync-state write -> commit.
- A7 (verifies R7): first bootstrap can insert every source row; later `2 insert / 1 update / 1 delete` executes exactly those row mutations and forbidden full-reload SQL is absent.
- A8 (verifies R8): injected failures leave prior consumer/hash/state state unchanged.
- A9 (verifies R9): test password/full DSN never appears in diagnostics or persisted metadata.
- A10 (verifies R10): all stated offline adapter cases pass.

## PR-35: Provision Dedicated PostgreSQL Service Role

PR name: `postgres-service-role-provisioning`
Status: Planned
Updated: 2026-08-22
PR: none
Git branch: `pr-35/postgres-service-role-provisioning`
Git status: `not-started (branch absent)`
Agent lane: PostgreSQL operations; one weak agent
Depends on: PR-31
Commit: `feat(pr-35): postgres-service-role-provisioning add least privilege role setup`
Design patterns: Command, Least Privilege, Idempotent Provisioning.

Description:
- R1: Add an operator provisioning script/SQL contract targeting `10.10.1.3:54321` that creates or validates exactly one application LOGIN role named `market-regime-loader`.
- R2: Receive the dedicated role password only through protected runtime input; never embed it in tracked files, examples, logs, errors, or Git history.
- R3: Enforce role attributes `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`.
- R4: Provision/validate schemas `market_regime` and `market_regime_sync` with ownership or exactly sufficient CREATE/USAGE rights for this role and no blanket rights on other project schemas.
- R5: Keep administrator provisioning credentials separate from application runtime credentials and never accept them as the sync role.
- R6: Make provisioning idempotent and fail safely on incompatible pre-existing ownership/privilege state instead of broadening privileges silently.
- R7: Add offline SQL/command-contract tests for exact role name/attributes/schemas, runtime-secret placeholders, idempotency semantics, and absence of real credentials.

Acceptance:
- A1 (verifies R1): generated provisioning targets exact endpoint and quoted/unquoted SQL resolves the exact role name `market-regime-loader`.
- A2 (verifies R2): tracked provisioning content contains placeholders/env references only and no literal operational password.
- A3 (verifies R3): SQL contract sets all six exact least-privilege role attributes.
- A4 (verifies R4): only `market_regime` and `market_regime_sync` are provisioned/granted for the application role.
- A5 (verifies R5): admin credential inputs are distinct from runtime role/password outputs and are not exported to the application.
- A6 (verifies R6): second-run plan is logically idempotent and incompatible role/ownership state fails rather than escalating.
- A7 (verifies R7): all offline provisioning contract tests pass.

## PR-36: PostgreSQL Sync Operational Config

PR name: `postgres-sync-operational-config`
Status: Planned
Updated: 2026-08-22
PR: none
Git branch: `pr-36/postgres-sync-operational-config`
Git status: `not-started (branch absent)`
Agent lane: Operations; one weak agent
Depends on: PR-31
Commit: `feat(pr-36): postgres-sync-operational-config add repository postgres settings`
Design patterns: Adapter, Dependency Injection.

Description:
- R1: Extend protected ignored `config.yaml` contract with exact `runtime.postgres_host=10.10.1.3`, `runtime.postgres_port=54321`, `runtime.postgres_user=market-regime-loader`, required configured database, and required `secrets.postgres_password` dedicated to this repo role.
- R2: Extend `scripts/export_cron_config.py` to export shell-safe `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE`, and `PGPASSWORD` while preserving existing exports.
- R3: Validate exact host/port/user plus non-empty database/password; wrong user or missing/blank password fails before any connection.
- R4: Sanitize validation failures so the dedicated password/full credential-bearing connection text never appears.
- R5: Define the canonical log path as `${PROJECT_ROOT}/.logs/market-regime-loader.log`; `.logs/` and `config.yaml` remain ignored and runtime creates `.logs` when needed.
- R6: Add offline config/export/quoting/invalid-setting/redaction/gitignore tests; tests use placeholders only.

Acceptance:
- A1 (verifies R1): valid fixture resolves exact host `10.10.1.3`, port `54321`, user `market-regime-loader`, database, and protected repo password.
- A2 (verifies R2): exporter emits exact shell-safe PG variables in addition to existing variables.
- A3 (verifies R3): wrong host/port/user or empty database/password fails deterministically.
- A4 (verifies R4): test secrets never appear in error text.
- A5 (verifies R5): canonical log resolves under `.logs/market-regime-loader.log` and both `.logs/` and config are Git-ignored.
- A6 (verifies R6): all listed offline configuration cases pass without real credentials.

## PR-37: Gold To PostgreSQL Complete Delta Sync

PR name: `gold-postgres-delta-sync`
Status: Planned
Updated: 2026-08-22
PR: none
Git branch: `pr-37/gold-postgres-delta-sync`
Git status: `not-started (branch absent)`
Agent lane: Integration; one agent only
Depends on: PR-33, PR-34
Commit: `feat(pr-37): gold-postgres-delta-sync synchronize complete gold state`
Design patterns: Facade/Orchestrator, Unit of Work, Repository, Dependency Injection.

Description:
- R1: Implement a Gold sync application service that resolves only catalog current complete compatible Gold and reads its explicit immutable Parquet path; it must never trigger provider/Bronze/Silver/Gold-build/publication/retention work.
- R2: First sync requires absent sync state and empty PostgreSQL digest state, reads complete current Gold, and submits every source row as insert.
- R3: Every later sync compares the complete current Gold row-digest set with the complete PostgreSQL digest set and applies the entire accumulated delta, independent of elapsed time or missed Gold builds.
- R4: If synchronized `data_sha256`, versions, row count, and bounds equal current Gold, perform zero Gold/digest row mutations while allowing the dataset sync checkpoint to advance to the current build identity.
- R5: On changed Gold, submit only planned new/changed full rows and stale keys; unchanged rows are never submitted as consumer-row writes.
- R6: Historical revisions and stale PostgreSQL-only keys are propagated as update/delete in the serving replica without changing Bronze/Silver source-omission semantics.
- R7: Verify final PostgreSQL row count/min/max against current Gold before success; state must not claim success after verification failure.
- R8: All failure/retry paths are idempotent and preserve prior authoritative sync state until successful transaction/verification.
- R9: Emit a typed result with dataset/build and inserted/updated/deleted/unchanged counts; credentials are not part of application contracts.
- R10: Add offline fake-repository/catalog/build tests for first full sync, no-op, exact mixed delta, three missed runs, historical correction, delete, version mismatch, verification failure, and retry.

Acceptance:
- A1 (verifies R1): spies prove only current Gold resolution/read and sync repository calls occur.
- A2 (verifies R2): empty target plus N Gold rows produces exactly N inserts in one bootstrap plan.
- A3 (verifies R3): multiple missed weekly runs are fully caught up in one later sync.
- A4 (verifies R4): same data/version/count/bounds yields zero consumer/digest row mutations.
- A5 (verifies R5): fixture `2 new + 1 changed + 1 stale + 100 unchanged` submits exactly 2 inserts, 1 update, 1 delete and no unchanged writes.
- A6 (verifies R6): an old historical row correction becomes exactly one update and stale serving key exactly one delete while local lake state is untouched.
- A7 (verifies R7): mismatched post-write count/bounds fails and cannot report the new source build synchronized.
- A8 (verifies R8): injected failures preserve prior state and retry converges without duplicate rows.
- A9 (verifies R9): result fields/counts are exact and contain no credential fields.
- A10 (verifies R10): all stated offline sync use-case scenarios pass.

## PR-38: PostgreSQL Gold Sync CLI

PR name: `postgres-gold-sync-cli`
Status: Planned
Updated: 2026-08-22
PR: none
Git branch: `pr-38/postgres-gold-sync-cli`
Git status: `not-started (branch absent)`
Agent lane: CLI/composition; one weak agent
Depends on: PR-35, PR-36, PR-37
Commit: `feat(pr-38): postgres-gold-sync-cli expose repository postgres synchronization`
Design patterns: Command, Dependency Injection.

Description:
- R1: Add exactly one operational command `gold-sync-postgres` to the existing CLI.
- R2: Compose current Gold catalog/build readers, sync use case, and PostgreSQL adapter from protected `PGHOST/PGPORT/PGUSER/PGDATABASE/PGPASSWORD`; validate exact endpoint/user before connecting.
- R3: Command is read-only toward provider/Bronze/Silver/local Gold and must not build, publish, mirror, retain, or source-reconcile.
- R4: Use the existing structured JSON event sink and redaction mechanism; do not create a separate PostgreSQL logger/handler.
- R5: Emit `command=gold-sync-postgres`, stage/status, dataset/build, inserted/updated/deleted/unchanged counts and sanitized failure category.
- R6: Define stable non-zero handling for configuration/current-Gold/compatibility/PostgreSQL/verification errors and ensure missing config fails before connection creation.
- R7: Add offline parser/composition/result/no-side-effect/redaction/error tests.

Acceptance:
- A1 (verifies R1): parser exposes exactly `gold-sync-postgres` and dispatches only the sync use case.
- A2 (verifies R2): composition spy observes exact `10.10.1.3:54321`, user `market-regime-loader`, configured database, and protected password from runtime environment.
- A3 (verifies R3): no provider/Bronze/Silver/build/publish/mirror/retention/reconcile side effect is reachable.
- A4 (verifies R4): PostgreSQL sync logs through the existing event sink with no extra logger/file handler.
- A5 (verifies R5): success/no-op fixtures contain exact structured result fields and counts.
- A6 (verifies R6): each listed failure returns non-zero, claims no success, and missing config creates no DB connection.
- A7 (verifies R7): all stated CLI cases pass offline and test password/full DSN is absent from outputs.

## PR-39: Sunday PostgreSQL Gold Sync Cron

PR name: `sunday-postgres-gold-sync-cron`
Status: Planned
Updated: 2026-08-22
PR: none
Git branch: `pr-39/sunday-postgres-gold-sync-cron`
Git status: `not-started (branch absent)`
Agent lane: Operations; one weak agent
Depends on: PR-38
Commit: `feat(pr-39): sunday-postgres-gold-sync-cron chain gold sync after daily run`
Design patterns: Command; Architectural baseline only for declarative scheduling.

Description:
- R1: Change the main host cron from Saturday 10:00 to Sunday 10:00 host-local time using exactly `0 10 * * 0`.
- R2: Load protected config exports, ensure `${PROJECT_ROOT}/.logs` exists, run existing `run-daily`, then run `gold-sync-postgres` only if `run-daily` succeeds.
- R3: Redirect stdout/stderr from both commands to exactly `${PROJECT_ROOT}/.logs/market-regime-loader.log`; `/var/log/market-regime-loader.log` and separate PostgreSQL log files are forbidden.
- R4: First scheduled PostgreSQL sync fills complete current Gold history; subsequent scheduled syncs apply complete accumulated delta including missed weeks and historical revisions.
- R5: PostgreSQL failure makes the cron chain non-zero without rolling back already-published local Gold; documented recovery command runs only `gold-sync-postgres` and logs to the same project log.
- R6: Preserve source `reconcile` as a separate optional schedule; it is absent from the main update+PostgreSQL-sync chain.
- R7: Cron source/log examples must contain no literal PostgreSQL password/admin credential; exact host/port/user arrive only through protected config export.
- R8: Add offline cron/README regression coverage for expression, config loading, command order, `&&` gating, `.logs` path, first/full vs later/delta semantics, retry, no-reconcile, and no scheduled GitHub Actions ingestion.

Acceptance:
- A1 (verifies R1): the main template contains exactly `0 10 * * 0` and no Saturday main schedule.
- A2 (verifies R2): config export and `.logs` creation precede exact `run-daily && gold-sync-postgres` execution.
- A3 (verifies R3): both streams append to exactly `.logs/market-regime-loader.log` and `/var/log`/separate PG log destinations are absent.
- A4 (verifies R4): docs/tests state first full load and complete accumulated later deltas including missed-run/historical-revision cases.
- A5 (verifies R5): sync failure is non-zero, local current Gold remains authoritative, and manual retry invokes only `gold-sync-postgres` with the same log path.
- A6 (verifies R6): main cron contains no source reconcile and optional reconciliation remains separate.
- A7 (verifies R7): cron/docs/tests contain no operational PostgreSQL password/admin credential literals.
- A8 (verifies R8): all stated offline cron/documentation invariants pass.
