# Backlog

This backlog is the implementation source of truth for `market-regime-loader`.

The repository loads reusable daily market-regime inputs from open/public sources, stores the maximum history available from each source, and then performs restart-safe daily incremental updates through the current date. Data is managed with Polars and Parquet using a Bronze -> Silver -> Gold medallion layout.

Last updated: 2026-08-18

## Delivery Policy

- One `PR-XX` entry equals one logical pull request.
- PRs must stay small enough for weak coding agents: one infrastructure boundary, one provider family, one transformation boundary, or one operational feature per PR.
- Every PR contains separate `Status`, `Updated`, `PR`, `Branch`, `Agent lane`, `Depends on`, and `Commit` fields.
- Valid statuses are `Planned`, `In Progress`, `Blocked`, `Ready`, and `Merged`.
- Every `Description` item has an ID `R1`, `R2`, ... and every `Acceptance` item has the matching ID `A1`, `A2`, .... `A1` verifies only `R1`, `A2` verifies only `R2`, etc.
- Description and Acceptance must have exactly the same number of numbered items.
- No PR may silently add a second responsibility beyond its numbered requirements.
- Unit tests must not call external services. Provider tests use committed small fixtures or mocked HTTP responses.
- Network integration tests, when added, must be explicitly marked and excluded from the default test command.
- Production data under `lake/` must be ignored by Git and must never be committed.
- Polars is the dataframe engine. Do not introduce pandas into production code.
- Parquet is the durable tabular storage format for Bronze, Silver, Gold, state, manifests, and inventories unless a later ADR explicitly changes the contract.
- Writes must be deterministic, idempotent, duplicate-safe, and restart-safe.
- Dates are stored as `Date`; timestamps are stored as timezone-aware UTC timestamps.
- Missing observations are never synthesized in Bronze or Silver.
- Gold features must be causal: a feature for date `t` may use observations dated `<= t` only.
- Provider limitations must be explicit. "Maximum history" means the maximum history made available by the selected open/public source, not paid history that the source no longer exposes.

## Parallel-Agent Rules

Two weak agents are expected to work in parallel.

- **Agent A lane:** lake contracts, CBOE/STOXX/Yahoo volatility sources, Silver normalization, volatility Gold features.
- **Agent B lane:** Parquet IO, ECB/FRED macro sources, coverage/inventory, macro Gold features.
- A PR may start only after every item in its `Depends on` field is merged.
- Independent lane PRs should branch from the same dependency-complete `main` and may proceed in parallel.
- If another PR modifies the same file, the later PR must rebase on current `main` before implementation; weak agents must not resolve broad semantic conflicts by guessing.

## Repository Scope

### Initial series catalog

| Canonical series ID | Primary source | Source series / file | Native shape | Maximum open history policy |
|---|---|---|---|---|
| `vix` | CBOE | `VIX_History.csv` | OHLC daily | Fetch complete CBOE history |
| `vix9d` | CBOE | `VIX9D_History.csv` | OHLC daily | Fetch complete CBOE history |
| `vix3m` | CBOE | `VIX3M_History.csv` | OHLC daily | Fetch complete CBOE history when public file is available |
| `vix6m` | CBOE | `VIX6M_History.csv` | OHLC daily | Fetch complete CBOE history when public file is available |
| `vix1y` | CBOE | `VIX1Y_History.csv` | OHLC daily | Fetch complete CBOE history when public file is available |
| `vstoxx` | STOXX | VSTOXX / `V2TX` historical data | scalar or provider-native daily | Fetch complete public STOXX history |
| `move` | Yahoo Finance | `^MOVE` | OHLC daily | Request `period=max` on bootstrap |
| `ciss` | ECB Data Portal | `CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX` | scalar daily | Fetch complete ECB series history |
| `estr` | ECB Data Portal | `EST.B.EU000A2X2A25.WT` | scalar business-day | Fetch complete ECB series history |
| `euro_hy_oas` | FRED | `BAMLHE00EHYIOAS` | scalar daily close | Fetch all observations currently exposed by FRED; retain older locally stored history if FRED later truncates it |
| `us_2y` | FRED | `DGS2` | scalar daily | Fetch complete FRED series history |
| `us_10y` | FRED | `DGS10` | scalar daily | Fetch complete FRED series history |
| `usd_broad` | FRED | `DTWEXBGS` | scalar daily | Fetch complete FRED series history |

No additional series belongs in the initial implementation unless it receives a separate backlog PR.

## Medallion Storage Contract

The crypto loader is the design reference, but this repository must adapt the physical layout to low-frequency daily data.

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
      year=<YYYY>/
        month=<MM>/
          data.parquet

  state/
    ingestion_state.parquet

  manifests/
    ingestion_runs.parquet
    dataset_inventory.parquet
```

Monthly partitions are intentional. Unlike minute/tick crypto history, these daily series are too small for one-Parquet-file-per-day storage.

### Bronze contract

Bronze preserves provider-native observations plus ingestion metadata. It may normalize column names and types but must not calculate regime features.

Required common columns:

```text
series_id: String
provider: String
observation_date: Date
fetched_at_utc: Datetime[UTC]
source_id: String
source_url: String
```

Provider-native value columns are retained. OHLC sources use `open`, `high`, `low`, `close`; scalar sources use `value`.

Natural key:

```text
(provider, series_id, observation_date)
```

### Silver contract

Silver exposes one canonical daily schema:

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

For OHLC sources, `value == close`. For scalar sources, `value` is the provider observation and OHLC columns are null.

Natural key:

```text
(series_id, observation_date)
```

### Gold contract

Gold is a reusable market-state feature dataset, not a regime classifier and not a portfolio allocation model.

Initial Gold feature families:

```text
volatility levels and trailing changes
VIX term-structure ratios/slopes
MOVE and VSTOXX trailing standardized levels
CISS trailing changes
Euro HY OAS trailing changes
US 10Y - US 2Y curve slope
US yield trailing changes
EUR short-rate level
USD broad-index trailing change
```

Gold must not create `risk_on`, `risk_off`, HMM states, portfolio weights, trading signals, labels, or targets.

## Incremental Update Contract

For each series:

1. If no Bronze observations exist, run bootstrap mode and request the maximum history exposed by the provider.
2. If Bronze observations exist, read the latest stored `observation_date` and request only the remaining provider range where the upstream API supports date ranges.
3. Use a configurable default overlap of 7 calendar days on incremental requests so source corrections can replace recent observations safely.
4. For sources that expose only a complete historical file, re-download that authoritative file but merge/write only changed or missing observations.
5. Never delete older locally stored observations solely because an upstream open source later exposes a shorter history.
6. Upsert by the Bronze natural key and rewrite only affected monthly partitions.
7. Persist last successful run metadata in `lake/state/ingestion_state.parquet`.
8. A rerun with unchanged upstream data must leave logical lake contents unchanged.

## PR Graph

```text
PR-01 repository bootstrap
  |\
  | +--> PR-03 parquet lake IO ------------------+
  +----> PR-02 dataset + path contracts ---------+
                                                  |
                                              PR-04 delta planner
                                              /             \
                     Agent A volatility lane /               \ Agent B macro lane
                                           /                   \
                               PR-05 CBOE                  PR-08 ECB
                                   |                          |
                               PR-06 STOXX                PR-09 FRED
                                   |                          |
                               PR-07 Yahoo                PR-10 coverage
                                           \              /
                                            PR-11 Bronze orchestration
                                             /          \
                                      PR-12 Silver    PR-13 inventory CLI
                                           |
                           +---------------+---------------+
                           |                               |
                 PR-14 volatility Gold             PR-15 macro Gold
                           \                               /
                            +---------- PR-16 ------------+
                                      daily pipeline
```

---

## PR-01: Bootstrap Python Repository And Quality Gates

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr01-repository-bootstrap`

Agent lane: Foundation; assign one agent only

Depends on: none

Commit: `chore: bootstrap market regime loader`

Description:
- R1: Create a `uv`/`pyproject.toml` Python project using Python >=3.13 with runtime dependencies `polars`, `pyarrow`, `httpx`, `pydantic`, and `PyYAML`, plus development dependencies `pytest`, `pytest-cov`, `ruff`, and `mypy`.
- R2: Create package roots `application/`, `ingestion/`, `api/`, `scripts/`, and `tests/`, each with only the minimal files required for imports and future work.
- R3: Add `.gitignore` rules that ignore `.venv/`, Python caches, test caches, coverage outputs, and the entire `lake/` directory.
- R4: Add `Makefile` targets `format-check`, `lint`, `typecheck`, `test`, and `check`, where `check` runs all four validation classes without downloading market data.
- R5: Add a minimal `README.md` that states the repository purpose, Polars/Parquet constraint, Bronze/Silver/Gold layout, and that the loader is reusable by multiple consumer projects.

Acceptance:
- A1 (verifies R1): `uv sync --extra dev` resolves an environment containing exactly the stated runtime/tooling families and no pandas production dependency.
- A2 (verifies R2): imports from `application`, `ingestion`, and `api` succeed and the five required top-level code/test directories exist.
- A3 (verifies R3): `lake/` and the listed local/cache artifacts are ignored by Git and no lake data is tracked.
- A4 (verifies R4): `make check` executes formatting check, lint, mypy, and pytest without any network call.
- A5 (verifies R5): README contains the stated purpose, engine/storage constraints, medallion layers, and multi-project reuse statement.

## PR-02: Define Series Registry And Medallion Path Contracts

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr02-series-registry-paths`

Agent lane: Agent A

Depends on: PR-01

Commit: `feat: define series and lake contracts`

Description:
- R1: Add a typed immutable registry containing exactly the 13 initial canonical series IDs from this backlog with provider, source ID/file, unit, native shape (`ohlc` or `scalar`), frequency, and bootstrap strategy.
- R2: Add typed helpers that return Bronze, Silver, Gold, state, and manifest paths using the exact monthly partition layout documented in this backlog.
- R3: Add validation that rejects duplicate canonical series IDs, unsupported native shapes, empty source IDs, and unknown providers at application startup.
- R4: Add focused tests covering every registered series and exact example partition paths for `2026-08-18`.

Acceptance:
- A1 (verifies R1): the registry contains exactly the 13 documented series and exposes all stated metadata fields with no additional series.
- A2 (verifies R2): path helpers produce the documented `provider=.../series=.../year=YYYY/month=MM/data.parquet` Bronze layout and corresponding Silver/Gold/state/manifest paths.
- A3 (verifies R3): invalid duplicate IDs, native shapes, source IDs, and providers fail deterministically before ingestion begins.
- A4 (verifies R4): tests assert the complete registry inventory and exact path strings for a fixed 2026-08-18 date.

## PR-03: Implement Polars Parquet Lake Merge And Read Utilities

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr03-polars-parquet-lake-io`

Agent lane: Agent B

Depends on: PR-01

Commit: `feat: add polars parquet lake io`

Description:
- R1: Implement Polars-only helpers to read zero, one, or many monthly Parquet partitions into deterministic sorted DataFrames without importing pandas.
- R2: Implement atomic monthly-partition writes using a temporary file followed by replace, with Parquet output produced from Polars.
- R3: Implement merge/upsert by caller-supplied natural-key columns so new rows replace equal-key old rows, duplicates are removed, and output ordering is deterministic.
- R4: Ensure one write call rewrites only months represented by changed input rows and does not rewrite unrelated monthly partitions.
- R5: Add tests for empty reads, multi-month reads, idempotent re-write, replacement of a revised row, duplicate removal, deterministic ordering, and unaffected-month preservation.

Acceptance:
- A1 (verifies R1): tests load empty/single/multi-partition lakes through Polars and production code contains no pandas import.
- A2 (verifies R2): a test proves successful writes leave one valid destination Parquet file and no temporary file; simulated failure does not corrupt the previous destination.
- A3 (verifies R3): repeated identical input yields identical logical rows, and a revised equal-key row replaces the old value exactly once.
- A4 (verifies R4): a test records an unrelated month before an update and proves its file content is not rewritten by another month's change.
- A5 (verifies R5): all listed lake read/write/merge cases have focused passing tests.

## PR-04: Implement Bootstrap And Incremental Range Planner

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr04-incremental-range-planner`

Agent lane: Foundation; assign the first free agent

Depends on: PR-02, PR-03

Commit: `feat: add incremental ingestion planner`

Description:
- R1: Implement a pure planner that returns `bootstrap` when a series has no Bronze observations and `incremental` when a latest stored date exists.
- R2: In incremental mode calculate `start_date = latest_stored_date - 7 calendar days` by default and `end_date = injected_today`, with the overlap configurable and never negative.
- R3: Represent provider capability explicitly as `date_range` or `full_file`; the planner must preserve the same logical update range while allowing full-file providers to refetch their compact source.
- R4: Add an ingestion-state Parquet contract keyed by `(provider, series_id)` with last success timestamp, last observed date, last requested start/end, mode, and row counts.
- R5: Add tests using injected dates only; no test may depend on wall-clock `today()`.

Acceptance:
- A1 (verifies R1): no-history input produces a deterministic bootstrap plan and existing-history input produces a deterministic incremental plan.
- A2 (verifies R2): fixed-date tests prove the exact 7-day overlap calculation, custom overlap behavior, and injected end date.
- A3 (verifies R3): tests prove `date_range` and `full_file` providers receive different fetch instructions but the same logical target range.
- A4 (verifies R4): state rows round-trip through Parquet and one provider/series key has exactly one current state row after upsert.
- A5 (verifies R5): the planner test suite passes with no wall-clock or network dependency.

## PR-05: Add CBOE Volatility-Index Provider

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr05-cboe-volatility-provider`

Agent lane: Agent A

Depends on: PR-04

Commit: `feat: ingest cboe volatility indices`

Description:
- R1: Implement one CBOE CSV adapter for the registry series `vix`, `vix9d`, `vix3m`, `vix6m`, and `vix1y`, using the public CBOE daily-history CSV family and treating it as a `full_file` provider.
- R2: Parse provider dates and OHLC values with Polars into the Bronze common metadata plus `open`, `high`, `low`, and `close`, rejecting rows without a valid date or close.
- R3: Preserve all locally stored older rows when a later CBOE response begins after the current Bronze minimum date, and upsert only matching/new natural keys.
- R4: Fail a single unsupported/unavailable CBOE series explicitly with its canonical series ID; do not silently substitute Yahoo or another provider in this PR.
- R5: Add provider fixtures and tests for valid OHLC parsing, duplicate-date deduplication, an upstream revised close, a truncated upstream history response, and an unavailable series response.

Acceptance:
- A1 (verifies R1): all five documented CBOE registry entries are handled by one adapter and plans identify CBOE as `full_file`.
- A2 (verifies R2): fixture rows become typed Bronze rows with exact common metadata/OHLC columns and invalid date/close rows are rejected.
- A3 (verifies R3): a truncated fixture cannot delete older pre-existing Bronze history and a revised equal-key row replaces only that observation.
- A4 (verifies R4): unavailable-series tests raise an error naming the canonical series and no fallback provider is called.
- A5 (verifies R5): all five listed CBOE behaviors are covered by passing offline tests.

## PR-06: Add STOXX VSTOXX Provider

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr06-stoxx-vstoxx-provider`

Agent lane: Agent A

Depends on: PR-05

Commit: `feat: ingest vstoxx history`

Description:
- R1: Implement a STOXX adapter for canonical series `vstoxx` using the public VSTOXX `V2TX` historical-data resource and maximum-history bootstrap behavior.
- R2: Parse the provider response with Polars into Bronze common metadata and either a scalar `value` or provider-native OHLC fields according to the actual public file schema, while keeping `source_id=V2TX` stable.
- R3: Treat the STOXX history resource as `full_file` unless its public endpoint explicitly supports bounded date queries; merge locally without deleting older stored rows.
- R4: Add a fixture representing the real STOXX header/date/value shape and tests for bootstrap parsing, a revised observation, and truncated-response preservation.

Acceptance:
- A1 (verifies R1): `vstoxx` bootstrap loads all rows supplied by the STOXX fixture and the adapter is registered only for `vstoxx`.
- A2 (verifies R2): fixture output contains the Bronze common metadata, stable `source_id=V2TX`, and correctly typed provider value fields matching the fixture schema.
- A3 (verifies R3): the provider capability is deterministic and a shorter later response cannot remove older Bronze rows.
- A4 (verifies R4): the three stated STOXX behaviors are covered by passing offline tests using a representative committed fixture.

## PR-07: Add Yahoo MOVE Provider

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr07-yahoo-move-provider`

Agent lane: Agent A

Depends on: PR-06

Commit: `feat: ingest move index history`

Description:
- R1: Implement a Yahoo Finance adapter only for canonical series `move` and Yahoo ticker `^MOVE`; no other Yahoo ticker is added in this PR.
- R2: Bootstrap with maximum available daily history and incremental fetches with the planner's bounded start/end range, using a library/client boundary that is mockable in tests.
- R3: Normalize Yahoo daily OHLC observations into Bronze common metadata and OHLC columns, ignoring dividends/splits/volume fields that are not part of the Bronze contract.
- R4: Add tests for maximum-history request arguments, incremental request arguments, empty-result handling, revised-date upsert input, and OHLC normalization.

Acceptance:
- A1 (verifies R1): the Yahoo adapter accepts `move`/`^MOVE` and rejects unrelated canonical series or tickers.
- A2 (verifies R2): mocked calls prove bootstrap requests maximum history and incremental mode passes the exact planner start/end range.
- A3 (verifies R3): normalized fixture output contains only Bronze common metadata plus OHLC market-value columns required by the contract.
- A4 (verifies R4): all five stated Yahoo behaviors have passing offline tests.

## PR-08: Add ECB CISS And ESTR Provider

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr08-ecb-provider`

Agent lane: Agent B

Depends on: PR-04

Commit: `feat: ingest ecb regime series`

Description:
- R1: Implement an ECB SDMX REST adapter for exactly `ciss` (`CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX`) and `estr` (`EST.B.EU000A2X2A25.WT`) using CSV responses.
- R2: Bootstrap by omitting `startPeriod` so the complete ECB-exposed series is requested; incremental mode must pass planner `startPeriod` and `endPeriod` values.
- R3: Parse ECB observation date/value fields with Polars into Bronze scalar rows and reject missing/non-numeric observations while retaining valid business-day gaps as absence, not zeroes.
- R4: Support ECB revisions by allowing overlap rows to replace equal-key existing Bronze rows; do not forward-fill or synthesize weekend/holiday observations.
- R5: Add fixtures/tests for both series, full-history request shape, bounded update request shape, one revised row, and one normal calendar gap.

Acceptance:
- A1 (verifies R1): the adapter accepts exactly the two documented ECB series keys and produces provider `ecb` Bronze rows.
- A2 (verifies R2): mocked request tests prove bootstrap omits `startPeriod` and incremental mode sends exact start/end dates from the planner.
- A3 (verifies R3): fixture values are typed Float64 scalar rows and missing/non-numeric values are excluded without invented observations.
- A4 (verifies R4): a revised overlap row replaces its prior value while weekend/holiday dates remain absent.
- A5 (verifies R5): both series and all stated request/revision/calendar cases are covered offline.

## PR-09: Add FRED Rates, Credit, And Dollar Provider

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr09-fred-provider`

Agent lane: Agent B

Depends on: PR-08

Commit: `feat: ingest fred regime series`

Description:
- R1: Implement one FRED adapter for exactly `DGS2`, `DGS10`, `DTWEXBGS`, and `BAMLHE00EHYIOAS`, mapped to `us_2y`, `us_10y`, `usd_broad`, and `euro_hy_oas`.
- R2: Bootstrap by requesting the full history currently exposed by FRED and incremental mode by requesting the planner start/end date range.
- R3: Parse FRED date/value CSV with Polars, treating `.`/blank observations as missing and never converting them to zero or forward-filled values.
- R4: For `euro_hy_oas`, preserve older local Bronze observations if FRED later exposes only a shorter rolling history; no provider response may truncate the local historical minimum date.
- R5: Add fixtures/tests for all four series, bootstrap and incremental parameters, missing-value parsing, one revised row, and the Euro HY OAS truncated-history case.

Acceptance:
- A1 (verifies R1): only the four documented FRED source IDs map to the four canonical series IDs and each produces provider `fred` Bronze rows.
- A2 (verifies R2): mocked requests prove full-history bootstrap behavior and exact bounded incremental dates.
- A3 (verifies R3): `.`/blank fixture values are absent from Bronze and no zero/forward-filled row is emitted.
- A4 (verifies R4): a shorter Euro HY OAS response leaves older locally stored rows intact while still updating overlapping observations.
- A5 (verifies R5): all four series and every listed behavior have passing offline tests.

## PR-10: Add Bronze Coverage And Run Manifests

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr10-bronze-coverage-manifests`

Agent lane: Agent B

Depends on: PR-09, PR-03

Commit: `feat: add bronze coverage manifests`

Description:
- R1: Add a Polars-built inventory row per canonical series containing provider, minimum observation date, maximum observation date, row count, duplicate-key count, and physical Parquet file count.
- R2: Add an ingestion-run manifest row per provider/series execution containing run ID, mode, requested range, fetched row count, changed row count, written partition count, status, and UTC timestamps.
- R3: Persist inventory and run manifests to the documented Parquet manifest paths using lake merge utilities.
- R4: Do not label weekends/holidays as missing data; the initial inventory reports bounds/duplicates only and makes no calendar-completeness claim.
- R5: Add tests for an empty series, populated series, duplicate detection, successful run manifest, and failed run manifest.

Acceptance:
- A1 (verifies R1): inventory output exposes exactly the six stated coverage fields for every canonical series tested.
- A2 (verifies R2): success/failure manifest fixtures contain every stated execution field with deterministic run identity inputs.
- A3 (verifies R3): inventory/run rows round-trip through Parquet and update without duplicate logical keys.
- A4 (verifies R4): inventory output contains no weekend/holiday missing-day count or synthesized completeness metric.
- A5 (verifies R5): all five stated inventory/manifest cases have passing tests.

## PR-11: Add Registry-Driven Bronze Orchestration

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr11-bronze-orchestration`

Agent lane: Foundation; assign the first free agent

Depends on: PR-05, PR-06, PR-07, PR-08, PR-09, PR-10

Commit: `feat: orchestrate bronze updates`

Description:
- R1: Add an application service that accepts canonical series IDs, builds plans from current Bronze state, calls only the registered provider adapter, and writes through the shared Parquet merge utility.
- R2: Add `bootstrap` behavior that processes all selected series with no prior history and `update` behavior that processes selected series through the incremental planner up to an injected current date.
- R3: Make each series execution isolated: one failed provider/series records a failed manifest and does not corrupt or delete another series' successful output.
- R4: Update ingestion state only after a series write and success manifest complete; failed series retain their previous success state.
- R5: Add tests with fake adapters proving provider routing, bootstrap, incremental update, partial failure isolation, and restart/idempotency.

Acceptance:
- A1 (verifies R1): fake-adapter tests prove each canonical series is routed to its registry provider and all persistence uses the shared lake writer.
- A2 (verifies R2): fixed-date tests prove bootstrap and update select the expected plan for each requested series.
- A3 (verifies R3): one simulated provider failure produces a failure manifest while a second series succeeds and remains readable.
- A4 (verifies R4): simulated failure leaves prior state unchanged, while successful completion advances state only after data/manifest writes.
- A5 (verifies R5): all five stated orchestration behaviors pass with repeated execution producing no duplicate logical rows.

## PR-12: Build Canonical Silver Daily Series

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr12-silver-canonical-series`

Agent lane: Agent A

Depends on: PR-11

Commit: `feat: build canonical silver series`

Description:
- R1: Implement a registry-driven Silver builder that reads all Bronze history for a canonical series and emits the exact Silver schema documented in this backlog.
- R2: For OHLC Bronze sources set Silver `value=close` and preserve typed OHLC fields; for scalar sources set `value` from Bronze `value` and all Silver OHLC fields to null.
- R3: Deduplicate by `(series_id, observation_date)`, sort ascending by observation date, reject non-finite values, and never fill missing dates.
- R4: Rebuild only the selected series but write deterministic monthly Silver partitions using the shared lake IO.
- R5: Add tests covering one OHLC series, one scalar series, deduplication, non-finite rejection, and missing-date preservation.

Acceptance:
- A1 (verifies R1): output columns/types match the documented Silver schema exactly for every fixture.
- A2 (verifies R2): OHLC fixture rows satisfy `value == close`, while scalar fixture rows retain value and null OHLC fields.
- A3 (verifies R3): duplicate dates collapse to one row, non-finite values disappear, output is sorted, and no absent date is invented.
- A4 (verifies R4): selecting one series rewrites only that series' monthly Silver paths with deterministic contents.
- A5 (verifies R5): all five stated transformation behaviors have passing tests.

## PR-13: Add Lake Inventory CLI

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr13-lake-inventory-cli`

Agent lane: Agent B

Depends on: PR-10, PR-11

Commit: `feat: add lake inventory cli`

Description:
- R1: Add a CLI command `inventory` that reads the Parquet inventory and prints one stable row per canonical series with provider, min date, max date, row count, duplicate count, and file count.
- R2: Add CLI filters `--series` and `--provider` that restrict output without mutating the lake.
- R3: Add `--json` output that emits deterministic machine-readable records with the same fields as text output.
- R4: Exit non-zero only for command/config/read errors; a series with zero observations is valid inventory output and must not make the command fail.
- R5: Add parser/output tests for unfiltered, series-filtered, provider-filtered, JSON, and empty-series cases.

Acceptance:
- A1 (verifies R1): fixed inventory fixtures produce stable text rows containing exactly the six stated coverage fields.
- A2 (verifies R2): each filter returns only matching rows and a test proves no lake file changes.
- A3 (verifies R3): JSON records expose the exact same logical fields/values as text output.
- A4 (verifies R4): empty-series inventory exits successfully while simulated config/read failures exit non-zero.
- A5 (verifies R5): all five stated CLI cases have passing tests.

## PR-14: Build Volatility Gold Features

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr14-volatility-gold-features`

Agent lane: Agent A

Depends on: PR-12

Commit: `feat: add volatility regime features`

Description:
- R1: Build causal per-series trailing features for `vix`, `vix9d`, `vix3m`, `vix6m`, `vix1y`, `vstoxx`, and `move`: level, 5-observation change, 20-observation change, and 60-observation trailing z-score using only current/past non-null observations.
- R2: Build VIX term-structure features on dates where required source values coexist: `vix9d_vix_ratio`, `vix_vix3m_ratio`, `vix3m_minus_vix`, `vix6m_minus_vix`, and `vix1y_minus_vix`.
- R3: Preserve nulls until each trailing window has enough observations; do not backfill, forward-fill, or center rolling windows.
- R4: Add tests with hand-calculable short fixtures proving feature formulas, denominator-zero handling, minimum-period nulls, and absence of future leakage.

Acceptance:
- A1 (verifies R1): all seven volatility series expose exactly the four stated causal feature types with expected hand-calculated values.
- A2 (verifies R2): the five documented VIX term features match hand-calculated fixture values and exist only on dates with required inputs.
- A3 (verifies R3): insufficient-history and missing-source dates remain null and tests find no fill operation or centered window behavior.
- A4 (verifies R4): formula, zero-denominator, minimum-period, and no-future-leakage tests all pass.

## PR-15: Build Macro, Credit, Rates, And Dollar Gold Features

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr15-macro-gold-features`

Agent lane: Agent B

Depends on: PR-12

Commit: `feat: add macro regime features`

Description:
- R1: Build `ciss` level plus 5-observation and 20-observation changes, and `euro_hy_oas` level plus 5-observation and 20-observation changes.
- R2: Build `us_2y` and `us_10y` levels, 20-observation changes, and `us_10y_minus_us_2y` on dates where both yields coexist.
- R3: Build `estr` level and 20-observation change, plus `usd_broad` level and 20-observation change.
- R4: Preserve nulls until required observations exist; do not fill absent business dates or use future observations.
- R5: Add hand-calculable tests for all stated feature families, a missing-yield date, minimum-history nulls, and no-future-leakage behavior.

Acceptance:
- A1 (verifies R1): CISS and Euro HY OAS fixtures expose exactly the stated levels and 5/20-observation changes with expected values.
- A2 (verifies R2): yield fixtures expose both levels, both 20-observation changes, and the exact 10Y-minus-2Y spread only when both inputs exist.
- A3 (verifies R3): ESTR and USD broad fixtures expose exactly the stated level/change features with expected values.
- A4 (verifies R4): missing/insufficient-history rows remain null and no forward/back fill or future observation is used.
- A5 (verifies R5): all stated macro feature and leakage tests pass.

## PR-16: Assemble Daily Gold Dataset And Daily Update Command

Status: Planned

Updated: 2026-08-18

PR: none

Branch: `codex/pr16-daily-medallion-pipeline`

Agent lane: Integration; assign one agent only

Depends on: PR-13, PR-14, PR-15

Commit: `feat: add daily medallion pipeline`

Description:
- R1: Assemble `dataset=regime_features_daily` by outer-joining the volatility and macro Gold feature families on `observation_date`, with one sorted row per date and no value imputation.
- R2: Add CLI commands `bootstrap`, `update`, `silver-build`, `gold-build`, and `run-daily`; `run-daily` executes Bronze update -> full deterministic Silver rebuild -> full deterministic Gold rebuild -> inventory refresh.
- R3: Default `bootstrap`, `update`, and `run-daily` to all 13 registry series while supporting repeatable `--series` selection for targeted runs.
- R4: Make `run-daily` return non-zero when any requested Bronze series fails and skip Silver/Gold publication on that failed run so consumers never see a partially refreshed Gold dataset.
- R5: Add an end-to-end offline integration test using fake provider fixtures that performs bootstrap, a next-day delta with one revised observation, repeated idempotent rerun, Silver rebuild, Gold rebuild, and inventory refresh.
- R6: Document a cron/systemd example that runs `run-daily` once per day; do not add a GitHub Actions data-ingestion schedule because the repository lake is not persisted by GitHub Actions.

Acceptance:
- A1 (verifies R1): Gold output has one sorted row per union date, contains both feature families, and retains nulls where a source is absent.
- A2 (verifies R2): all five commands parse and `run-daily` executes the four documented stages in order.
- A3 (verifies R3): default runs target exactly all 13 registry series and repeated `--series` options restrict execution to the requested subset.
- A4 (verifies R4): a simulated Bronze provider failure yields non-zero status and leaves the previously published Silver/Gold artifacts unchanged.
- A5 (verifies R5): the complete stated bootstrap/delta/revision/idempotency/Silver/Gold/inventory scenario passes offline.
- A6 (verifies R6): README documents a once-daily cron/systemd invocation and the repository contains no scheduled GitHub Actions ingestion workflow.

## Definition Of MVP Complete

The MVP is complete only when PR-01 through PR-16 are merged and all of the following are true:

- An empty lake can bootstrap every currently available initial series to the maximum history exposed by its open source.
- A second run downloads/requests the remaining date range where provider APIs support it, uses the overlap policy for corrections, and writes only changed monthly Bronze partitions.
- Full-file providers may refetch their authoritative compact history file, but local writes remain incremental and idempotent.
- Older locally stored data is never removed because an upstream source later truncates its public history.
- Bronze, Silver, Gold, state, manifests, and inventory are all Parquet-backed and manipulated with Polars.
- Silver contains normalized reusable observations, while Gold contains reusable causal market-state features only.
- No HMM, regime classifier, trading signal, portfolio optimizer, or consumer-specific business logic exists in this repository.
- `run-daily` can be scheduled once per day by the deployment environment and fails safely without publishing partially refreshed Silver/Gold output.
