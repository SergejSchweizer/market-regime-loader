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
- Before `Ready`, the branch is pushed and the remote four-job quality gate is green; set `Git status: pushed-ci-green`.
- After merge, set `Status: Merged`, fill `PR`, and set `Git status: merged`.
- Do not force-push shared branches, reuse a branch for another PR, or resolve semantic conflicts by guessing.

Current planning state: no planned `pr-XX/...` implementation branches exist, therefore every PR below starts with `Git status: not-started (branch absent)`.

## Push And Merge Quality Gates

Quality gates are part of the repository contract.

### Local pre-push gate

The repository-managed pre-push hook runs these four classes **in parallel**:

```text
lint
type
unit
integration
```

Any failure blocks `git push`. `integration` is offline and excludes `network` tests.

### Remote push gate

GitHub Actions runs the same four independent jobs on every `push`.

### Pull-request / merge gate

The same four jobs run for `pull_request` targeting `main` and for `merge_group`. `main` must be protected so all four exact checks are required and direct pushes to `main` are forbidden. The jobs must not depend on each other; they run in parallel. A later aggregate/reporting job may depend on them but is not a substitute for the four required checks.

## Parallel-Agent Rules

- **Agent A:** registry/path contracts, CBOE/STOXX/Yahoo, Silver, volatility Gold, immutable Gold storage, build sidecars.
- **Agent B:** Parquet IO, shared HTTP client, ECB/FRED, operational manifests/inventory, macro Gold, Gold catalog.
- **Integration/Foundation:** first free agent only after listed dependencies merge.
- Provider PRs are independent once their common foundations are merged; the backlog does not encode fake serial dependencies merely because one agent may execute them sequentially.
- If two PRs touch the same file, the later branch rebases on dependency-complete `main` before implementation.

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
| `ciss` | ECB Data Portal | `CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX` | `scalar` | `date_range` | complete exposed history |
| `estr` | ECB Data Portal | `EST.B.EU000A2X2A25.WT` | `scalar` | `date_range` | complete exposed history |
| `euro_hy_oas` | FRED | `BAMLHE00EHYIOAS` | `scalar` | `date_range` | all currently exposed observations; never truncate older local history |
| `us_2y` | FRED | `DGS2` | `scalar` | `date_range` | complete exposed history |
| `us_10y` | FRED | `DGS10` | `scalar` | `date_range` | complete exposed history |
| `usd_broad` | FRED | `DTWEXBGS` | `scalar` | `date_range` | complete exposed history |

No additional series belongs in the MVP without a separate backlog PR. The registry is authoritative; provider modules do not invent symbols or implicit fallbacks.

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
- R1: Create the Python >=3.13 `uv` project with runtime dependencies `polars`, `pyarrow`, `httpx`, `pydantic`, `PyYAML`, `matplotlib` and dev dependencies `pytest`, `pytest-cov`, `ruff`, `mypy`; create package/test roots and pytest markers `integration` and `network`.
- R2: Add Make targets `lint`, `type`, `unit`, `integration`, `quality-gate`; `quality-gate` runs the four classes in parallel and required test targets exclude `network`.
- R3: Add an installable repository pre-push hook that requires a clean `git status --short`, runs those four classes in parallel, and blocks push on any failure.
- R4: Add `.github/workflows/quality-gates.yml` for `push`, `pull_request` to `main`, and `merge_group`, with four independent jobs named exactly `lint`, `type`, `unit`, `integration`.
- R5: Add commit validation for `<type>(pr-XX): <description>` and branch/commit PR-ID matching; generated merge-group commits are excluded from this subject check.
- R6: Add documented/scripted `main` protection requiring the four checks, pull requests, and no direct pushes; add `.gitignore` for runtime/caches and keep README/ARCHITECTURE synchronized.

Acceptance:
- A1 (verifies R1): `uv sync --extra dev` resolves, all roots/markers exist, and production deps contain no pandas.
- A2 (verifies R2): all five targets run their exact class; injected failure makes `quality-gate` fail while all four children are started.
- A3 (verifies R3): hook install is idempotent; dirty worktree or fake gate failure blocks push and clean fake success permits it.
- A4 (verifies R4): workflow tests prove all three triggers and that the four jobs have no inter-job `needs` dependencies.
- A5 (verifies R5): valid matching examples pass; missing/wrong PR scope, bad type, and malformed subject fail.
- A6 (verifies R6): protection setup names the four exact checks and disallows direct `main` pushes; ignored artifacts are not tracked and docs do not contradict the contract.

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
- R1: Add one immutable registry with exactly the 13 series and required provider/source/unit/native-shape/frequency/bootstrap/capability metadata.
- R2: Restrict capabilities to `date_range|full_file` and native shapes to `ohlc|scalar`; make `vstoxx` unambiguously scalar/full-file.
- R3: Add typed helpers for every Bronze/Silver/Gold/build/root/state/manifest path documented above.
- R4: Validate duplicate IDs, unknown providers, empty source IDs, invalid units/frequencies/shapes/capabilities and add exact fixed-path tests for `2026-08-18` / `20260818T020000Z`.

Acceptance:
- A1 (verifies R1): registry contains exactly 13 populated entries.
- A2 (verifies R2): only declared enum values pass and VSTOXX is scalar/full-file.
- A3 (verifies R3): helpers return every exact documented path without provider-local hard-coded duplicates.
- A4 (verifies R4): every invalid condition fails before adapter execution and fixed-path tests pass.

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
- R1: Implement deterministic Polars-only zero/one/multi-partition reads and atomic sibling-temp-file Parquet replacement.
- R2: Implement natural-key merge/upsert with deterministic new-row precedence, duplicate removal, stable ordering, and inserted/revised/unchanged diff counts.
- R3: Rewrite only partitions containing inserted/revised rows; logical no-op and unrelated months are not rewritten.
- R4: Add tests for reads, atomic failure recovery, revisions, duplicate removal, ordering, no-op and unaffected-month preservation.

Acceptance:
- A1 (verifies R1): reads are deterministic, no pandas exists, failed write preserves previous bytes.
- A2 (verifies R2): one logical row per key and exact diff counts are produced.
- A3 (verifies R3): hashes/mtimes prove no-op and unrelated months remain untouched.
- A4 (verifies R4): all stated IO cases pass offline.

## PR-04: Add Shared HTTP Client And Provider Adapter Port

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-04/shared-http-provider-port`

Git status: `not-started (branch absent)`

Agent lane: Agent B

Depends on: PR-01

Commit: `feat(pr-04): add shared provider http client`

Description:
- R1: Define a provider port accepting a canonical series definition and fetch plan and returning Bronze candidate rows without lake writes.
- R2: Implement shared `httpx` timeouts, deterministic user-agent, injectable transport, and no provider-specific parsing.
- R3: Retry only transient network errors, HTTP 429 and 5xx with capped exponential backoff/injectable sleeper; do not retry other 4xx.
- R4: Return typed provider errors with provider/series/request/retry context while redacting credentials; test success, timeout, retry success/exhaustion, 429, permanent 4xx and redaction offline.

Acceptance:
- A1 (verifies R1): fake adapters satisfy the port without importing lake IO.
- A2 (verifies R2): timeout/user-agent/transport settings are asserted.
- A3 (verifies R3): exact retry/no-retry behavior and backoff are deterministic without sleeping.
- A4 (verifies R4): all scenarios pass and test secrets never appear in logs/errors.

## PR-05: Implement Bootstrap/Incremental Planner And Ingestion State

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-05/incremental-planner-ingestion-state`

Git status: `not-started (branch absent)`

Agent lane: Foundation; first free agent

Depends on: PR-02, PR-03

Commit: `feat(pr-05): add incremental planner and ingestion state`

Description:
- R1: Produce deterministic bootstrap/incremental plans; incremental uses `latest - overlap_days` (default 7) through injected today and rejects invalid ranges/negative overlap.
- R2: Map `date_range` to exact bounded requests and `full_file` to full fetch plus the same logical target range for diffing.
- R3: Define atomic `ingestion_state.parquet` keyed by `(provider, series_id)` with last success, latest observation, requested bounds, mode and row/partition counters.
- R4: Advance state only after explicit durable success; use injected clocks and test bootstrap, incremental, capabilities, state round-trip and failure preservation.

Acceptance:
- A1 (verifies R1): fixed fixtures produce exact plans and invalid ranges fail.
- A2 (verifies R2): capability fixtures produce exact distinct fetch instructions.
- A3 (verifies R3): state round-trips to one row per key with all fields.
- A4 (verifies R4): failure preserves prior state, success advances it, and tests have no wall-clock dependency.

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
- R1: Implement one CBOE adapter for exactly `vix`, `vix9d`, `vix3m`, `vix6m`, `vix1y` through shared ports as registered full-file sources.
- R2: Parse exact Bronze metadata + OHLC with Polars; reject invalid dates/non-finite OHLC/missing valid close.
- R3: Collapse identical same-date duplicates, fail conflicting duplicates, preserve ability to retain old local rows when a later response is shorter, and never silently fallback provider.
- R4: Add fixtures for valid history, identical/conflicting duplicate, revision, shorter response, malformed row and unavailable series.

Acceptance:
- A1 (verifies R1): exactly five series route through CBOE.
- A2 (verifies R2): normalized contract/types are exact and bad rows fail with context.
- A3 (verifies R3): duplicate/truncation/fallback behavior is deterministic.
- A4 (verifies R4): all CBOE cases pass offline.

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
- R1: Implement STOXX only for canonical `vstoxx` / registered `V2TX` through shared ports as a `full_file` source.
- R2: Normalize the selected daily observation to scalar Bronze `value: Float64`; provider-specific extras do not leak into canonical Bronze.
- R3: Reject invalid/non-finite/conflicting duplicates and never infer deletion from a shorter upstream full-file response.
- R4: Add representative bootstrap/scalar/duplicate/revision/truncation fixtures.

Acceptance:
- A1 (verifies R1): only VSTOXX is accepted with stable source ID and full-file capability.
- A2 (verifies R2): output is unambiguously scalar Bronze.
- A3 (verifies R3): invalid/truncation behavior is deterministic.
- A4 (verifies R4): all VSTOXX cases pass offline.

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
- R1: Implement Yahoo only for `move` / `^MOVE` through the shared HTTP/provider ports; do not add another Yahoo client library without ADR.
- R2: Bootstrap max history and use exact planner bounds incrementally; normalize only Bronze metadata + OHLC.
- R3: Reject invalid/non-finite close and conflicting duplicate dates; empty response is zero rows, never fabricated data.
- R4: Test max/bounded args, empty, revision, duplicate conflict, malformed value and normalization.

Acceptance:
- A1 (verifies R1): unrelated series/tickers are rejected and shared HTTP is used.
- A2 (verifies R2): request args and Bronze schema are exact.
- A3 (verifies R3): empty/malformed/duplicate cases match contract.
- A4 (verifies R4): all MOVE cases pass offline.

## PR-09: Add ECB CISS And ESTR Provider

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-09/ecb-ciss-estr-provider`

Git status: `not-started (branch absent)`

Agent lane: Agent B

Depends on: PR-02, PR-04, PR-05

Commit: `feat(pr-09): ingest ecb ciss and estr`

Description:
- R1: Implement exactly `ciss` and `estr` using registered keys through shared ports with full bootstrap and exact bounded incremental periods.
- R2: Parse scalar Float64 Bronze rows; missing/non-numeric observations are absent, never zero.
- R3: Collapse identical duplicates, reject conflicting duplicates, preserve normal weekend/holiday gaps and allow revisions.
- R4: Add fixtures for both series, request modes, revision, duplicate cases, gap and missing values.

Acceptance:
- A1 (verifies R1): exactly two ECB series are accepted and requests are exact.
- A2 (verifies R2): valid values are Float64 and missing values fabricate nothing.
- A3 (verifies R3): duplicate/revision/calendar behavior is deterministic.
- A4 (verifies R4): all ECB cases pass offline.

## PR-10: Add FRED Rates, Credit, And Dollar Provider

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-10/fred-rates-credit-dollar-provider`

Git status: `not-started (branch absent)`

Agent lane: Agent B

Depends on: PR-02, PR-04, PR-05

Commit: `feat(pr-10): ingest fred rates credit and dollar`

Description:
- R1: Map exactly `DGS2`, `DGS10`, `DTWEXBGS`, `BAMLHE00EHYIOAS` to the four registered canonical series through shared ports; runtime credentials, if any, are never committed/logged.
- R2: Bootstrap exposed history and use exact planner bounds; parse `.`/blank/non-finite as no observation and never fill.
- R3: Collapse identical duplicates, reject conflicting duplicates, and ensure a shorter later Euro-HY response cannot imply deletion of older local history while overlap revisions remain valid.
- R4: Test all series, request modes, missing values, duplicates, revision, shortened HY history and redaction.

Acceptance:
- A1 (verifies R1): only four mappings exist and secrets are external/redacted.
- A2 (verifies R2): requests/parsing match contract without fabricated values.
- A3 (verifies R3): duplicate/truncation/revision behavior is deterministic.
- A4 (verifies R4): all FRED cases pass offline.

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
- R1: Inventory has one row per registered series with provider, min/max observation date, row count, duplicate-key count and physical Bronze file count.
- R2: Ingestion-run rows contain injected run ID, provider/series, mode, requested bounds, fetched/changed rows, written partitions, status, bounded/redacted error, started/completed UTC.
- R3: Persist inventory keyed by `series_id` and runs keyed by `run_id` atomically; do not invent weekend/holiday missing or completeness metrics.
- R4: Test empty/populated inventory, duplicates, success/failure runs, repeated refresh and secret-redacted errors.

Acceptance:
- A1 (verifies R1): exactly one six-field coverage row exists per registered series.
- A2 (verifies R2): every stated audit field is present with deterministic injected IDs/times.
- A3 (verifies R3): natural keys round-trip without duplicates and no synthetic calendar metric exists.
- A4 (verifies R4): all manifest/inventory cases pass offline and secrets are absent.

## PR-12: Add Registry-Driven Bronze Orchestration

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-12/bronze-orchestration`

Git status: `not-started (branch absent)`

Agent lane: Integration; one agent only

Depends on: PR-03, PR-05, PR-06, PR-07, PR-08, PR-09, PR-10, PR-11

Commit: `feat(pr-12): orchestrate bronze ingestion`

Description:
- R1: Resolve selected series -> registry -> state -> plan -> exact registered adapter -> shared lake writer with deterministic bootstrap/update modes and run IDs.
- R2: For full-file sources diff against retained Bronze and write inserted/revised rows only; never delete historical rows merely absent upstream.
- R3: Isolate series failures; advance state only after Bronze + success-run durability; return stable per-series status/fetched/changed/partitions/min/max/error summaries.
- R4: Add fake-adapter integration tests for routing, bootstrap, update, truncation, partial failure, restart and idempotent rerun.

Acceptance:
- A1 (verifies R1): fake adapters prove exact routing/planner/writer use.
- A2 (verifies R2): shorter file preserves history and overlap revision updates exactly once.
- A3 (verifies R3): one failed series coexists with durable success and state advances only after success durability.
- A4 (verifies R4): all orchestration scenarios pass offline without duplicates.

## PR-13: Build Canonical Silver Daily Series

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-13/canonical-silver-series`

Git status: `not-started (branch absent)`

Agent lane: Agent A

Depends on: PR-12

Commit: `feat(pr-13): build canonical silver series`

Description:
- R1: Build exact Silver schema for selected series; OHLC maps `value=close`, scalar maps `value` with null OHLC.
- R2: Deduplicate `(series_id, observation_date)`, sort, reject non-finite canonical values, never fill missing dates.
- R3: Write deterministic monthly partitions through shared IO and do not replace logically unchanged months; return stable build summaries.
- R4: Test OHLC/scalar, duplicates, non-finite, gaps, no-op rebuild and one revised month.

Acceptance:
- A1 (verifies R1): columns/types/mappings exactly match Silver contract.
- A2 (verifies R2): keys/gaps/non-finite behavior is exact.
- A3 (verifies R3): no-op rewrites nothing and one revision rewrites only its month.
- A4 (verifies R4): all Silver cases pass offline.

## PR-14: Add Lake Inventory CLI

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-14/lake-inventory-cli`

Git status: `not-started (branch absent)`

Agent lane: Agent B

Depends on: PR-11

Commit: `feat(pr-14): add lake inventory cli`

Description:
- R1: Add read-only `inventory` text output with provider, min/max date, row count, duplicate count and file count for each series.
- R2: Add repeatable `--series` / `--provider` filters with deterministic intersection semantics and `--json` equivalent output.
- R3: Empty/unpopulated series is valid; only argument/config/read/contract errors fail and no command mutates lake files.
- R4: Test unfiltered, repeated filters, JSON equivalence, empty series and read failure.

Acceptance:
- A1 (verifies R1): fixed fixtures produce exactly six coverage fields in stable order.
- A2 (verifies R2): filters and JSON are deterministic/equivalent.
- A3 (verifies R3): valid empties succeed, injected errors fail, files remain unchanged.
- A4 (verifies R4): all CLI cases pass offline.

## PR-15: Build Volatility Gold Features On Canonical Timestamp

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-15/volatility-gold-features`

Git status: `not-started (branch absent)`

Agent lane: Agent A

Depends on: PR-13

Commit: `feat(pr-15): add volatility gold features`

Description:
- R1: Convert Silver dates to UTC-midnight `timestamp_m1: Datetime(us, UTC)`, remove `observation_date`, preserve unique sorted timestamps.
- R2: For each `vix`, `vix9d`, `vix3m`, `vix6m`, `vix1y`, `vstoxx`, `move`, create `{series}_level`, `_delta_5obs`, `_delta_20obs`, `_zscore_60obs` exactly per global math contract.
- R3: Create `vix9d_vix_ratio`, `vix_vix3m_ratio`, `vix3m_minus_vix`, `vix6m_minus_vix`, `vix1y_minus_vix` only on same timestamps; null ratios for null/nonpositive denominator; no fill/as-of/future use.
- R4: Add hand-calculable tests for timestamp, formulas, observation-lag vs calendar gap, 60-observation/ddof=0/zero-variance, denominator and leakage cases.

Acceptance:
- A1 (verifies R1): exact timestamp dtype/name/order and no `observation_date`.
- A2 (verifies R2): all seven series expose exact names/formulas and observation lags.
- A3 (verifies R3): all cross-series features and null/no-fill rules are exact.
- A4 (verifies R4): all volatility tests pass offline.

## PR-16: Build Macro, Credit, Rates, And Dollar Gold Features

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-16/macro-gold-features`

Git status: `not-started (branch absent)`

Agent lane: Agent B

Depends on: PR-13

Commit: `feat(pr-16): add macro gold features`

Description:
- R1: Convert Silver dates to exact UTC-midnight `timestamp_m1` and remove `observation_date`.
- R2: Build CISS and Euro-HY levels + 5/20-observation absolute source-unit deltas; US2Y/US10Y levels + 20-observation deltas + same-timestamp `us_10y_minus_us_2y`.
- R3: Build €STR level/20-observation delta and USD-broad level/20-observation absolute source-unit delta; no percentage semantics unless a later feature PR adds them; no fill/as-of/future use.
- R4: Add hand-calculable tests for exact names/formulas, observation lags, missing yield pairs, gaps and leakage.

Acceptance:
- A1 (verifies R1): canonical timestamp contract holds and no date column remains.
- A2 (verifies R2): CISS/HY/yield values, deltas and spread are exact.
- A3 (verifies R3): €STR/USD and null/no-fill semantics are exact.
- A4 (verifies R4): all macro tests pass offline.

## PR-17: Assemble And Validate Canonical Daily Gold Frame

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-17/canonical-gold-frame`

Git status: `not-started (branch absent)`

Agent lane: Integration; one agent only

Depends on: PR-15, PR-16

Commit: `feat(pr-17): assemble canonical gold frame`

Description:
- R1: Outer-join feature families only on `timestamp_m1`; define exact stable schema/order with timestamp first, all feature columns Float64-or-null, no unexpected/date columns.
- R2: Validate non-empty, unique/strictly sorted exact timestamp dtype and exact feature schema; define source-controlled `schema_version=1`, `feature_version=1` with explicit bump rules and no runtime auto-bump.
- R3: Document timestamp as observation-day identity, not publication/tradability time; MVP is not same-day intraday point-in-time safe without downstream lag/availability policy.
- R4: Keep assembly storage-neutral and test outer-join nulls, schema/order/type, invalid timestamps/columns, versions and absence of storage side effects.

Acceptance:
- A1 (verifies R1): one row per union timestamp and exact complete column order.
- A2 (verifies R2): invalid frames fail and version constants/rules are explicit.
- A3 (verifies R3): docs/tests never claim UTC midnight is information availability.
- A4 (verifies R4): all assembly tests pass and module performs no filesystem/publication work.

## PR-18: Add Immutable Versioned Gold Parquet Storage

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-18/versioned-gold-storage`

Git status: `not-started (branch absent)`

Agent lane: Agent A

Depends on: PR-17

Commit: `feat(pr-18): add immutable gold parquet storage`

Description:
- R1: Validate injected UTC build IDs `YYYYMMDDTHHMMSSZ` and atomically create the exact build `data.parquet` preserving canonical Gold schema.
- R2: Make build path creation-only: any existing target build directory/data path fails before writing, independent of future catalog status.
- R3: Provide explicit-build reader only; never discover latest/current by mtime/order.
- R4: Return rows, columns, min/max timestamp, semantic versions and SHA-256 of final Parquet bytes; test ID/path/schema/atomic failure/creation-only/coexistence/readback/hash.

Acceptance:
- A1 (verifies R1): exact IDs/path/schema and malformed/non-UTC IDs fail.
- A2 (verifies R2): second create cannot modify prior bytes.
- A3 (verifies R3): explicit build A never returns B.
- A4 (verifies R4): metadata/hash independently match file and all storage tests pass.

## PR-19: Add Gold Parquet Catalog And Consumer Selection Contract

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-19/gold-catalog-contract`

Git status: `not-started (branch absent)`

Agent lane: Agent B

Depends on: PR-17

Commit: `feat(pr-19): add gold manifest catalog`

Description:
- R1: Define root `manifest.parquet` with exactly the 14 global catalog fields and atomic deterministic ordering by `started_at_utc`, then `build_id`.
- R2: Validate unique IDs, status enum, current invariants, UTC types, nonnegative counts; selectable complete rows require all three artifact paths.
- R3: Allow zero current before first success; otherwise at most one current and only complete may be current.
- R4: Implement pure compatible-current then newest-compatible-complete fallback by completion/build ID; never inspect filesystem; test exact schema, invalid states, ordering and selection.

Acceptance:
- A1 (verifies R1): exact 14 fields/path/order and no legacy date-only min/max.
- A2 (verifies R2): every invalid status/current/type/count/path condition fails.
- A3 (verifies R3): empty/pre-first-success is valid; multiple/non-complete current fails.
- A4 (verifies R4): current/fallback tests pass without filesystem discovery.

## PR-20: Generate Immutable Gold JSON And Feature-Profile Sidecars

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-20/gold-build-sidecars`

Git status: `not-started (branch absent)`

Agent lane: Agent A

Depends on: PR-18

Commit: `feat(pr-20): add gold json and plot sidecars`

Description:
- R1: Create sorted UTF-8 build `manifest.json` containing identity/versions/status/times/rows/columns/min/max/data+plot paths plus `data_sha256`, `feature_set_hash`, `git_commit_hash`.
- R2: Define stable `feature_set_hash` over versions + ordered feature names + transformation parameters; use repository Git hash when available and deterministic `nogit` only when Git metadata is unavailable.
- R3: Create deterministic `feature_profile.png` from exactly the Gold frame, excluding timestamp and plotting only numeric features in stable order; no random/wall-clock sampling/content.
- R4: JSON/PNG are creation-only; validate JSON against Parquet/frame and PNG readability/non-empty; test paths, serialization, hashes, Git fallback, plot content/order, immutability and failure propagation.

Acceptance:
- A1 (verifies R1): fixed build JSON is sorted and matches artifact/frame metadata.
- A2 (verifies R2): hashes/Git fallback are deterministic.
- A3 (verifies R3): plot covers only numeric features in stable order with timestamp excluded.
- A4 (verifies R4): pre-existing/mismatched/corrupt sidecars fail without modifying prior artifacts and all tests pass.

## PR-21: Publish Gold Catalog, JSON Mirror, And Current Plot Transactionally

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-21/transactional-gold-publication`

Git status: `not-started (branch absent)`

Agent lane: Integration; one agent only

Depends on: PR-19, PR-20

Commit: `feat(pr-21): publish gold builds transactionally`

Description:
- R1: Register attempt as `building,current=false` by staging matching root JSON + next catalog, replacing JSON first and authoritative Parquet last; existing current/plot remain unchanged.
- R2: Build/validate immutable Parquet+JSON+PNG; successful promotion stages next catalog (`new complete/current`, old demoted), root JSON mirror and byte-copy root plot, then replaces supplemental files with rollback and `manifest.parquet` last as promotion commit point.
- R3: Failure changes only attempt to `failed,current=false`, updates root JSON mirror, preserves old current/root plot; stale `building` rows from interrupted processes are deterministically failed on next publication entry and never auto-promoted from filesystem presence.
- R4: Root JSON must mirror authoritative catalog/current ID after every successful catalog mutation and root plot bytes equal current build plot; add failure injection for registration/build/promotion/failure/recovery plus success.

Acceptance:
- A1 (verifies R1): building registration is visible but never changes current selection/plot and JSON/catalog remain consistent.
- A2 (verifies R2): invalid bundle never promotes; success leaves exactly one current and Parquet is the last authority switch.
- A3 (verifies R3): failures/restarts preserve old current and stale builds never auto-promote.
- A4 (verifies R4): all consistency, byte-equality, failure-injection and success cases pass offline.

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
- R1: Default `gold_retention_successful_builds=5`, counted per `(schema_version, feature_version)` including current; prune oldest eligible non-current complete by completion time then build ID.
- R2: Treat Parquet+JSON+PNG as one bundle; never prune current/building or another semantic pair.
- R3: Retain audit rows but null all three artifact paths after physical pruning; consumer selection must exclude them.
- R4: Retention is restart-safe/idempotent: already-pruned unselectable rows are okay; partial bundle deletion of a selectable row is a consistency error; test default/custom/current/version/bundle/repeat/partial cases.

Acceptance:
- A1 (verifies R1): limit/tie-breaking are exact.
- A2 (verifies R2): three artifacts are preserved/deleted together and protected states/pairs remain.
- A3 (verifies R3): pruned rows remain but are unselectable with all paths null.
- A4 (verifies R4): second run is no-op, partial selectable bundle fails, all retention tests pass.

## PR-23: Add Daily Medallion CLI Pipeline And End-To-End Regression

Status: Planned

Updated: 2026-08-18

PR: none

Git branch: `pr-23/daily-medallion-pipeline`

Git status: `not-started (branch absent)`

Agent lane: Integration; one agent only

Depends on: PR-14, PR-22

Commit: `feat(pr-23): add daily medallion pipeline`

Description:
- R1: Add `bootstrap`, `update`, `silver-build`, `gold-build`, `run-daily`; unknown series fail before side effects and `gold-build` publishes only through PR-21.
- R2: `run-daily` executes Bronze -> Silver -> feature families -> Gold assembly -> immutable bundle -> validation -> registration/promotion -> retention -> inventory refresh with explicit stage results.
- R3: Defaults target all 13 series; repeatable `--series` restricts source work. Pre-publication failure returns non-zero and preserves prior Gold current/root plot while separately durable Bronze successes may remain.
- R4: Add offline end-to-end bootstrap + next-day revision + full-file truncation + UTC timestamp + publication + consumer selection + idempotent rerun + retention + inventory fixture, plus interrupted-building recovery regression.
- R5: Document daily cron and systemd timer, working directory/configuration, no scheduled GitHub Actions ingestion, and keep all required integration gates offline with live checks marked `network`.

Acceptance:
- A1 (verifies R1): all commands parse, unknown series has no side effect and Gold contract remains exact.
- A2 (verifies R2): tracing proves stage order and all build/root artifacts exist after success.
- A3 (verifies R3): defaults/filters/failure preservation behave exactly as stated.
- A4 (verifies R4): complete end-to-end and stale-building recovery scenarios pass offline.
- A5 (verifies R5): README documents both scheduler forms/runtime requirements, no scheduled ingestion action exists, and required integration excludes network.

## Definition Of MVP Complete

The MVP is complete only when PR-01 through PR-23 are merged and all of the following are true:

- every implementation branch/commit follows the `pr-XX` Git naming contract and backlog Git metadata is current;
- local pre-push and remote push/PR/merge quality gates run `lint`, `type`, `unit`, and offline `integration` in parallel, and `main` cannot merge with a required check failing;
- an empty lake can bootstrap every available initial series to maximum exposed public history;
- subsequent runs fetch/refetch only planner-approved correction/delta scope and are duplicate-safe, restart-safe and no-op safe;
- upstream truncation never deletes older locally retained history;
- Bronze, Silver, Gold, state, operational manifests and Gold catalogs use the documented contracts;
- Gold uses only `timestamp_m1: Datetime(us, UTC)` as temporal key without misrepresenting midnight as information availability;
- feature formulas, observation-lag rules, rolling-window rules, same-timestamp joins and semantic versions are explicit/tested;
- Gold contains reusable causal market-state features only, not regimes, labels, targets, portfolio weights or trading decisions;
- every successful Gold build is immutable Parquet+JSON+PNG with reproducibility hashes/metadata;
- root Parquet/JSON/PNG remain consistent, with Parquet the sole selection authority;
- interrupted `building` attempts are restart-safe and never auto-promoted by filesystem discovery;
- retention preserves configured complete bundles per semantic version pair without deleting current or silently accepting partial selectable bundles;
- `run-daily` can be scheduled once daily, preserves separately durable Bronze successes and never publishes partial Gold state;
- required integration tests are offline; future live tests are `network` and never required for push/merge;
- `README.md`, `ARCHITECTURE.md`, and this backlog remain synchronized with implementation.