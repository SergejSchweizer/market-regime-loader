# Backlog

This backlog is the implementation source of truth for `market-regime-loader`.

The repository loads reusable daily market-state inputs from open/public sources, stores the maximum history exposed by each configured source, and performs restart-safe daily incremental updates. Data is managed with Polars and Parquet using a Bronze -> Silver -> Gold medallion architecture. Gold publication produces immutable Parquet data plus deterministic JSON and PNG sidecars.

Last reviewed: 2026-08-18

## Delivery Policy

- One `PR-XX` entry equals one logical pull request.
- PRs are intentionally small and explicit for two weak coding agents: one infrastructure boundary, provider family, transformation boundary, publication concern, or operational concern per PR.
- Every PR has `Status`, `Updated`, `PR`, `Git branch`, `Git status`, `Agent lane`, `Depends on`, and `Commit` metadata.
- Valid delivery statuses are `Planned`, `In Progress`, `Blocked`, `Ready`, and `Merged`.
- `Git status` is distinct from delivery status. Planned PRs use `not-started (branch absent)`. Active work must be updated to `active-clean`, `active-dirty: <paths>`, `pushed-ci-green`, or `merged`.
- Every `Description` requirement has an ID `R1`, `R2`, ... and every `Acceptance` item has the matching `A1`, `A2`, ... . Requirement and acceptance counts must match exactly.
- No PR may silently add responsibility outside its numbered requirements.
- Unit and required integration tests are offline. Live-provider tests must use `@pytest.mark.network` and are excluded from all required push/merge gates.
- Production data under `lake/` is ignored by Git and never committed.
- Polars is the production dataframe engine. Do not introduce pandas into production code.
- Parquet is the durable tabular format for Bronze, Silver, Gold, state, catalogs, and inventories. JSON/PNG are Gold sidecars only.
- Bronze/Silver never synthesize missing market observations. Gold features are causal and use only current/past observations.
- `README.md` and `ARCHITECTURE.md` are durable implementation sidecars. Any PR changing a documented contract updates the applicable sidecar in the same PR.

## Git Workflow Contract

Every implementation PR uses these exact conventions:

```text
Git branch: pr-XX/<kebab-case-description>
Commit:     type(pr-XX): <description>
```

Rules:

- Branch name and Conventional Commit scope contain the same `pr-XX` identifier as the backlog entry.
- Allowed commit types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`.
- Example: branch `pr-06/cboe-volatility-provider`, commit `feat(pr-06): ingest cboe volatility indices`.
- A PR starts only after every item in `Depends on` is merged to `main`; branch from dependency-complete `main`.
- Before each push, the repository pre-push gate must pass and `git status --short` must be empty.
- Before marking `Ready`, the branch must be pushed, the four parallel execution checks plus the `coverage` check must be green, combined production-code line coverage must be at least `90.0%`, and the PR backlog field must read `Git status: pushed-ci-green`.
- After merge, set `Status: Merged`, fill `PR`, and set `Git status: merged`.
- Do not force-push shared branches, reuse a branch for another PR, or resolve semantic conflicts by guessing.

Current planning state: no planned `pr-XX/...` implementation branches exist, therefore every PR below starts with `Git status: not-started (branch absent)`.

## Push And Merge Quality Gates

Quality gates are part of the repository contract, not optional agent advice.

### Coverage threshold

Required combined **production-code line coverage is `>= 90.0%`** on every push and merge candidate.

Coverage scope is the production Python code under:

```text
application/
ingestion/
api/
scripts/
```

Tests, fixtures, generated artifacts, and the runtime `lake/` are excluded from the denominator. The threshold is calculated from the **combined** results of the unit and offline integration suites; neither suite is required to reach 90% in isolation. Live `network` tests never contribute to the required threshold.

### Local pre-push gate

The repository-managed pre-push hook starts these four execution classes **in parallel**:

```text
lint
type
unit
integration
```

`unit` and `integration` write separate coverage data files. After both test classes finish successfully, a `coverage` aggregation step combines their data and runs the equivalent of:

```text
coverage report --fail-under=90
```

A non-zero result from any of the four parallel classes **or** combined coverage below `90.0%` blocks `git push`. The integration class is offline and excludes `network` tests.

### Remote push gate

GitHub Actions starts the same four independent jobs on every `push`. The `unit` and `integration` jobs upload separate raw coverage artifacts. A fifth job named exactly `coverage` depends only on `unit` and `integration`, downloads/combines their coverage data, and fails below `90.0%`.

A feature branch is not considered ready unless all five checks are green:

```text
lint
type
unit
integration
coverage
```

### Pull-request / merge gate

The same five checks run for:

```text
pull_request -> main
merge_group
```

`main` must be protected/ruleset-controlled so merging requires all five exact checks:

```text
lint
type
unit
integration
coverage
```

Direct pushes to `main` are forbidden. `merge_group` support keeps the same checks valid when a merge queue is enabled.

The first four jobs must not depend on one another and therefore run in parallel. The `coverage` job is deliberately an aggregation gate with `needs: [unit, integration]`; it must not rerun the test suites or replace either required test check.

## Parallel-Agent Rules

Two weak agents are expected to work in parallel.

- **Agent A:** registry/path contracts, CBOE/STOXX/Yahoo, Silver, volatility Gold, immutable Gold storage, build sidecars.
- **Agent B:** Parquet IO, shared HTTP client, ECB/FRED, operational manifests/inventory, macro Gold, Gold catalog.
- **Integration/Foundation:** use the first free agent only after listed dependencies merge; do not overlap integration PRs with unresolved dependency PRs.
- Provider PRs are deliberately independent of one another once their common foundations are merged. The backlog does not encode fake serial dependencies merely because the same agent is likely to execute them sequentially.
- If two PRs ultimately touch the same file, the later branch must rebase on current dependency-complete `main` before implementation.

## Initial Series Catalog

| Canonical series ID | Primary source | Source series / file | Native shape | Provider capability | Bootstrap policy |
|---|---|---|---|---|---|
| `vix` | CBOE | `VIX_History.csv` | `ohlc` | `full_file` | complete public history |
| `vix9d` | CBOE | `VIX9D_History.csv` | `ohlc` | `full_file` | complete public history |
| `vix3m` | CBOE | `VIX3M_History.csv` | `ohlc` | `full_file` | complete public history when exposed |
| `vix6m` | CBOE | `VIX6M_History.csv` | `ohlc` | `full_file` | complete public history when exposed |
| `vix1y` | CBOE | `VIX1Y_History.csv` | `ohlc` | `full_file` | complete public history when exposed |
| `vstoxx` | STOXX | `V2TX` | `scalar` | `full_file` | maximum exposed public history |
| `move` | Yahoo Finance | `^MOVE` | `ohlc` | `date_range` | maximum available history |
| `ciss` | ECB Data Portal | `CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX` | `scalar` | `date_range` | complete exposed ECB history |
| `estr` | ECB Data Portal | `EST.B.EU000A2X2A25.WT` | `scalar` | `date_range` | complete exposed ECB history |
| `euro_hy_oas` | FRED | `BAMLHE00EHYIOAS` | `scalar` | `date_range` | all currently exposed observations; never truncate older local history |
| `us_2y` | FRED | `DGS2` | `scalar` | `date_range` | complete exposed history |
| `us_10y` | FRED | `DGS10` | `scalar` | `date_range` | complete exposed history |
| `usd_broad` | FRED | `DTWEXBGS` | `scalar` | `date_range` | complete exposed history |

No additional series belongs in the MVP without a separate backlog PR. The registry is the authority; provider modules do not invent symbols or implicit fallbacks.

## Medallion Storage Contract

```text
lake/
  bronze/
    provider=<provider>/series=<series_id>/year=<YYYY>/month=<MM>/data.parquet
  silver/
    series=<series_id>/year=<YYYY>/month=<MM>/data.parquet
  gold/
    dataset=regime_features_daily/
      versions/build_id=<YYYYMMDDTHHMMSSZ>/
        data.parquet
        manifest.json
        feature_profile.png
      manifest.parquet
      manifest.json
      feature_profile.png
  state/
    ingestion_state.parquet
  manifests/
    ingestion_runs.parquet
    dataset_inventory.parquet
```

### Bronze common contract

```text
series_id: String
provider: String
observation_date: Date
fetched_at_utc: Datetime(time_zone="UTC")
source_id: String
source_url: String
```

Native payload columns are exactly one of `open/high/low/close` or scalar `value`. Natural key: `(provider, series_id, observation_date)`.

### Silver contract

```text
observation_date: Date
series_id: String
value: Float64
open: Float64 nullable
high: Float64 nullable
low: Float64 nullable
close: Float64 nullable
unit: String
provider: String
source_id: String
fetched_at_utc: Datetime(time_zone="UTC")
```

Natural key: `(series_id, observation_date)`. OHLC sources use `value=close`; scalar sources use `value` and null OHLC fields.

### Gold timestamp contract

```text
timestamp_m1: Datetime(time_unit="us", time_zone="UTC")
```

`timestamp_m1` is the first Gold column, unique and strictly increasing. Silver dates map to `00:00:00 UTC`. Gold contains no `observation_date`. `_m1` is an interoperability name only; the dataset remains daily. This timestamp identifies the source observation day and is **not** a provider publication/availability timestamp.

### Gold feature-math contract

All `delta_Nobs` features use observation lags rather than calendar-day subtraction:

```text
delta_Nobs(t) = x(t) - x(previous Nth valid observation)
```

All `zscore_60obs` features use the last 60 valid observations including `t`, population standard deviation (`ddof=0`), and are null before 60 observations or when standard deviation is zero. Cross-series ratios/spreads use only same-`timestamp_m1` values. No forward-fill, backward-fill, interpolation, centered windows, or as-of carry is allowed in the MVP.

### Gold semantic version contract

```text
schema_version  = 1
feature_version = 1
```

Increment `schema_version` only when Gold column names/order/types change. Increment `feature_version` when formulas/parameters change without a schema change. Versions are source-controlled constants; runtime never auto-increments them.

### Gold root catalog contract

`lake/gold/dataset=regime_features_daily/manifest.parquet` is the only authoritative current-selection catalog.

Exact fields:

```text
dataset_id
build_id
status                 # building | complete | failed
current
started_at_utc
completed_at_utc
schema_version
feature_version
min_timestamp
max_timestamp
row_count
data_path
build_manifest_path
plot_path
```

Root `manifest.json` mirrors the authoritative catalog for inspection. Root `feature_profile.png` belongs to the authoritative current build. Neither sidecar chooses current independently.

## Incremental Update Contract

1. No Bronze history -> bootstrap maximum available public history.
2. Existing history -> `start = latest_stored_date - overlap_days`, default 7 calendar days; `end = injected_today`.
3. `date_range` providers receive exact bounds.
4. `full_file` providers may refetch their compact public file but diff/write only inserted or revised rows.
5. Shorter upstream responses never delete older local history.
6. Only affected Bronze/Silver monthly partitions are rewritten.
7. State advances only after durable data plus success-run persistence.
8. Unchanged reruns are logical and physical no-ops for Bronze/Silver partitions.

## PR Graph

```text
PR-01 bootstrap + quality gates
  |\
  | +--> PR-03 Parquet IO --------------------+
  | +--> PR-04 shared HTTP                    |
  +----> PR-02 contracts --------+            |
                                 +--> PR-05 planner/state
                                 |       |
                                 |       +--> PR-06 CBOE ----+
                                 |       +--> PR-07 STOXX ---+
                                 |       +--> PR-08 Yahoo ---+--> PR-12 Bronze orchestration
                                 |       +--> PR-09 ECB -----+         |
                                 |       +--> PR-10 FRED ----+         v
                                 |                           |      PR-13 Silver
                                 +--> PR-11 manifests -------+       /       \
                                          |                        /         \
                                          +--> PR-14 inventory   PR-15     PR-16
                                               CLI              volatility   macro
                                                                    \       /
                                                                     PR-17 Gold frame
                                                                      /      \
                                                               PR-18 storage PR-19 catalog
                                                                     |          |
                                                               PR-20 sidecars   |
                                                                      \        /
                                                                       PR-21 publication
                                                                              |
                                                                         PR-22 retention
                                                                              |
                                                     PR-14 inventory CLI ------+------ PR-23 daily pipeline
```

---

## PR-01: Bootstrap Python Repository And Enforced Quality Gates

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-01/repository-bootstrap-quality-gates`

Git status: `not-started (branch absent)`

Agent lane: Foundation; one agent only

Depends on: none

Commit: `chore(pr-01): bootstrap repository and quality gates`

Description:
- R1: Create a `uv`/`pyproject.toml` project for Python >=3.13 with runtime dependencies `polars`, `pyarrow`, `httpx`, `pydantic`, `PyYAML`, and `matplotlib`, plus development dependencies `pytest`, `pytest-cov`, `coverage`, `ruff`, and `mypy`; configure coverage source to `application/`, `ingestion/`, `api/`, and `scripts/`, excluding tests/fixtures/generated/runtime lake files; do not add pandas to production dependencies.
- R2: Create minimal importable package roots `application/`, `ingestion/`, `api/`, `scripts/`, `tests/unit/`, `tests/integration/`, and `tests/fixtures/`; register pytest markers `integration` and `network`, with `network` excluded from every required quality gate.
- R3: Add Makefile targets `lint`, `type`, `unit`, `integration`, `coverage`, and `quality-gate`; `lint` runs `ruff format --check` plus `ruff check`, `type` runs mypy, `unit` and `integration` run their respective offline pytest suites while writing distinct coverage data files, `coverage` combines those files and enforces total production-code line coverage `>=90.0%`, and `quality-gate` starts `lint|type|unit|integration` in parallel then runs the coverage aggregation after both test suites succeed.
- R4: Add a repository-managed pre-push hook plus an idempotent installer command so an installed hook runs the four execution classes in parallel and then the combined `coverage` gate before `git push`; any failed class or combined line coverage below `90.0%` blocks the push.
- R5: Add `.github/workflows/quality-gates.yml` triggered by `push`, `pull_request` targeting `main`, and `merge_group`, with four independent parallel jobs named exactly `lint`, `type`, `unit`, and `integration`; `unit` and `integration` upload distinct raw coverage artifacts, and a fifth required job named exactly `coverage` with `needs: [unit, integration]` downloads/combines them and enforces `>=90.0%` without rerunning tests.
- R6: Add a Conventional Commits validator for implementation commits: subjects must match `<type>(pr-XX): <description>` where type is one of `feat|fix|docs|test|refactor|perf|build|ci|chore`, and the `pr-XX` scope must match the PR identifier encoded in the feature branch name; generated merge-group commits are excluded from this subject check.
- R7: Add a documented/scripted GitHub merge-gate setup requiring the five exact checks `lint`, `type`, `unit`, `integration`, and `coverage` on `main`, requiring pull requests, preventing direct pushes to `main`, and supporting merge queue/`merge_group` checks when enabled.
- R8: Add `.gitignore` rules for `.venv/`, Python/test/coverage caches, temporary quality-gate output, and the complete `lake/` runtime tree; update `README.md` and `ARCHITECTURE.md` only where bootstrap/tooling behavior is documented.

Acceptance:
- A1 (verifies R1): `uv sync --extra dev` resolves the stated dependency families including explicit `coverage`; coverage configuration includes exactly the declared production roots/exclusions and production dependency inspection finds no pandas.
- A2 (verifies R2): All required package/test roots import or exist, pytest recognizes both markers, and default required tests never select `network` tests.
- A3 (verifies R3): Each Make target runs the stated tool/test class; unit/integration create separate readable coverage data, their combination reports the union, `89.99%` fails while `90.00%` passes, and an injected failure in any parallel child makes `make quality-gate` non-zero while the other execution classes are still started independently.
- A4 (verifies R4): Hook installation is idempotent; clean fake execution plus coverage `>=90.0%` permits push, while a failed execution class or coverage `<90.0%` exits non-zero before push proceeds.
- A5 (verifies R5): Workflow contract tests prove all three triggers exist, `lint|type|unit|integration` have no inter-job `needs`, unit/integration upload distinct coverage artifacts, `coverage` depends exactly on the two test jobs, combines both artifacts, uses `--fail-under=90`, and all five checks are required outputs of the workflow.
- A6 (verifies R6): Valid examples such as `feat(pr-06): ingest cboe volatility indices` pass; missing scope, wrong PR scope, invalid type, and malformed subjects fail deterministically.
- A7 (verifies R7): The setup documentation/script names all five required checks exactly including `coverage`, disallows direct `main` pushes, and documents the one-time repository-setting step needed if GitHub permissions prevent automatic configuration.
- A8 (verifies R8): Ignored artifacts are not tracked, and the documentation sidecars remain consistent with the bootstrap/quality-gate contract.

## PR-02: Define Series Registry And Lake Path Contracts

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-02/series-registry-lake-contracts`

Git status: `not-started (branch absent)`

Agent lane: Agent A

Depends on: PR-01

Commit: `feat(pr-02): define series and lake contracts`

Description:
- R1: Add one immutable typed registry containing exactly the 13 initial canonical series with `series_id`, provider, source ID/file, unit, native shape, frequency, bootstrap strategy, and provider capability.
- R2: Make provider capabilities explicit as only `date_range` or `full_file`; make native shapes explicit as only `ohlc` or `scalar`, with `vstoxx` normalized to the scalar contract instead of the current ambiguous `scalar/provider-native` wording.
- R3: Add typed helpers for Bronze/Silver monthly paths, Gold dataset root, version `data.parquet`, build `manifest.json`, build `feature_profile.png`, root `manifest.parquet`, root `manifest.json`, root `feature_profile.png`, ingestion state, ingestion-run manifest, and inventory paths.
- R4: Validate duplicate canonical IDs, unknown providers, empty source IDs, invalid units/frequencies, unsupported native shapes, and unsupported provider capabilities before adapter execution; add exact fixed-path tests for observation date `2026-08-18` and Gold build `20260818T020000Z`.

Acceptance:
- A1 (verifies R1): Registry contains exactly 13 populated entries and no additional series.
- A2 (verifies R2): Only declared enum values pass and `vstoxx` is unambiguously scalar/full-file.
- A3 (verifies R3): Path helpers return every exact documented path without provider-local hard-coded duplicates.
- A4 (verifies R4): Every stated invalid condition fails before an adapter is called and all fixed path tests pass.

## PR-03: Implement Polars Parquet Lake Read, Diff, And Upsert Utilities

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-03/polars-parquet-lake-io`

Git status: `not-started (branch absent)`

Agent lane: Agent B

Depends on: PR-01

Commit: `feat(pr-03): add polars parquet lake io`

Description:
- R1: Implement deterministic Polars-only reads for zero, one, or many monthly Parquet partitions and return stable sort order supplied by the caller's natural key.
- R2: Implement atomic destination-filesystem writes using same-directory temporary files, flush/fsync where supported, and `os.replace`; a failed write must leave the previous destination readable and remove/ignore its temp artifact on restart.
- R3: Implement a pure logical diff/upsert by caller-supplied natural key: classify inserts, unchanged rows, and revisions; new equal-key rows replace old ones exactly once; duplicate keys in incoming data are rejected rather than resolved by row order.
- R4: Rewrite only monthly partitions containing inserted/revised rows; a logical no-op must not rewrite any monthly file and unrelated partitions must remain byte/mtime unchanged.
- R5: Add tests for empty/single/multi-month reads, duplicate incoming keys, revision replacement, no-op physical preservation, deterministic ordering, same-directory atomic replacement, simulated interrupted temp file, and unaffected-month preservation.

Acceptance:
- A1 (verifies R1): Fixtures prove all three read modes, stable caller-key ordering, and production lake code contains no pandas import.
- A2 (verifies R2): Successful writes leave one valid destination and no live temp; injected pre-replace failure retains the old Parquet; a stale temp does not become authoritative on read/restart.
- A3 (verifies R3): Fixtures classify inserts/unchanged/revisions exactly; identical rerun produces no changes; duplicate incoming natural keys fail deterministically.
- A4 (verifies R4): No-op update preserves destination hash/mtime and an update to one month leaves every unrelated month unchanged.
- A5 (verifies R5): Every listed IO/diff/restart case has a focused passing offline test.

## PR-04: Add Shared HTTP Client And Provider Adapter Port

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-04/shared-http-provider-port`

Git status: `not-started (branch absent)`

Agent lane: Agent B

Depends on: PR-01

Commit: `feat(pr-04): add shared http provider port`

Description:
- R1: Define a narrow application-facing HTTP request/response port and provider adapter protocol so provider modules do not construct unrelated `httpx.Client` instances or leak HTTP details into orchestration.
- R2: Implement one `httpx` adapter with explicit connect/read/write/pool timeouts, injected retry policy, bounded attempts, retry only for documented transient transport errors plus HTTP `429` and `5xx`, and no retry for other `4xx` responses.
- R3: Implement deterministic bounded exponential backoff with injectable sleep and no random jitter in tests; honor numeric `Retry-After` when present without exceeding the configured maximum delay.
- R4: Define typed provider errors carrying provider, canonical series ID, source ID, request context, and status/error category while never embedding API keys, authorization values, or full secret query strings.
- R5: Add offline tests for success, timeout, transport error, retryable 429/5xx, non-retryable 4xx, retry exhaustion, Retry-After, injected sleep sequence, and secret redaction.

Acceptance:
- A1 (verifies R1): Provider-facing test doubles implement one stable protocol and application code can orchestrate them without importing `httpx`.
- A2 (verifies R2): Mocked responses prove exact retry/non-retry categories, attempt limits, and explicit timeout configuration.
- A3 (verifies R3): Fixed configuration produces the exact expected sleep sequence, Retry-After is honored within the cap, and tests never perform real sleeping.
- A4 (verifies R4): Error fixtures expose all safe identity/context fields and assertions prove configured secrets never appear in messages/representations.
- A5 (verifies R5): Every stated HTTP/retry/error case passes offline.

## PR-05: Implement Bootstrap, Incremental Planner, And Ingestion State

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-05/incremental-planner-state`

Git status: `not-started (branch absent)`

Agent lane: Foundation; first free agent

Depends on: PR-02, PR-03

Commit: `feat(pr-05): add incremental ingestion planner`

Description:
- R1: Implement a pure planner that returns `bootstrap` when no Bronze observations exist and `incremental` when a latest stored observation exists; planner input includes canonical series contract, durable latest date, injected `today`, and overlap days.
- R2: For incremental mode compute `logical_start=latest_stored_date-overlap_days` with default `7` calendar days and `logical_end=injected_today`; reject `logical_end < logical_start` and non-positive/invalid configuration.
- R3: Map logical plans to provider instructions: `date_range` emits exact start/end bounds; `full_file` emits a complete-file request while retaining logical bounds as metadata for diff/state/audit.
- R4: Define `ingestion_state.parquet` with explicit schema and unique key `(provider, series_id)`, including `last_success_utc`, `last_observed_date`, `last_requested_start`, `last_requested_end`, `mode`, `fetched_row_count`, and `changed_row_count`; writes use shared atomic/upsert IO.
- R5: State advances only after a caller reports durable data and success-manifest persistence; failed/no-durable execution retains the previous state exactly.
- R6: Use only injected dates/times in planner/state code and tests; no direct `date.today()`, `datetime.now()`, or hidden wall-clock dependency is allowed in the application path.

Acceptance:
- A1 (verifies R1): No-history/history fixtures return exact bootstrap/incremental plans for every capability class.
- A2 (verifies R2): Tests prove default/custom overlap, exact injected end date, and all invalid ranges/configurations fail deterministically.
- A3 (verifies R3): The two capability types produce exact documented provider instructions while retaining identical logical-plan metadata.
- A4 (verifies R4): State schema/types round-trip and repeated equal-key update leaves exactly one row.
- A5 (verifies R5): Failure/no-durable fixtures preserve the previous state byte/logically; success advances only after the simulated durability barrier.
- A6 (verifies R6): Static/runtime tests prove deterministic injected-clock behavior with no production planner use of wall-clock functions.

## PR-06: Add CBOE Volatility-Index Provider

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-06/cboe-volatility-provider`

Git status: `not-started (branch absent)`

Agent lane: Agent A

Depends on: PR-02, PR-04, PR-05

Commit: `feat(pr-06): ingest cboe volatility indices`

Description:
- R1: Implement one CBOE adapter for exactly `vix`, `vix9d`, `vix3m`, `vix6m`, and `vix1y` using the registered public daily-history CSV sources and shared provider/HTTP ports.
- R2: Treat all five CBOE sources as `full_file`; build the request only from registry source metadata and reject unregistered symbols/source IDs.
- R3: Parse provider dates plus OHLC columns into the exact Bronze common+OHLC contract with Polars; reject invalid dates, duplicate provider dates, missing/non-finite close, or rows that cannot satisfy the natural key.
- R4: A shorter later response never means deletion: diff it against retained Bronze, write only inserts/revisions, and permit equal-key source revisions to replace prior rows.
- R5: If a registered CBOE public file is unavailable, return the typed provider error naming canonical series/source; do not silently fallback or synthesize data.
- R6: Add committed representative fixtures and offline tests for all five routes, valid parsing, duplicate date, invalid OHLC, revised close, shortened response preservation, unavailable file, and shared HTTP error propagation.

Acceptance:
- A1 (verifies R1): Exactly the five registered canonical IDs route through the CBOE adapter and no other series is accepted.
- A2 (verifies R2): Mocked requests prove full-file behavior and exact registry source use with no hard-coded alternative source.
- A3 (verifies R3): Fixture output has the exact typed Bronze+OHLC schema and every stated invalid row/duplicate condition fails.
- A4 (verifies R4): Truncated response preserves historical minimum/rows while overlap revision changes only matching keys/affected month.
- A5 (verifies R5): Unavailable fixture returns the typed error and no fallback adapter/source is invoked.
- A6 (verifies R6): All stated provider behaviors pass without network access.

## PR-07: Add STOXX VSTOXX Provider

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-07/stoxx-vstoxx-provider`

Git status: `not-started (branch absent)`

Agent lane: Agent A

Depends on: PR-02, PR-04, PR-05

Commit: `feat(pr-07): ingest vstoxx history`

Description:
- R1: Implement a STOXX adapter only for canonical `vstoxx` / registered `V2TX` source using the shared provider/HTTP ports.
- R2: Parse the selected public source into the registry-declared scalar Bronze contract `value: Float64`; do not allow provider-native shape guessing at runtime.
- R3: Use the registry-declared `full_file` capability and maximum exposed public history; a shorter later upstream response never deletes older local rows.
- R4: Reject invalid/duplicate dates and non-finite/missing scalar values; equal-key valid revisions replace retained values through shared diff/upsert.
- R5: Add a representative committed fixture plus offline tests for bootstrap parse, stable `source_id=V2TX`, duplicate/invalid value rejection, revision, shortened-response preservation, and HTTP error propagation.

Acceptance:
- A1 (verifies R1): Only `vstoxx` with registered source metadata is accepted.
- A2 (verifies R2): Output is exactly common Bronze fields plus scalar `value: Float64`, never an ambiguous OHLC/provider-native shape.
- A3 (verifies R3): Request behavior is full-file and shorter responses cannot reduce retained earliest date/row set.
- A4 (verifies R4): Duplicate/invalid fixtures fail and a valid equal-key revision replaces once.
- A5 (verifies R5): Every stated STOXX scenario passes offline.

## PR-08: Add Yahoo MOVE Provider

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-08/yahoo-move-provider`

Git status: `not-started (branch absent)`

Agent lane: Agent A

Depends on: PR-02, PR-04, PR-05

Commit: `feat(pr-08): ingest move index history`

Description:
- R1: Implement a Yahoo adapter only for canonical `move` and registered ticker `^MOVE` using shared provider/HTTP ports; reject unrelated tickers.
- R2: Bootstrap maximum available daily history and, in incremental mode, pass the planner's exact date-range bounds through the adapter without silently expanding/shrinking them.
- R3: Normalize only daily OHLC market fields into exact common Bronze+OHLC columns; exclude volume/dividend/split/corporate-action fields and reject invalid/duplicate dates or missing/non-finite close.
- R4: Equal-key revisions replace retained rows once; empty bounded responses are valid no-op results and do not advance observation coverage by fabrication.
- R5: Add offline tests for max-history bootstrap args, exact bounded args, empty result, invalid/duplicate row, revised date, OHLC normalization, and shared HTTP error propagation.

Acceptance:
- A1 (verifies R1): Only the registry mapping `move -> ^MOVE` is accepted.
- A2 (verifies R2): Mocked calls prove exact bootstrap/max and incremental-bound request arguments.
- A3 (verifies R3): Output columns/types exactly match common Bronze+OHLC and prohibited corporate-action fields never appear.
- A4 (verifies R4): Empty response yields no inserted rows/state fabrication and revision updates the equal key once.
- A5 (verifies R5): All stated Yahoo scenarios pass offline.

## PR-09: Add ECB CISS And ESTR Provider

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-09/ecb-ciss-estr-provider`

Git status: `not-started (branch absent)`

Agent lane: Agent B

Depends on: PR-02, PR-04, PR-05

Commit: `feat(pr-09): ingest ecb regime series`

Description:
- R1: Implement an ECB adapter for exactly registered `ciss` and `estr` source keys using the shared provider/HTTP ports.
- R2: Bootstrap the complete exposed series history and pass exact planner date bounds in incremental mode; keep request construction registry-driven.
- R3: Parse dates/scalars with Polars into the exact Bronze scalar contract; missing/non-numeric/non-finite observations are absent, not zero; duplicate dates are rejected.
- R4: Calendar gaps remain gaps, overlap revisions replace equal keys once, and the adapter does not forward-fill/back-fill weekends or holidays.
- R5: Propagate typed HTTP/provider errors with safe source identity and no secret leakage.
- R6: Add representative fixtures/tests for both series, bootstrap and bounded requests, missing/non-numeric values, duplicate date, one revision, one normal calendar gap, and HTTP error propagation.

Acceptance:
- A1 (verifies R1): Exactly the two registered ECB canonical/source mappings are accepted.
- A2 (verifies R2): Mocked calls prove complete-history bootstrap and exact incremental bounds.
- A3 (verifies R3): Valid output is exact Bronze scalar schema and every invalid/missing/duplicate case behaves as specified.
- A4 (verifies R4): Gap fixture remains absent and revision replaces only the matching key with no synthetic row.
- A5 (verifies R5): Safe typed provider error is preserved through adapter boundary.
- A6 (verifies R6): All stated ECB cases pass offline.

## PR-10: Add FRED Rates, Credit, And Dollar Provider

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-10/fred-rates-credit-dollar-provider`

Git status: `not-started (branch absent)`

Agent lane: Agent B

Depends on: PR-02, PR-04, PR-05

Commit: `feat(pr-10): ingest fred regime series`

Description:
- R1: Implement one FRED adapter mapping exactly registered `DGS2`, `DGS10`, `DTWEXBGS`, and `BAMLHE00EHYIOAS` to `us_2y`, `us_10y`, `usd_broad`, and `euro_hy_oas` through shared provider/HTTP ports.
- R2: Bootstrap all currently exposed history and use exact planner date bounds in incremental mode; no implicit provider fallback.
- R3: Parse dates/scalar values with Polars into exact Bronze scalar contract; treat `.`, blank, missing, and non-finite values as absent and reject duplicate dates.
- R4: A shorter later `euro_hy_oas` response cannot truncate older retained history; valid overlap revisions still replace equal keys once.
- R5: Define API-key configuration through environment/config injection without putting secrets in registry, URLs written to Bronze, logs, error strings, or committed fixtures.
- R6: Add fixtures/tests for all four series, request modes, missing values, duplicate handling, one revision, shortened HY history, and secret-redaction behavior.

Acceptance:
- A1 (verifies R1): Only the four documented source IDs map to the four canonical FRED series.
- A2 (verifies R2): Mocked requests prove full-history bootstrap and exact bounded incremental behavior.
- A3 (verifies R3): Missing markers emit no fabricated row and duplicates/non-finite values fail as documented.
- A4 (verifies R4): Shortened HY response preserves prior historical minimum/rows and overlap revision updates exactly once.
- A5 (verifies R5): Tests inspect registry, persisted `source_url`, logs/errors, and fixture tree and find no API key value.
- A6 (verifies R6): All listed FRED scenarios pass offline.

## PR-11: Add Bronze Coverage Inventory And Ingestion-Run Manifests

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-11/bronze-inventory-run-manifests`

Git status: `not-started (branch absent)`

Agent lane: Agent B

Depends on: PR-02, PR-03

Commit: `feat(pr-11): add bronze inventory and run manifests`

Description:
- R1: Define `dataset_inventory.parquet` with one row per canonical series and exact fields `series_id`, `provider`, `min_observation_date`, `max_observation_date`, `row_count`, `duplicate_key_count`, and `file_count` (seven columns including series identity).
- R2: Define `ingestion_runs.parquet` keyed by unique `run_id` with provider, series ID, mode, requested bounds, fetched rows, inserted rows, revised rows, written partition count, status (`success|failed`), started/completed UTC, and sanitized error category/message.
- R3: Persist both files with deterministic typed schemas and atomic/upsert utilities; inventory is replaced as an authoritative snapshot, while run manifest appends/upserts unique run IDs without rewriting source data.
- R4: Do not invent expected-calendar completeness, weekend/holiday missing counts, or fill gaps; coverage means observed stored boundaries/counts only.
- R5: Failed run records must not contain secrets and must not claim inserted/revised partitions that were not durable.
- R6: Add tests for empty/populated inventory, exact schemas, duplicate detection, successful run, failed run, repeat same run ID, and sanitized errors.

Acceptance:
- A1 (verifies R1): Inventory exposes exactly one row per registered series with the seven stated fields and correct values from fixed lake fixtures.
- A2 (verifies R2): Success/failure fixtures contain every exact run field and allowed status only.
- A3 (verifies R3): Inventory snapshot and run upsert round-trip with deterministic ordering/types and no duplicate run ID.
- A4 (verifies R4): No expected-calendar or synthetic missing-day metric exists in output/schema.
- A5 (verifies R5): Failed-run fixture contains no configured secret and no false durable-change counts.
- A6 (verifies R6): All stated manifest/inventory cases pass offline.

## PR-12: Add Registry-Driven Bronze Orchestration

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-12/bronze-orchestration`

Git status: `not-started (branch absent)`

Agent lane: Integration; one agent only

Depends on: PR-03, PR-05, PR-06, PR-07, PR-08, PR-09, PR-10, PR-11

Commit: `feat(pr-12): orchestrate bronze updates`

Description:
- R1: Add an application service accepting canonical series IDs, resolving registry contract+planner, routing each series only to its registered provider adapter, and using shared diff/write/state/run-manifest ports; orchestration must not import provider HTTP implementation details.
- R2: Implement `bootstrap` and `update` operation modes with injected current date/time; bootstrap rejects already-populated selected series unless explicit future reset behavior is separately specified.
- R3: Isolate each selected series transaction boundary: one provider failure records that run failed and does not corrupt another series that successfully reaches its durability barrier.
- R4: For success, durable order is Bronze partition write -> success run manifest -> ingestion state update; failure before that barrier leaves prior state and authoritative Bronze intact except already completed independent series.
- R5: A logical no-op update writes a success run with zero inserted/revised/partition counts, does not rewrite Bronze partitions, and may advance `last_success_utc` while leaving `last_observed_date` unchanged.
- R6: Add fake-adapter/temporary-lake tests for routing, bootstrap guard, bounded/full-file execution, one partial provider failure, restart after failure, no-op rerun, revision rerun, and multi-series isolation.

Acceptance:
- A1 (verifies R1): Fake adapters prove exact registry routing and no provider implementation import appears in application orchestration.
- A2 (verifies R2): Fixed-clock fixtures select exact operations and bootstrap-on-populated fails before provider fetch.
- A3 (verifies R3): One simulated provider failure coexists with another independently successful readable series/run/state.
- A4 (verifies R4): Failure injection at each pre-barrier point preserves prior state/authoritative Bronze; success advances state only after simulated durable data+manifest.
- A5 (verifies R5): No-op keeps every Bronze file hash/mtime unchanged, records zero changes, and does not fabricate a newer observation date.
- A6 (verifies R6): All listed orchestration/restart/isolation cases pass offline.

## PR-13: Build Canonical Silver Daily Series

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-13/silver-canonical-series`

Git status: `not-started (branch absent)`

Agent lane: Agent A

Depends on: PR-12

Commit: `feat(pr-13): build canonical silver series`

Description:
- R1: Implement a registry-driven Silver builder producing exactly the documented Silver schema from retained Bronze history for selected series.
- R2: For OHLC sources set `value=close` and preserve OHLC; for scalar sources preserve scalar `value` and output null Float64 OHLC columns; retain unit/provider/source identity from registry/source metadata.
- R3: Require unique `(series_id, observation_date)`, strict date ordering per series, finite non-null `value`, consistent provider/source identity, and never create/fill an absent source date.
- R4: Diff selected rebuilt Silver against current Silver and rewrite only affected monthly partitions; unchanged rebuild is a physical no-op and unselected series are untouched.
- R5: Add tests for one OHLC and one scalar source, exact dtypes/order, duplicate rejection, non-finite rejection, identity mismatch, preserved source gaps, revision, and no-op physical preservation.

Acceptance:
- A1 (verifies R1): Output column order/types equal the Silver contract exactly.
- A2 (verifies R2): OHLC/scalar fixtures produce exact stated mappings and nullable OHLC dtypes.
- A3 (verifies R3): Every duplicate/non-finite/identity-invalid fixture fails and an absent date remains absent.
- A4 (verifies R4): Revision rewrites only its affected month; identical rebuild changes no Silver file hash/mtime; unselected series stay untouched.
- A5 (verifies R5): All stated Silver cases pass offline.

## PR-14: Add Lake Inventory CLI

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-14/lake-inventory-cli`

Git status: `not-started (branch absent)`

Agent lane: Agent B

Depends on: PR-11, PR-12

Commit: `feat(pr-14): add lake inventory cli`

Description:
- R1: Add a non-mutating `inventory` CLI that reads authoritative `dataset_inventory.parquet` and outputs stable fields `series_id`, provider, min date, max date, row count, duplicate count, and file count.
- R2: Add repeatable/non-mutating `--series` and `--provider` filters validated against the registry/provider set; unknown filters fail rather than silently returning unrelated rows.
- R3: Add deterministic `--json` output with exactly the same logical field names/values and stable ordering as text/tabular output.
- R4: Empty registered series/filtered results are valid successful output; config/unknown-filter/read/schema failures are non-zero and do not modify any lake file.
- R5: Add parser/output tests for unfiltered, series filter, provider filter, combined filter, JSON, empty registered series, unknown filter, and corrupt/missing inventory.

Acceptance:
- A1 (verifies R1): Fixed fixtures produce exactly the seven documented fields per row in stable order.
- A2 (verifies R2): Valid filters return only matching rows; unknown values fail non-zero; before/after lake hashes prove no mutation.
- A3 (verifies R3): JSON and text representations contain equivalent logical values/order.
- A4 (verifies R4): Empty valid selection exits zero; each stated read/config/schema failure exits non-zero without lake mutation.
- A5 (verifies R5): All listed CLI cases pass offline.

## PR-15: Build Volatility Gold Features On Canonical Timestamp

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-15/volatility-gold-features`

Git status: `not-started (branch absent)`

Agent lane: Agent A

Depends on: PR-13

Commit: `feat(pr-15): add volatility regime features`

Description:
- R1: Convert Silver `observation_date` to first-column `timestamp_m1` at exact `00:00:00.000000 UTC`, cast to Polars `Datetime(time_unit="us", time_zone="UTC")`, remove `observation_date`, and retain one row per union source date needed by this feature family.
- R2: For each `vix`, `vix9d`, `vix3m`, `vix6m`, `vix1y`, `vstoxx`, `move`, output exact columns `<series>_level`, `<series>_delta_5obs`, `<series>_delta_20obs`, `<series>_zscore_60obs` using the global Gold feature-math contract.
- R3: Output exact term columns `vix9d_vix_ratio`, `vix_vix3m_ratio`, `vix3m_minus_vix`, `vix6m_minus_vix`, `vix1y_minus_vix`; calculate only on same timestamp and return null on missing required input or zero denominator.
- R4: Do not fill source gaps. Observation-lag operations count previous valid observations for that series, z-score uses last 60 valid observations including current with `ddof=0`, and all outputs are null until their stated minimum history exists.
- R5: Define deterministic output column order: `timestamp_m1`, then series in registry order with their four columns, then the five term columns; all feature columns are `Float64` nullable.
- R6: Add hand-calculable tests for UTC timestamp conversion/type, exact names/order/dtypes, 5/20 observation-lag delta (including calendar gaps), 60-value z-score/ddof, zero variance, ratio denominator zero, missing same-day input, and no future leakage.

Acceptance:
- A1 (verifies R1): Fixed date maps exactly to UTC midnight, timestamps are unique/sorted `Datetime(us, UTC)`, and `observation_date` is absent.
- A2 (verifies R2): All seven series expose the exact four named features and hand-calculated deltas use observation lags rather than calendar-day subtraction.
- A3 (verifies R3): All five exact term columns match hand fixtures and required-missing/zero denominator returns null.
- A4 (verifies R4): Gap fixtures prove no fill; 59 valid values remain z-score-null; the 60th matches population-standard-deviation result; zero variance is null.
- A5 (verifies R5): Full column list/order/dtypes match one explicit expected schema.
- A6 (verifies R6): Every stated formula/timestamp/leakage case passes offline.

## PR-16: Build Macro, Credit, Rates, And Dollar Gold Features

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-16/macro-gold-features`

Git status: `not-started (branch absent)`

Agent lane: Agent B

Depends on: PR-13

Commit: `feat(pr-16): add macro regime features`

Description:
- R1: Convert Silver dates to canonical first-column `timestamp_m1: Datetime(us, UTC)` at UTC midnight, remove `observation_date`, and retain the union of source dates for this feature family without filling gaps.
- R2: Output exact CISS columns `ciss_level`, `ciss_delta_5obs`, `ciss_delta_20obs`, `ciss_zscore_60obs` and Euro HY columns `euro_hy_oas_level`, `euro_hy_oas_delta_5obs`, `euro_hy_oas_delta_20obs`, `euro_hy_oas_zscore_60obs` using the global feature-math contract.
- R3: Output `us_2y_level`, `us_2y_delta_20obs`, `us_10y_level`, `us_10y_delta_20obs`, and `us_10y_minus_us_2y`; yield spread exists only with same-timestamp values.
- R4: Output `estr_level`, `estr_delta_20obs`, `usd_broad_level`, `usd_broad_delta_20obs`; absent source dates remain null after family union and are never carried forward/backward.
- R5: Define deterministic output order exactly as R2 -> R3 -> R4 after `timestamp_m1`; all feature columns are nullable `Float64` and insufficient history/zero-variance z-score is null.
- R6: Add hand-calculable tests for exact timestamp/name/order/dtype, delta across calendar gaps, 60-observation z-scores with `ddof=0`, missing yield-pair date, no fill, zero variance, and no future leakage.

Acceptance:
- A1 (verifies R1): Output uses exact unique/sorted UTC `timestamp_m1` and contains no `observation_date` or synthetic gap row beyond union source dates.
- A2 (verifies R2): CISS/HY columns/formulas exactly match explicit fixtures including z-score minimum history.
- A3 (verifies R3): Yield levels/deltas/spread match hand values and missing same-day pair yields null spread.
- A4 (verifies R4): ESTR/USD fixtures match exact values and missing dates are not filled.
- A5 (verifies R5): Complete expected schema/order/dtypes match exactly and zero variance is null.
- A6 (verifies R6): All stated macro/timestamp/leakage cases pass offline.

## PR-17: Assemble Canonical Daily Gold Frame And Validate Contract

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-17/canonical-daily-gold-frame`

Git status: `not-started (branch absent)`

Agent lane: Integration; one agent only

Depends on: PR-15, PR-16

Commit: `feat(pr-17): assemble canonical daily gold frame`

Description:
- R1: Outer-join the volatility and macro family frames only on `timestamp_m1`, yielding exactly one row per union timestamp and preserving missing-family values as null with no imputation/as-of carry.
- R2: Define one exact source-controlled ordered schema: canonical timestamp first, then every PR-15 feature in its exact order, then every PR-16 feature in its exact order; reject missing, extra, renamed, reordered, or wrong-dtype columns and forbid `observation_date`.
- R3: Validate non-empty frame, exact `Datetime(us, UTC)`, UTC-midnight values, unique strictly increasing timestamps, nullable finite Float64 values, and reject positive/negative infinity while allowing null/NaN only according to one explicit policy: normalize feature NaN to null before final validation.
- R4: Add a causality regression harness that truncates Silver input at cutoff `t`, rebuilds Gold, and asserts all Gold rows/features `<= t` equal the corresponding prefix of a full-history build; use this to detect future leakage in combined features.
- R5: Keep assembly storage-neutral: no build-ID generation, filesystem writes, hashing, JSON, plots, catalog mutation, publication, or retention imports/side effects.
- R6: Add tests for family outer join, exact full schema, missing/extra/reordered column rejection, duplicate/unsorted timestamp rejection, UTC-midnight validation, NaN normalization/infinity rejection, truncation causality, and storage-neutral boundary.

Acceptance:
- A1 (verifies R1): Fixtures yield exactly the union timestamps with correct null preservation and no carried values.
- A2 (verifies R2): One explicit expected column/dtype list passes and every listed schema drift fails deterministically.
- A3 (verifies R3): Every timestamp/value-invalid fixture fails except allowed null/NaN-to-null behavior; final frame contains no NaN or infinity.
- A4 (verifies R4): Multiple fixed cutoff fixtures produce byte/logically identical Gold prefixes and a deliberately leaky test transform is detected by the harness.
- A5 (verifies R5): Import/static test proves assembly has no physical publication dependencies or side effects.
- A6 (verifies R6): All stated assembly/contract/causality cases pass offline.

## PR-18: Add Immutable Versioned Gold Parquet Storage

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-18/immutable-gold-storage`

Git status: `not-started (branch absent)`

Agent lane: Agent A

Depends on: PR-17

Commit: `feat(pr-18): add immutable gold build storage`

Description:
- R1: Define build IDs from an injected UTC build time in exact second-resolution `YYYYMMDDTHHMMSSZ`; reject non-UTC input, malformed IDs, and reuse of an existing build directory.
- R2: Create a new build directory on the destination filesystem, write `data.parquet` to a same-directory temp, validate readback schema/row count/timestamp bounds, fsync where supported, then atomically rename to final `data.parquet`; never overwrite or merge an existing final artifact.
- R3: Compute and return deterministic SHA-256 of the final Parquet bytes plus `row_count`, `min_timestamp`, `max_timestamp`; these values are inputs to later sidecar/catalog publication.
- R4: Provide explicit-build reader by exact build ID/path only; never perform implicit `latest`, mtime, glob-max, or lexicographic selection.
- R5: Treat a partially created directory without valid final Parquet as an incomplete attempted build that explicit reader rejects; do not auto-promote/overwrite it.
- R6: Add tests for exact ID, UTC validation, same-second collision, exact path, schema/timestamp preservation, hash repeatability for the written bytes, injected write/readback failure, overwrite rejection, partial directory rejection, and coexistence/readback of two builds.

Acceptance:
- A1 (verifies R1): Fixed UTC time yields exact expected ID; malformed/non-UTC/reused IDs fail before changing an existing build.
- A2 (verifies R2): Success leaves one valid final Parquet/no temp; every injected pre-final failure leaves no authoritative final artifact and cannot alter an existing build.
- A3 (verifies R3): Metadata equals independent read/hash calculation on final artifact.
- A4 (verifies R4): Reading build A always returns A regardless of newer build B/mtime/order.
- A5 (verifies R5): Partial build directory is never selected/read as complete and a new run cannot silently overwrite it.
- A6 (verifies R6): All stated storage/identity/failure cases pass offline.

## PR-19: Add Gold Parquet Catalog And Consumer Resolution

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-19/gold-catalog-resolution`

Git status: `not-started (branch absent)`

Agent lane: Agent B

Depends on: PR-17

Commit: `feat(pr-19): add gold catalog and resolution`

Description:
- R1: Define root `manifest.parquet` with exact ordered typed fields: `dataset_id`, `build_id`, `status`, `current`, `started_at_utc`, `completed_at_utc`, `schema_version`, `feature_version`, `min_timestamp`, `max_timestamp`, `row_count`, `data_path`, `build_manifest_path`, `plot_path`.
- R2: Define `schema_version=1` and `feature_version=1` as source-controlled constants; catalog code receives them explicitly and never auto-increments them.
- R3: Persist the catalog with deterministic row ordering `(started_at_utc, build_id)` and same-directory atomic replacement; `build_id` is unique, allowed status is only `building|complete|failed`, and before first publication zero current rows is valid.
- R4: Validate state invariants: only complete may be current; after a successful publication exactly one current; selectable complete requires non-null existing three artifact paths whose build IDs agree; `completed_at_utc`, row/timestamp metadata are required for complete; building/failed are never selectable.
- R5: Implement pure consumer resolution from catalog: supported compatible current first; else newest compatible selectable complete by `(completed_at_utc DESC, build_id DESC)`; compatibility is exact membership in caller-supported schema/feature version sets.
- R6: Add tests for exact schema/order/types, semantic-version constants, duplicate/status/current/path mismatch, missing physical artifact, deterministic ordering, current-compatible selection, incompatible-current fallback, and no filesystem-recency selection.

Acceptance:
- A1 (verifies R1): One explicit schema fixture matches exactly and old `min_date|max_date` fields are absent.
- A2 (verifies R2): Version constants equal `1/1`; runtime inputs cannot trigger implicit bump.
- A3 (verifies R3): Atomic round-trip preserves deterministic ordering and invalid duplicate/status conditions fail.
- A4 (verifies R4): Every stated invalid state/path/build-ID/metadata combination is rejected; zero-current pre-publication passes.
- A5 (verifies R5): Fixtures prove exact current preference/fallback ordering/version filtering and never inspect mtime/glob order.
- A6 (verifies R6): All catalog/resolution cases pass offline.

## PR-20: Generate Immutable Gold Build JSON And Feature Profile

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-20/gold-build-sidecars`

Git status: `not-started (branch absent)`

Agent lane: Agent A

Depends on: PR-18

Commit: `feat(pr-20): add gold build sidecars`

Description:
- R1: Generate immutable UTF-8 `versions/build_id=<id>/manifest.json` with exact required keys `dataset_id`, `build_id`, `schema_version`, `feature_version`, `status`, `started_at_utc`, `completed_at_utc`, `rows_out`, ordered `columns`, `min_timestamp`, `max_timestamp`, `data_path`, `data_sha256`, `feature_set_hash`, `git_commit_hash`, and `plot_path`; serialize with stable sorted keys/separators and ISO UTC values.
- R2: Compute `feature_set_hash` deterministically from exact Gold ordered column names+dtypes+formula/version contract and capture `git_commit_hash` from an injected/source-control service; do not use wall-clock/random identity in these hashes.
- R3: Generate immutable `feature_profile.png` from exactly the published Gold frame using a deterministic plotting service analogous to `crypto-history-loader`; exclude `timestamp_m1`, plot only numeric features in canonical column order, and include no random sampling/current-time text.
- R4: Existing build `manifest.json` or `feature_profile.png` is creation-only and never overwritten; successful build bundle requires valid Parquet, JSON, and non-empty valid PNG all sharing the same build identity/metadata.
- R5: Plot/JSON failure leaves that build incomplete and propagates to caller; do not mutate root sidecars/catalog in this PR.
- R6: Add tests for exact JSON schema/serialization, source/build/hash metadata, deterministic feature-set hash, injected git hash, exact paths, PNG validity/order/exclusions, creation-only behavior, identity mismatch, and sidecar failure propagation.

Acceptance:
- A1 (verifies R1): Fixed build emits exact required key set/values with deterministic bytes and matching Parquet metadata/hash.
- A2 (verifies R2): Same contract yields same feature hash; one formula/schema/version change yields different hash; injected git commit is preserved exactly.
- A3 (verifies R3): PNG is non-empty/valid and plot input order is canonical numeric features with no timestamp/random/time-dependent content.
- A4 (verifies R4): Valid bundle identities agree; second write to either final sidecar fails without changing existing bytes.
- A5 (verifies R5): Injected JSON/plot failures leave root publication untouched and caller receives failure.
- A6 (verifies R6): All stated sidecar/reproducibility/immutability cases pass offline.

## PR-21: Publish Gold Bundle And Root Sidecars Transactionally

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-21/transactional-gold-publication`

Git status: `not-started (branch absent)`

Agent lane: Integration; one agent only

Depends on: PR-19, PR-20

Commit: `feat(pr-21): publish gold bundle transactionally`

Description:
- R1: Implement publication state machine `new attempt -> catalog building,current=false -> immutable Parquet -> immutable JSON -> immutable PNG -> validate bundle -> complete/current commit`; prior current remains authoritative until final commit.
- R2: Validate candidate bundle before promotion: exact schema/version/build identity, Parquet SHA/row/timestamp bounds, build JSON identity/hash/path fields, valid plot, and all artifact paths inside the expected build directory.
- R3: Build next root catalog and deterministic root `manifest.json` mirror in staging; copy/stage candidate `feature_profile.png`; replace root JSON/PNG with rollback backups, then replace authoritative root `manifest.parquet` last as the commit point.
- R4: On any pre-commit failure, restore prior root JSON/PNG/catalog and prior current selection; mark attempt `failed,current=false` in a later safe catalog write only if doing so preserves prior current. No failed/incomplete bundle is selectable.
- R5: After successful commit, verify root JSON `current_build_id` and build records mirror catalog and root PNG bytes equal the selected current build PNG; if post-commit verification fails, return a hard operational error without pretending the catalog commit did not happen.
- R6: Add explicit restart recovery for catalog rows left `building`: if no authoritative commit selected that build, recovery marks it failed after validating it is non-current; never infer completion from version-directory/file existence.
- R7: Add failure-injection tests after each build artifact, each root staging/replacement point, before catalog replace, and post-commit verification; add successful publication, first publication, prior-current preservation, and interrupted-building recovery tests.

Acceptance:
- A1 (verifies R1): State-transition fixtures prove only fully validated bundle reaches complete/current and old current persists until commit point.
- A2 (verifies R2): Every metadata/hash/path mismatch prevents promotion.
- A3 (verifies R3): Success has exactly one current, deterministic matching root JSON/PNG, and event trace proves Parquet catalog replacement is last authority switch.
- A4 (verifies R4): Every injected pre-commit failure leaves old authoritative root state/current intact and failed attempt unselectable.
- A5 (verifies R5): Success consistency check passes; injected post-commit mismatch reports hard error while catalog truth remains the committed source of authority.
- A6 (verifies R6): Restart fixture converts stale non-current building -> failed and never promotes based on files/mtime.
- A7 (verifies R7): All stated failure/restart/success scenarios pass offline.

## PR-22: Add Gold Build-Bundle Retention

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-22/gold-build-retention`

Git status: `not-started (branch absent)`

Agent lane: Foundation; first free agent

Depends on: PR-21

Commit: `feat(pr-22): retain recent gold build bundles`

Description:
- R1: Add `gold_retention_successful_builds` with default `5`, meaning five physically retained complete build directories including current for each `(schema_version, feature_version)` pair.
- R2: Retention runs only after successful publication/recovery has no active ambiguity; sort eligible non-current complete builds by `(completed_at_utc ASC, build_id ASC)` and prune oldest beyond limit.
- R3: Treat build directory as one bundle: delete `data.parquet`, `manifest.json`, `feature_profile.png`, then remove empty build directory; never prune current, building, failed, another semantic version pair, or a bundle whose identity/path validation fails.
- R4: After successful physical prune, atomically update audit catalog row by setting `data_path`, `build_manifest_path`, `plot_path` to null while retaining immutable audit metadata/hash/version/timestamps; it becomes unselectable.
- R5: If deletion is partial/fails, do not null catalog paths or pretend success; surface an operational error and require consistency recovery. Consumer resolver must reject a selectable row whose required bundle is partial/missing.
- R6: Add tests for defaults/custom limit, current protection, version isolation, exact ordering, full deletion, injected partial-delete failure, retained audit row, and resolver rejection of partial selectable bundle.

Acceptance:
- A1 (verifies R1): Default never retains more than five complete physical bundles per semantic pair including current after successful retention.
- A2 (verifies R2): Six eligible fixed builds prune exactly oldest allowed bundle and ordering tie breaks by build ID.
- A3 (verifies R3): Protected/invalid identities remain untouched; valid prune removes all three files and directory.
- A4 (verifies R4): Successful pruned row remains audit-visible with all three paths null and cannot resolve.
- A5 (verifies R5): Injected partial deletion preserves non-null catalog paths, returns error, and partial selectable bundle fails consistency/resolution instead of being silently selected.
- A6 (verifies R6): All stated retention/failure/selection cases pass offline.

## PR-23: Add Daily Medallion Pipeline And CLI

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-23/daily-medallion-pipeline`

Git status: `not-started (branch absent)`

Agent lane: Integration; one agent only

Depends on: PR-14, PR-21, PR-22

Commit: `feat(pr-23): add daily medallion pipeline`

Description:
- R1: Add CLI commands `bootstrap`, `update`, `silver-build`, `gold-build`, `inventory`, and `run-daily`; all command parsing/config validation is in `api/`, use cases in `application/`, and `gold-build` publishes only through the PR-21 service.
- R2: `run-daily` order is selected Bronze update -> selected/all Silver rebuild -> full canonical Gold assembly from current Silver -> immutable Parquet -> build JSON -> build PNG -> candidate validation -> root staging -> authoritative catalog publication -> retention -> inventory refresh.
- R3: Default source processing targets exactly all 13 registry series; repeatable `--series` may restrict Bronze/Silver source execution, but Gold always rebuilds the full canonical schema from all currently available Silver inputs rather than dropping unselected feature columns.
- R4: Failure semantics: a requested Bronze series failure makes command non-zero but already completed independent Bronze series remain durable; any Silver/Gold failure before publication leaves prior current Gold/root sidecars authoritative; no partial new Gold becomes selectable.
- R5: Add end-to-end offline fixture covering empty-lake bootstrap, next-day incremental run with one revision and one shortened full-file response, Silver affected-month updates, UTC-midnight Gold, all build/root artifacts, manifest resolution, retention, repeated no-op source rerun, and inventory refresh.
- R6: On startup/run-daily invoke interrupted-`building` recovery before creating a new build; recovery errors stop Gold publication rather than bypassing catalog ambiguity.
- R7: Document once-daily cron and systemd examples, required persistent lake path, environment/secret injection, and exit-code/log expectations; explicitly do not add scheduled GitHub Actions ingestion because CI runners do not own the persistent runtime lake.
- R8: Add CLI/integration tests for default/all selection, repeat filters, unknown series, stage ordering, failure propagation, first run, second run, no-op run, recovery, and `network` marker exclusion.

Acceptance:
- A1 (verifies R1): All commands parse, respect layer boundaries, and Gold outputs only through publication service with exact timestamp/schema contract.
- A2 (verifies R2): Integration tracing proves the stated stage order and successful output contains all immutable build artifacts plus all three root Gold sidecars.
- A3 (verifies R3): Defaults target exactly 13 series and repeatable filters restrict only requested source execution without altering full Gold column contract.
- A4 (verifies R4): Injected provider/Silver/Gold failures return non-zero with exact documented durable-state behavior and no partial Gold selection.
- A5 (verifies R5): The complete bootstrap/delta/revision/truncation/timestamp/publication/resolution/idempotency/retention/inventory scenario passes offline.
- A6 (verifies R6): Interrupted-building recovery is deterministic and never promotes by filesystem recency/presence.
- A7 (verifies R7): README documents both scheduler examples/runtime requirements and no scheduled GitHub Actions data-ingestion workflow exists.
- A8 (verifies R8): Required integration gate remains network-free and marker tests prove `network` tests are excluded.

## Definition Of MVP Complete

The MVP is complete only when PR-01 through PR-23 are merged and all of the following are true:

- every implementation branch/commit follows the `pr-XX` Git naming contract and backlog Git metadata is current;
- local pre-push and remote push/PR/merge quality gates run `lint`, `type`, `unit`, and offline `integration` in parallel, require the `coverage` aggregation check, enforce combined production-code line coverage `>=90.0%`, and `main` cannot merge with any required check failing;
- an empty lake can bootstrap every available initial source series to the maximum history exposed by its configured open/public provider;
- subsequent source runs fetch/refetch only the planner-approved delta/correction scope and remain duplicate-safe, restart-safe, and no-op safe;
- upstream source-window truncation never deletes older locally retained Bronze history;
- Bronze, Silver, Gold, state, operational manifests, and Gold catalogs use the documented Polars/Parquet contracts;
- Silver remains daily long-form with `observation_date: Date`;
- Gold uses only canonical `timestamp_m1: Datetime(time_unit="us", time_zone="UTC")` as temporal key and does not misrepresent UTC midnight as information availability time;
- every Gold feature formula, observation-lag rule, rolling-window rule, same-timestamp join rule, schema version, and feature version is explicit and tested;
- Gold contains reusable causal market-state features only and no HMM states, regime labels, targets, portfolio weights, or trading decisions;
- each successful Gold build is an immutable `data.parquet + manifest.json + feature_profile.png` bundle with reproducibility metadata/hashes;
- root `manifest.parquet`, `manifest.json`, and `feature_profile.png` remain consistent, with `manifest.parquet` the sole authoritative current-selection catalog;
- interrupted `building` attempts are restart-safe and are never auto-promoted by filesystem discovery;
- consumers can select current/compatible builds without filesystem recency logic;
- retention keeps the configured complete build bundles per semantic version pair without deleting current or silently accepting partial selectable bundles;
- `run-daily` can be scheduled once per day, preserves separately durable Bronze successes, and never publishes partial Gold state;
- required integration tests are offline; live-provider checks, if later added, are marked `network` and excluded from push/merge requirements;
- `README.md`, `ARCHITECTURE.md`, and this backlog remain synchronized with the implementation they describe.
