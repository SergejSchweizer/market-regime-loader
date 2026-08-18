# Backlog

This backlog is the implementation source of truth for `market-regime-loader`.

The repository loads reusable daily market-regime inputs from open/public sources, stores the maximum history exposed by each configured source, and performs restart-safe daily incremental updates. Data is managed with Polars and Parquet using a Bronze -> Silver -> Gold medallion architecture. Gold publication additionally produces deterministic JSON and PNG sidecars.

Last updated: 2026-08-18

## Delivery Policy

- One `PR-XX` entry equals one logical pull request.
- PRs must remain small enough for weak coding agents: one infrastructure boundary, one provider family, one transformation boundary, or one publication responsibility per PR.
- Every PR contains separate `Status`, `Updated`, `PR`, `Branch`, `Agent lane`, `Depends on`, and `Commit` fields.
- Valid statuses are `Planned`, `In Progress`, `Blocked`, `Ready`, and `Merged`.
- Every `Description` requirement has an ID `R1`, `R2`, ... and every `Acceptance` check has the matching ID `A1`, `A2`, .... `A1` verifies only `R1`, `A2` verifies only `R2`, etc.
- Description and Acceptance must have exactly the same number of numbered items.
- No PR may silently add a second responsibility beyond its numbered requirements.
- Unit tests must not call external services. Provider tests use committed small fixtures or mocked HTTP responses.
- Network integration tests, when added, must be explicitly marked and excluded from the default test command.
- Production data under `lake/` is ignored by Git and never committed.
- Polars is the production dataframe engine. Do not introduce pandas into production code.
- Parquet is the durable tabular format for Bronze, Silver, Gold, state, catalogs, and inventories.
- Gold JSON sidecars are deterministic UTF-8 JSON; Gold plots are deterministic PNG artifacts.
- Writes are deterministic, idempotent, duplicate-safe, and restart-safe.
- Bronze/Silver dates are stored as `Date`; timestamps are timezone-aware UTC timestamps.
- Missing observations are never synthesized in Bronze or Silver.
- Gold features are causal and may use current/past information only.
- Gold uses the same canonical timestamp contract as `crypto-history-loader`: `timestamp_m1: Datetime(time_unit="us", time_zone="UTC")`.
- Daily Silver `observation_date` values are converted to `timestamp_m1` at `00:00:00 UTC` at the Gold boundary; Gold must not contain `observation_date`.
- Published Gold build directories are immutable and identified by `build_id`.
- Every successful Gold build contains `data.parquet`, `manifest.json`, and `feature_profile.png`.
- `lake/gold/dataset=regime_features_daily/manifest.parquet` is the only authoritative publication catalog. Root `manifest.json` and `feature_profile.png` are required sidecars but are not current-selection authority.
- Consumers must never infer the current build from directory order, file modification time, or `max(build_id)`.
- `README.md` and `ARCHITECTURE.md` are durable documentation sidecars and must be updated in the same PR whenever the implemented contract they describe changes.

## Parallel-Agent Rules

Two weak agents are expected to work in parallel.

- **Agent A lane:** series/path contracts, CBOE/STOXX/Yahoo sources, Silver normalization, volatility Gold features, immutable Gold storage, Gold build sidecars.
- **Agent B lane:** shared Parquet IO, ECB/FRED sources, manifests/inventory, macro Gold features, Gold catalog contract.
- A PR may start only after every entry in its `Depends on` field is merged.
- Independent lane PRs should branch from the same dependency-complete `main` and may proceed in parallel.
- If two planned PRs would modify the same implementation file, the later PR must rebase on current `main`; weak agents must not resolve broad semantic conflicts by guessing.

## Initial Series Catalog

| Canonical series ID | Primary source | Source series / file | Native shape | Bootstrap policy |
|---|---|---|---|---|
| `vix` | CBOE | `VIX_History.csv` | OHLC daily | complete public history |
| `vix9d` | CBOE | `VIX9D_History.csv` | OHLC daily | complete public history |
| `vix3m` | CBOE | `VIX3M_History.csv` | OHLC daily | complete public history when available |
| `vix6m` | CBOE | `VIX6M_History.csv` | OHLC daily | complete public history when available |
| `vix1y` | CBOE | `VIX1Y_History.csv` | OHLC daily | complete public history when available |
| `vstoxx` | STOXX | VSTOXX / `V2TX` history | scalar/provider-native daily | complete public history |
| `move` | Yahoo Finance | `^MOVE` | OHLC daily | maximum available history |
| `ciss` | ECB Data Portal | `CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX` | scalar daily | complete ECB history |
| `estr` | ECB Data Portal | `EST.B.EU000A2X2A25.WT` | scalar business-day | complete ECB history |
| `euro_hy_oas` | FRED | `BAMLHE00EHYIOAS` | scalar daily | all currently exposed observations; never truncate older local history |
| `us_2y` | FRED | `DGS2` | scalar daily | complete FRED history |
| `us_10y` | FRED | `DGS10` | scalar daily | complete FRED history |
| `usd_broad` | FRED | `DTWEXBGS` | scalar daily | complete FRED history |

No additional series belongs in the initial implementation without a separate backlog PR.

## Medallion Storage Contract

```text
lake/
  bronze/
    provider=<provider>/
      series=<series_id>/
        year=<YYYY>/
          month=<MM>/
            data.parquet

  silver/
    series=<series_id>/
      year=<YYYY>/
        month=<MM>/
          data.parquet

  gold/
    dataset=regime_features_daily/
      versions/
        build_id=<YYYYMMDDTHHMMSSZ>/
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

Bronze/Silver use monthly partitions. Every Gold build is a complete immutable snapshot bundle.

### Bronze contract

```text
series_id: String
provider: String
observation_date: Date
fetched_at_utc: Datetime[UTC]
source_id: String
source_url: String
```

Provider-native OHLC or scalar value fields are retained. Natural key: `(provider, series_id, observation_date)`.

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
fetched_at_utc: Datetime[UTC]
```

Natural key: `(series_id, observation_date)`. OHLC sources use `value=close`; scalar sources keep `value` and null OHLC fields.

### Gold temporal contract

Gold uses:

```text
timestamp_m1: Datetime(time_unit="us", time_zone="UTC")
```

`timestamp_m1` is the first column and unique/strictly increasing. Daily Silver dates map to UTC midnight. Gold contains no `observation_date` column.

### Gold catalog contract

Root `manifest.parquet` contains one row per attempted build:

```text
dataset_id: String
build_id: String
status: String              # building | complete | failed
current: Boolean
started_at_utc: Datetime[UTC]
completed_at_utc: Datetime[UTC] nullable
schema_version: Int64
feature_version: Int64
min_timestamp: Datetime(us, UTC) nullable
max_timestamp: Datetime(us, UTC) nullable
row_count: Int64 nullable
data_path: String nullable
build_manifest_path: String nullable
plot_path: String nullable
```

Root `manifest.json` is a deterministic mirror of this catalog/current resolution. Root `feature_profile.png` is the plot for the build identified as current by `manifest.parquet`.

## Incremental Update Contract

For each source series:

1. no Bronze history -> bootstrap maximum available public history;
2. existing history -> start at latest stored date minus a default 7-calendar-day correction overlap and end at an injected current date;
3. bounded providers request only that range;
4. compact full-file providers may refetch the complete file but merge only missing/revised logical observations;
5. upstream truncation never deletes older local history;
6. only affected Bronze monthly partitions are rewritten;
7. state advances only after a successful durable series write;
8. unchanged reruns are logically idempotent.

## PR Graph

```text
PR-01 repository bootstrap
  |\
  | +--> PR-03 parquet lake IO ------------------+
  +----> PR-02 dataset/path contracts -----------+
                                                  |
                                              PR-04 delta planner
                                              /             \
                               Agent A       /               \       Agent B
                                           /                 \
                               PR-05 CBOE                    PR-08 ECB
                                   |                            |
                               PR-06 STOXX                  PR-09 FRED
                                   |                            |
                               PR-07 Yahoo                  PR-10 manifests
                                           \                 /
                                            +---- PR-11 -----+
                                              Bronze orchestration
                                               /          \
                                      PR-12 Silver       PR-13 inventory CLI
                                           |
                         +-----------------+-----------------+
                         |                                   |
                 PR-14 volatility Gold              PR-15 macro Gold
                         \                                   /
                          +------------- PR-16 --------------+
                                  canonical Gold frame
                                      /       \
                                     /         \
                         PR-17 storage        PR-18 catalog
                              |                    |
                         PR-19 build sidecars      |
                               \                  /
                                +------ PR-20 ----+
                                  atomic publication
                                          |
                                        PR-21
                                      retention
                                          |
                              PR-13 ------+------ PR-22
                                      daily pipeline
```

---

## PR-01: Bootstrap Python Repository And Quality Gates

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr01-repository-bootstrap`

Agent lane: Foundation; one agent only

Depends on: none

Commit: `chore: bootstrap market regime loader`

Description:
- R1: Create a `uv`/`pyproject.toml` Python project using Python >=3.13 with runtime dependencies `polars`, `pyarrow`, `httpx`, `pydantic`, `PyYAML`, and `matplotlib`, plus development dependencies `pytest`, `pytest-cov`, `ruff`, and `mypy`.
- R2: Create package roots `application/`, `ingestion/`, `api/`, `scripts/`, and `tests/` with only minimal importable scaffolding.
- R3: Add `.gitignore` rules for `.venv/`, Python/test/coverage caches, and the complete `lake/` runtime tree.
- R4: Add `Makefile` targets `format-check`, `lint`, `typecheck`, `test`, and `check`; `check` must not download market data.
- R5: Keep `README.md` and `ARCHITECTURE.md` synchronized with the implemented bootstrap/tooling contract.

Acceptance:
- A1 (verifies R1): `uv sync --extra dev` resolves the stated dependency families, including plotting support, with no production pandas dependency.
- A2 (verifies R2): imports from `application`, `ingestion`, and `api` succeed and all five required roots exist.
- A3 (verifies R3): the runtime lake and listed cache artifacts are ignored and no lake output is tracked.
- A4 (verifies R4): `make check` executes all four validation classes offline.
- A5 (verifies R5): both documentation sidecars remain present and do not contradict the bootstrap implementation.

## PR-02: Define Series Registry And Lake Path Contracts

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr02-series-registry-paths`

Agent lane: Agent A

Depends on: PR-01

Commit: `feat: define series and lake contracts`

Description:
- R1: Add an immutable typed registry containing exactly the 13 initial series with provider, source ID/file, unit, native shape, frequency, bootstrap strategy, and provider capability.
- R2: Add typed path helpers for Bronze/Silver monthly files, Gold dataset root, build `data.parquet`, build `manifest.json`, build `feature_profile.png`, root `manifest.parquet`, root `manifest.json`, root `feature_profile.png`, state, and operational manifests.
- R3: Validate duplicate series IDs, unknown providers, empty source IDs, unsupported native shapes, and unsupported provider capabilities before ingestion.
- R4: Add fixed examples for `2026-08-18` and Gold build `20260818T020000Z` covering every required path.

Acceptance:
- A1 (verifies R1): the registry contains exactly 13 entries and every required metadata field is populated.
- A2 (verifies R2): helpers return exactly the documented paths, including all three build artifacts and all three root Gold sidecars.
- A3 (verifies R3): every listed invalid registry condition fails deterministically before an adapter is called.
- A4 (verifies R4): tests assert exact fixed path strings for the sample date/build ID.

## PR-03: Implement Polars Parquet Lake Read And Upsert Utilities

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr03-polars-parquet-lake-io`

Agent lane: Agent B

Depends on: PR-01

Commit: `feat: add polars parquet lake io`

Description:
- R1: Implement Polars-only helpers to read zero/one/many monthly Parquet partitions into deterministically sorted frames.
- R2: Implement atomic monthly writes using destination-filesystem temporary files followed by replace.
- R3: Implement merge/upsert by caller-supplied natural keys with new-row precedence, duplicate removal, and deterministic ordering.
- R4: Rewrite only monthly partitions represented by changed input rows; unrelated months must not be rewritten.
- R5: Add tests for empty reads, multi-month reads, idempotency, revised-row replacement, duplicate removal, ordering, and unaffected-month preservation.

Acceptance:
- A1 (verifies R1): all read modes work through Polars and production lake code contains no pandas import.
- A2 (verifies R2): successful writes leave one valid destination file/no temp files and injected failure cannot corrupt the prior destination.
- A3 (verifies R3): repeated identical input yields one logical row per key and revisions replace equal-key values exactly once.
- A4 (verifies R4): an unrelated monthly file remains byte/mtime-unmodified when another month is updated.
- A5 (verifies R5): every listed IO case has a focused passing test.

## PR-04: Implement Bootstrap And Incremental Range Planner

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr04-incremental-range-planner`

Agent lane: Foundation; first free agent

Depends on: PR-02, PR-03

Commit: `feat: add incremental ingestion planner`

Description:
- R1: Return deterministic `bootstrap` plans for series without Bronze history and `incremental` plans for series with a latest stored date.
- R2: In incremental mode calculate `start_date=latest_stored_date-overlap_days` with default 7 calendar days and `end_date=injected_today`.
- R3: Represent provider fetch capability explicitly as `date_range` or `full_file` while preserving the same logical target range.
- R4: Define/upsert `lake/state/ingestion_state.parquet` keyed by `(provider, series_id)` with last success, last observation, requested bounds, mode, and row counts.
- R5: Use injected dates/times in all planner/state tests; no wall-clock `today()` dependency is allowed.

Acceptance:
- A1 (verifies R1): fixed no-history/history fixtures produce exact bootstrap/incremental plans.
- A2 (verifies R2): tests prove default/custom overlap and exact injected end date.
- A3 (verifies R3): tests prove different fetch instructions for the two capability types without changing the logical range.
- A4 (verifies R4): state rows round-trip and upsert to one row per provider/series key.
- A5 (verifies R5): planner/state tests are deterministic and offline.

## PR-05: Add CBOE Volatility-Index Provider

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr05-cboe-volatility-provider`

Agent lane: Agent A

Depends on: PR-04

Commit: `feat: ingest cboe volatility indices`

Description:
- R1: Implement one CBOE adapter for exactly `vix`, `vix9d`, `vix3m`, `vix6m`, and `vix1y` using the public daily-history CSV family as `full_file` sources.
- R2: Parse dates and OHLC values with Polars into Bronze common metadata plus `open/high/low/close`, rejecting invalid date/close rows.
- R3: Preserve older local rows when a later CBOE response is shorter and allow overlap revisions to replace equal natural keys.
- R4: Fail unavailable/unsupported CBOE series explicitly without silently switching to another provider.
- R5: Add fixtures/tests for valid parsing, duplicate date, revised close, truncated history, and unavailable series.

Acceptance:
- A1 (verifies R1): exactly the five documented series route through one CBOE full-file adapter.
- A2 (verifies R2): fixture rows produce the exact typed Bronze metadata/OHLC shape and invalid rows are rejected.
- A3 (verifies R3): truncated responses cannot delete prior history and revisions replace only matching keys.
- A4 (verifies R4): unavailable series errors name the canonical series and no fallback is called.
- A5 (verifies R5): all five stated cases pass offline.

## PR-06: Add STOXX VSTOXX Provider

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr06-stoxx-vstoxx-provider`

Agent lane: Agent A

Depends on: PR-05

Commit: `feat: ingest vstoxx history`

Description:
- R1: Implement a STOXX adapter only for `vstoxx` / `V2TX` with maximum public-history bootstrap.
- R2: Parse a representative real provider shape into Bronze common metadata and scalar/OHLC fields matching the source, keeping `source_id=V2TX` stable.
- R3: Use `full_file` unless the selected public endpoint demonstrably supports bounded ranges; never truncate older local rows.
- R4: Add representative fixture tests for bootstrap parsing, one revision, and truncated-response preservation.

Acceptance:
- A1 (verifies R1): only `vstoxx` is accepted and all fixture history is returned on bootstrap.
- A2 (verifies R2): output matches the declared Bronze source shape and stable source ID.
- A3 (verifies R3): capability is deterministic and a shorter response cannot remove prior history.
- A4 (verifies R4): all three provider behaviors pass offline.

## PR-07: Add Yahoo MOVE Provider

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr07-yahoo-move-provider`

Agent lane: Agent A

Depends on: PR-06

Commit: `feat: ingest move index history`

Description:
- R1: Implement a Yahoo adapter only for canonical `move` and ticker `^MOVE`.
- R2: Bootstrap with maximum available daily history and use exact planner start/end bounds for incremental requests through a mockable client boundary.
- R3: Normalize daily OHLC observations into Bronze metadata/OHLC fields while excluding unrelated corporate-action/volume fields.
- R4: Add tests for maximum-history args, bounded args, empty result, revised-date input, and OHLC normalization.

Acceptance:
- A1 (verifies R1): unrelated series/tickers are rejected.
- A2 (verifies R2): mocked calls prove exact bootstrap and incremental request arguments.
- A3 (verifies R3): normalized output contains only the declared Bronze metadata and OHLC market fields.
- A4 (verifies R4): all five stated cases pass offline.

## PR-08: Add ECB CISS And ESTR Provider

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr08-ecb-provider`

Agent lane: Agent B

Depends on: PR-04

Commit: `feat: ingest ecb regime series`

Description:
- R1: Implement an ECB SDMX/CSV adapter for exactly `ciss` and `estr` using their registered series keys.
- R2: Bootstrap complete exposed history and pass exact planner start/end periods in incremental mode.
- R3: Parse dates/values with Polars into Bronze scalar rows, excluding missing/non-numeric observations without creating zeroes.
- R4: Allow overlap revisions to replace equal-key rows and never synthesize weekend/holiday observations.
- R5: Add fixtures/tests for both series, bootstrap/bounded requests, one revision, and one normal calendar gap.

Acceptance:
- A1 (verifies R1): exactly the two registered ECB series are accepted.
- A2 (verifies R2): mocked requests prove exact full/bounded request behavior.
- A3 (verifies R3): valid values become Float64 and missing/non-numeric rows are absent rather than zero.
- A4 (verifies R4): revision replacement works and calendar gaps remain gaps.
- A5 (verifies R5): all stated cases pass offline.

## PR-09: Add FRED Rates, Credit, And Dollar Provider

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr09-fred-provider`

Agent lane: Agent B

Depends on: PR-08

Commit: `feat: ingest fred regime series`

Description:
- R1: Implement one FRED adapter mapping exactly `DGS2`, `DGS10`, `DTWEXBGS`, and `BAMLHE00EHYIOAS` to their four canonical series IDs.
- R2: Bootstrap full currently exposed history and use exact planner bounds incrementally.
- R3: Parse FRED date/value data with Polars and treat `.`/blank as missing rather than zero/fill.
- R4: Preserve older local `euro_hy_oas` history if FRED later exposes a shorter rolling window.
- R5: Add fixtures/tests for all four series, request modes, missing values, revision, and truncated Euro HY history.

Acceptance:
- A1 (verifies R1): only the four documented source IDs map to canonical FRED series.
- A2 (verifies R2): mocked requests prove full and bounded behavior.
- A3 (verifies R3): missing markers emit no fabricated observations.
- A4 (verifies R4): shorter HY responses cannot truncate local minimum date and overlap revisions still update.
- A5 (verifies R5): all stated cases pass offline.

## PR-10: Add Bronze Coverage And Run Manifests

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr10-bronze-coverage-manifests`

Agent lane: Agent B

Depends on: PR-09, PR-03

Commit: `feat: add bronze coverage manifests`

Description:
- R1: Build one inventory row per canonical series with provider, min observation date, max observation date, row count, duplicate-key count, and physical file count.
- R2: Build one ingestion-run row per provider/series execution with run ID, mode, requested bounds, fetched rows, changed rows, written partitions, status, and UTC timestamps.
- R3: Persist inventory/run data in their documented Parquet paths using shared merge utilities.
- R4: Do not classify weekends/holidays as missing or synthesize a calendar-completeness metric.
- R5: Add tests for empty/populated inventory, duplicate detection, success run, and failed run.

Acceptance:
- A1 (verifies R1): inventory exposes exactly the six stated coverage fields.
- A2 (verifies R2): run fixtures contain every stated execution field.
- A3 (verifies R3): rows round-trip/upsert without duplicate logical keys.
- A4 (verifies R4): no weekend/holiday missing-day metric exists.
- A5 (verifies R5): all five cases pass.

## PR-11: Add Registry-Driven Bronze Orchestration

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr11-bronze-orchestration`

Agent lane: Foundation; first free agent

Depends on: PR-05, PR-06, PR-07, PR-08, PR-09, PR-10

Commit: `feat: orchestrate bronze updates`

Description:
- R1: Add an application service that accepts canonical series IDs, builds plans from Bronze state, routes each series only to its registered adapter, and writes through shared lake IO.
- R2: Add bootstrap/update modes using the range planner and an injected current date.
- R3: Isolate each series execution so one provider failure records failure metadata without corrupting another successful series.
- R4: Advance ingestion state only after data write and success-run metadata are durable; failures retain prior success state.
- R5: Add fake-adapter tests for routing, bootstrap, incremental update, partial failure, restart, and idempotency.

Acceptance:
- A1 (verifies R1): fake adapters prove exact registry routing and shared writer use.
- A2 (verifies R2): fixed-date tests select exact expected plans.
- A3 (verifies R3): one simulated failure coexists with an independently successful readable series.
- A4 (verifies R4): failure leaves prior state unchanged and success advances it only after persistence.
- A5 (verifies R5): all listed orchestration behaviors pass repeatedly without duplicates.

## PR-12: Build Canonical Silver Daily Series

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr12-silver-canonical-series`

Agent lane: Agent A

Depends on: PR-11

Commit: `feat: build canonical silver series`

Description:
- R1: Implement a registry-driven Silver builder producing the exact canonical Silver schema from all Bronze history for a selected series.
- R2: Set `value=close` for OHLC sources; use scalar `value` and null OHLC fields for scalar sources.
- R3: Deduplicate `(series_id, observation_date)`, sort dates, reject non-finite values, and never fill missing dates.
- R4: Rebuild only selected series and write deterministic monthly Silver partitions.
- R5: Add tests for one OHLC series, one scalar series, deduplication, non-finite rejection, and preserved missing dates.

Acceptance:
- A1 (verifies R1): output columns/types match the Silver contract exactly.
- A2 (verifies R2): both source-shape mappings produce expected fields.
- A3 (verifies R3): duplicate/non-finite/missing-date behaviors match the contract.
- A4 (verifies R4): selecting one series rewrites only its Silver paths.
- A5 (verifies R5): all five cases pass.

## PR-13: Add Lake Inventory CLI

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr13-lake-inventory-cli`

Agent lane: Agent B

Depends on: PR-10, PR-11

Commit: `feat: add lake inventory cli`

Description:
- R1: Add `inventory` CLI outputting one stable row per series with provider, min/max date, row count, duplicate count, and file count.
- R2: Add non-mutating `--series` and `--provider` filters.
- R3: Add deterministic `--json` output with the same logical fields as text output.
- R4: Empty series are valid; only command/config/read errors cause non-zero exit.
- R5: Add parser/output tests for unfiltered, both filters, JSON, and empty series.

Acceptance:
- A1 (verifies R1): fixed fixtures produce exactly the six stated text fields.
- A2 (verifies R2): filters return only matching rows and do not mutate lake files.
- A3 (verifies R3): JSON carries exactly equivalent fields/values.
- A4 (verifies R4): empty series succeeds while injected read/config errors fail.
- A5 (verifies R5): all five cases pass.

## PR-14: Build Volatility Gold Features On Canonical Timestamp

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr14-volatility-gold-features`

Agent lane: Agent A

Depends on: PR-12

Commit: `feat: add volatility regime features`

Description:
- R1: Convert each selected Silver `observation_date` to `timestamp_m1` at `00:00:00 UTC`, cast exactly to Polars `Datetime(time_unit="us", time_zone="UTC")`, and remove `observation_date` from volatility Gold output.
- R2: Build for `vix`, `vix9d`, `vix3m`, `vix6m`, `vix1y`, `vstoxx`, and `move`: level, 5-observation change, 20-observation change, and 60-observation trailing z-score using only current/past non-null observations.
- R3: Build `vix9d_vix_ratio`, `vix_vix3m_ratio`, `vix3m_minus_vix`, `vix6m_minus_vix`, and `vix1y_minus_vix` only when required same-timestamp inputs coexist.
- R4: Preserve nulls until rolling windows have sufficient observations; do not fill dates or use centered/future windows.
- R5: Add hand-calculable tests for exact timestamp name/type/midnight conversion, formulas, denominator-zero behavior, minimum-history nulls, and no future leakage.

Acceptance:
- A1 (verifies R1): output begins with unique sorted `timestamp_m1: Datetime(us, UTC)`, fixture date `2026-08-18` maps exactly to UTC midnight, and no `observation_date` column exists.
- A2 (verifies R2): all seven series expose exactly the four stated causal feature classes with expected fixture values.
- A3 (verifies R3): all five term-structure features match expected values and appear only with required same-timestamp inputs.
- A4 (verifies R4): insufficient/missing histories remain null and no fill/centered-window operation affects output.
- A5 (verifies R5): all stated timestamp/formula/leakage tests pass.

## PR-15: Build Macro, Credit, Rates, And Dollar Gold Features On Canonical Timestamp

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr15-macro-gold-features`

Agent lane: Agent B

Depends on: PR-12

Commit: `feat: add macro regime features`

Description:
- R1: Convert Silver `observation_date` to `timestamp_m1` at UTC midnight with exact Polars `Datetime(time_unit="us", time_zone="UTC")` and remove `observation_date` from macro Gold output.
- R2: Build CISS level/5-change/20-change and Euro HY OAS level/5-change/20-change.
- R3: Build US 2Y/10Y levels, 20-observation changes, and `us_10y_minus_us_2y` only where both yields coexist at the same timestamp.
- R4: Build €STR level/20-change and USD broad level/20-change; preserve nulls and never fill absent business dates/use future observations.
- R5: Add hand-calculable tests for timestamp conversion/type, all feature families, missing-yield dates, minimum-history nulls, and no future leakage.

Acceptance:
- A1 (verifies R1): output begins with unique sorted `timestamp_m1: Datetime(us, UTC)`, fixed daily dates map to UTC midnight, and `observation_date` is absent.
- A2 (verifies R2): CISS/HY fixtures expose exactly the required values.
- A3 (verifies R3): yield levels/changes/spread match expected values and missing-pair timestamps remain null.
- A4 (verifies R4): €STR/USD outputs match expected values and no fill/future use occurs.
- A5 (verifies R5): all timestamp/feature/leakage cases pass.

## PR-16: Assemble Canonical Daily Gold Frame

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr16-assemble-daily-gold`

Agent lane: Integration; one agent only

Depends on: PR-14, PR-15

Commit: `feat: assemble daily gold dataset`

Description:
- R1: Outer-join volatility and macro Gold feature families only on `timestamp_m1`, producing one row per union timestamp with null preservation and no imputation.
- R2: Define one deterministic ordered Gold schema whose first column is exactly `timestamp_m1: Datetime(time_unit="us", time_zone="UTC")`; all remaining columns are the complete PR-14/PR-15 numeric-or-null feature set and `observation_date` is forbidden.
- R3: Validate non-empty output, strict timestamp ordering/uniqueness, exact timestamp dtype, numeric-or-null features, and no future-leakage condition.
- R4: Keep this PR storage-neutral: no build-ID generation, filesystem writes, JSON, plots, manifest mutation, publication, or retention.
- R5: Add focused tests for outer-join null preservation, exact schema/order/type, duplicate timestamp rejection, chronological ordering, forbidden `observation_date`, and storage-neutral behavior.

Acceptance:
- A1 (verifies R1): fixtures produce exactly one row per union `timestamp_m1` and preserve missing-family nulls.
- A2 (verifies R2): tests assert exact first-column name/type, deterministic column order, and absence of `observation_date`.
- A3 (verifies R3): empty/unsorted/duplicate/wrong-type/non-numeric/future-leakage fixtures fail deterministic validation.
- A4 (verifies R4): the assembly module contains no storage/publication/sidecar side effects.
- A5 (verifies R5): all stated assembly tests pass.

## PR-17: Add Immutable Versioned Gold Parquet Storage

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr17-versioned-gold-storage`

Agent lane: Agent A

Depends on: PR-16

Commit: `feat: add immutable gold build storage`

Description:
- R1: Define/validate build IDs in exact UTC-sortable format `YYYYMMDDTHHMMSSZ` from an injected build time.
- R2: Atomically write one validated canonical Gold frame to `lake/gold/dataset=regime_features_daily/versions/build_id=<build_id>/data.parquet` using Polars.
- R3: Treat an existing completed build `data.parquet` path as immutable and fail rather than overwrite/merge it.
- R4: Provide an explicit-build reader that loads only the requested build ID and never performs implicit latest-file discovery.
- R5: Add tests for ID validation, exact path, timestamp schema preservation, atomic write, overwrite rejection, and coexistence/readback of two builds.

Acceptance:
- A1 (verifies R1): fixed time produces e.g. `20260818T020000Z` and malformed IDs are rejected.
- A2 (verifies R2): successful write creates exactly the documented Parquet path and preserves `timestamp_m1: Datetime(us, UTC)`.
- A3 (verifies R3): repeated same-build write fails without changing the first artifact.
- A4 (verifies R4): explicitly reading build A cannot return build B because of recency/order.
- A5 (verifies R5): all stated storage/versioning cases pass.

## PR-18: Add Gold Parquet Catalog And Consumer Selection Contract

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr18-gold-catalog-contract`

Agent lane: Agent B

Depends on: PR-16

Commit: `feat: add gold manifest catalog`

Description:
- R1: Define root `manifest.parquet` with exactly the 14 fields documented in the Gold catalog contract, including `min_timestamp`, `max_timestamp`, `data_path`, `build_manifest_path`, and `plot_path`.
- R2: Persist only to `lake/gold/dataset=regime_features_daily/manifest.parquet` with deterministic ordering by `started_at_utc`, then `build_id`, using atomic replacement.
- R3: Validate statuses, unique build IDs, current-state invariants, exact UTC timestamp types for min/max, and require all three artifact paths for a selectable complete build.
- R4: Implement pure consumer resolution: compatible `complete,current=true` first; otherwise newest compatible complete row with all artifact paths non-null ordered by `completed_at_utc DESC, build_id DESC`; never select building/failed.
- R5: Add tests for schema/round-trip, invalid state combinations, duplicate build IDs, timestamp types, deterministic ordering, and current/fallback selection.

Acceptance:
- A1 (verifies R1): catalog fixtures expose exactly the 14 fields and date-only `min_date/max_date` fields do not exist.
- A2 (verifies R2): only one atomic root catalog file exists at the exact path and ordering is deterministic.
- A3 (verifies R3): every listed invalid state/path/timestamp condition is rejected; pre-first-publication zero-current state is allowed.
- A4 (verifies R4): fixtures prove current-compatible preference and newest-compatible fallback with no filesystem-recency logic.
- A5 (verifies R5): all stated catalog/selection cases pass.

## PR-19: Generate Immutable Gold JSON And Feature-Profile Sidecars

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr19-gold-build-sidecars`

Agent lane: Agent A

Depends on: PR-17

Commit: `feat: add gold json and plot sidecars`

Description:
- R1: Generate deterministic UTF-8 build `manifest.json` at `versions/build_id=<build_id>/manifest.json` containing at least dataset/build/schema/feature identity, status, start/completion timestamps, `rows_out`, ordered `columns`, `min_timestamp`, `max_timestamp`, `data_path`, and `plot_path`; JSON keys are stably sorted.
- R2: Generate `versions/build_id=<build_id>/feature_profile.png` from exactly the canonical Gold frame using a reusable feature-profile plotting service analogous to `crypto-history-loader`; exclude `timestamp_m1` and plot only numeric feature columns.
- R3: Treat the build JSON and PNG as immutable siblings of `data.parquet`: existing completed paths for the same build ID must not be overwritten and a successful build requires all three files.
- R4: Make plot generation deterministic and offline: no random sampling, no wall-clock-dependent chart contents, and identical input/schema must produce equivalent plotted feature coverage/order.
- R5: Add tests for exact paths, JSON field/order equivalence, timestamp serialization, PNG creation/non-empty validity, exclusion of `timestamp_m1`, immutable overwrite rejection, and sidecar failure propagation.

Acceptance:
- A1 (verifies R1): a fixed build produces a valid sorted-key JSON object with every required field and timestamps corresponding exactly to the Parquet frame/build metadata.
- A2 (verifies R2): a non-empty PNG exists at the exact build path and the plotting input excludes `timestamp_m1` while covering only numeric feature columns.
- A3 (verifies R3): completed build bundles contain exactly required Parquet/JSON/PNG artifacts and second writes fail without modifying them.
- A4 (verifies R4): repeated fixed-input tests preserve feature ordering/coverage and use no random/wall-clock chart data.
- A5 (verifies R5): all stated sidecar/immutability/failure cases pass.

## PR-20: Publish Gold Build And Root Sidecars Transactionally

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr20-atomic-gold-publication`

Agent lane: Integration; one agent only

Depends on: PR-18, PR-19

Commit: `feat: publish gold builds transactionally`

Description:
- R1: Implement publication orchestration that registers a new build as `building,current=false`, completes/validates the immutable `data.parquet + manifest.json + feature_profile.png` build bundle, and refuses promotion when any artifact/schema/timestamp/count validation fails.
- R2: Generate root `manifest.json` as a deterministic mirror of the next authoritative catalog with top-level `dataset_id`, `current_build_id`, and ordered `builds`; stage root `feature_profile.png` as the exact current candidate build plot.
- R3: Stage all root replacements, replace supplemental root JSON/PNG with rollback protection, and replace root `manifest.parquet` last as the publication commit point so the new build and old-current demotion become authoritative in one catalog write.
- R4: On any pre-commit failure, restore/retain the previous root JSON/PNG/catalog and previous current build; record the attempted build as `failed,current=false` only when doing so cannot expose it as current.
- R5: Add failure-injection tests after build Parquet, build JSON, build plot, root JSON stage, root plot stage, and before/at catalog commit, plus a success test proving root JSON/catalog consistency and root plot equality to current build plot.

Acceptance:
- A1 (verifies R1): no build missing/invalid in any of the three immutable artifacts can become `complete,current=true`.
- A2 (verifies R2): root JSON mirrors the candidate catalog/current ID deterministically and root PNG corresponds exactly to the candidate build plot.
- A3 (verifies R3): successful publication ends with exactly one current complete catalog row and `manifest.parquet` is demonstrably the last authority switch rather than JSON/PNG existence.
- A4 (verifies R4): every injected pre-commit failure leaves the prior current catalog selection and its root sidecars intact, with the attempt non-current.
- A5 (verifies R5): all six failure points plus successful consistency/current-plot scenario pass offline.

## PR-21: Add Gold Build-Bundle Retention

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr21-gold-retention`

Agent lane: Foundation; first free agent

Depends on: PR-20

Commit: `feat: retain recent gold build bundles`

Description:
- R1: Add `gold_retention_successful_builds` with default `5`, meaning five physically retained complete build directories including current per `(schema_version, feature_version)` pair.
- R2: After successful publication, prune oldest eligible non-current complete build directories beyond the limit by `completed_at_utc`, then `build_id`.
- R3: Treat each build directory atomically for retention: `data.parquet`, `manifest.json`, and `feature_profile.png` are retained/pruned together; never prune current/building/failed or another semantic version pair.
- R4: Retain catalog audit rows for pruned complete builds but set `data_path`, `build_manifest_path`, and `plot_path` to null so they are unselectable.
- R5: Add tests for default/custom retention, current protection, semantic-version isolation, bundle-level deletion, and retained audit rows with all three paths nulled.

Acceptance:
- A1 (verifies R1): default configuration retains at most five physical complete bundles per semantic pair including current.
- A2 (verifies R2): six eligible builds prune only the oldest non-current bundle and retain the five newest.
- A3 (verifies R3): all three files are removed/preserved as one bundle and protected states/version pairs remain untouched.
- A4 (verifies R4): pruned audit rows remain but have all three artifact paths null and cannot be selected.
- A5 (verifies R5): all stated retention cases pass.

## PR-22: Add Daily Medallion Pipeline And Published Gold Bundle

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr22-daily-medallion-pipeline`

Agent lane: Integration; one agent only

Depends on: PR-13, PR-20, PR-21

Commit: `feat: add daily medallion pipeline`

Description:
- R1: Add CLI commands `bootstrap`, `update`, `silver-build`, `gold-build`, and `run-daily`; `gold-build` must assemble the canonical `timestamp_m1` frame and publish only through the PR-20 publication service.
- R2: Make `run-daily` execute Bronze update -> deterministic Silver rebuild -> Gold feature assembly -> immutable Parquet/JSON/PNG build -> validation -> root JSON/PNG staging -> authoritative Parquet catalog publication -> retention -> inventory refresh.
- R3: Default source-processing commands to all 13 registry series and support repeatable `--series` targeting without changing Gold schema/timestamp semantics.
- R4: Return non-zero and leave previous current Gold/root sidecars authoritative if any requested Bronze/Silver/Gold pre-publication stage fails; never expose a partial new Gold bundle.
- R5: Add an end-to-end offline fixture test covering first bootstrap, next-day delta with a revised source value, UTC-midnight `timestamp_m1`, Parquet/JSON/PNG Gold publication, catalog selection, repeated idempotent source rerun, and inventory refresh.
- R6: Document a once-daily cron/systemd invocation; do not add a scheduled GitHub Actions ingestion job because the runtime lake is not Git-persisted.

Acceptance:
- A1 (verifies R1): all commands parse and Gold outputs contain exact `timestamp_m1: Datetime(us, UTC)` with no `observation_date`.
- A2 (verifies R2): integration tracing proves the stated stage order and successful output contains all three immutable build files plus all three root sidecars.
- A3 (verifies R3): defaults target exactly 13 series and repeatable `--series` restricts source execution without altering Gold contract.
- A4 (verifies R4): injected pre-publication failures return non-zero and preserve the previous current catalog/JSON/plot and build data.
- A5 (verifies R5): the complete bootstrap/delta/revision/timestamp/publication/idempotency/inventory scenario passes offline.
- A6 (verifies R6): README documents the daily scheduler example and no scheduled GitHub Actions data-ingestion workflow exists.

## Definition Of MVP Complete

The MVP is complete only when PR-01 through PR-22 are merged and all of the following are true:

- an empty lake can bootstrap every available initial source series to the maximum history exposed by its configured open/public provider;
- subsequent source runs request/refetch only the required correction/delta scope allowed by the provider and remain duplicate-safe/restart-safe;
- upstream source-window truncation never deletes older locally retained history;
- Bronze, Silver, Gold data, state, and catalogs use the documented Polars/Parquet contracts;
- Silver remains daily long-form with `observation_date: Date`;
- Gold uses **only** `timestamp_m1: Datetime(time_unit="us", time_zone="UTC")` as its temporal key and converts source dates to UTC midnight;
- Gold contains reusable causal market-state features only and no regime/model/portfolio decisions;
- each successful Gold build is an immutable bundle containing `data.parquet`, deterministic `manifest.json`, and `feature_profile.png`;
- root `manifest.parquet`, `manifest.json`, and `feature_profile.png` are published consistently, with root `manifest.parquet` as the authoritative commit point/current-selection catalog;
- consumers can select current/compatible builds without inspecting filesystem recency;
- Gold retention keeps the configured number of complete build bundles per semantic version pair without deleting current;
- `run-daily` can be scheduled once per day and fails safely without publishing partial Gold state;
- `README.md`, `ARCHITECTURE.md`, and this backlog remain synchronized with the implemented contracts.