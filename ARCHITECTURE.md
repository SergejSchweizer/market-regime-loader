# Architecture

This document is the durable architecture contract for `market-regime-loader`.

It must remain synchronized with code changes that alter repository scope, supported series, providers, medallion paths, dataset contracts, Gold publication/versioning, runtime/update behavior, package boundaries, or quality guarantees. `README.md` is the concise consumer/operator sidecar; `BACKLOG.md` is the delivery/ticket source of truth.

## System Shape

`market-regime-loader` is a reusable daily market-state data platform. It downloads the maximum open/public history available from each configured provider, normalizes that history into canonical daily series, derives causal market-state features, and keeps the lake current using restart-safe incremental updates.

```text
                        registry / runtime config
                                  |
                                  v
                           api / scripts
                                  |
                                  v
                            application
                  planning / contracts / policies
                                  |
                    +-------------+-------------+
                    |                           |
                    v                           v
             provider adapters              lake IO
              HTTP + parsing          Polars + Parquet merge
                    |                           |
                    +-------------+-------------+
                                  |
                                  v
                  lake/bronze -> lake/silver -> lake/gold
                                                   |
                                                   v
                                      immutable published builds
                                                   |
                                                   v
                                           manifest.parquet
                                                   |
                                                   v
                                      downstream consumers
```

The repository owns data acquisition, normalization, persistence, causal reusable features, coverage metadata, update state, Gold build versioning, and Gold publication metadata. It does not own regime labels, models, strategy decisions, portfolio allocation, or trading execution.

## Dependency Direction

The intended dependency direction is narrow:

```text
api / scripts ----------> application ----------> typed contracts / DTOs
                                |
                                v
                           ingestion ports
                                ^
                                |
ingestion adapters -------------+
```

Rules:

- `api/` may depend on `application/`, but must not directly implement provider HTTP logic or Parquet persistence rules.
- `application/` owns use-case orchestration, registry contracts, planning, policies, Gold publication state transitions, and deterministic business behavior.
- `ingestion/` owns provider adapters, HTTP/parsing details, and physical Parquet lake IO.
- `ingestion/` must not own CLI parsing or portfolio/model behavior.
- Downstream consumer projects must read published dataset contracts rather than import provider internals.
- Consumers must not infer the current Gold build from filesystem ordering or modification timestamps.

If a future change crosses boundaries, define or change the typed contract first, then update the adapter or orchestrator.

## Layer Ownership

| Layer | Owns | Must not own |
|---|---|---|
| `api/` | CLI parsing, command wiring, human/machine output shape | provider HTTP requests, Parquet implementation details, model logic |
| `application/` | series registry, provider capability contracts, bootstrap/delta planning, medallion contracts, Gold build/publication contracts, orchestration, validation, runtime policy | HTTP parsing internals, physical low-level Parquet implementation, trading strategy logic |
| `ingestion/` | source adapters, HTTP behavior, source parsing, Polars/Parquet reads and writes, partition/version paths, manifest/state persistence adapters | CLI behavior, model decisions, portfolio allocation |
| `scripts/` | operational entrypoints and schedulable wrappers | hidden business rules bypassing application contracts |
| `tests/` | contract, unit, regression, integration, architecture validation | production behavior |

## Initial Series Registry

The first implementation contains exactly these canonical series:

```text
vix
vix9d
vix3m
vix6m
vix1y
vstoxx
move
ciss
estr
euro_hy_oas
us_2y
us_10y
usd_broad
```

Provider ownership:

```text
CBOE         -> vix, vix9d, vix3m, vix6m, vix1y
STOXX        -> vstoxx
Yahoo        -> move
ECB          -> ciss, estr
FRED         -> euro_hy_oas, us_2y, us_10y, usd_broad
```

Every registry entry must declare at least:

```text
series_id
provider
source_id_or_file
unit
native_shape        # ohlc | scalar
frequency
bootstrap_strategy
provider_capability # date_range | full_file
```

No unregistered series may be ingested or published.

## Medallion Data Flow

```text
Bronze
  provider-shaped observations
  ingestion metadata
  deterministic monthly partitions
  idempotent natural-key upserts
             |
             v
Silver
  canonical daily schema
  canonical series identity
  validated types and units
  no synthetic observations
             |
             v
Gold logical frame
  reusable causal market-state features
  trailing transformations only
  no labels, no strategies, no portfolio decisions
             |
             v
Gold publication
  immutable build_id snapshot
  manifest-governed current selection
```

### Bronze

Bronze preserves source observations for auditability. Column names and types may be normalized, but source values must not be converted into strategy-specific features.

Required common fields:

```text
series_id: String
provider: String
observation_date: Date
fetched_at_utc: Datetime[UTC]
source_id: String
source_url: String
```

Native fields:

- OHLC providers retain `open`, `high`, `low`, `close`.
- Scalar providers retain `value`.

Natural key:

```text
(provider, series_id, observation_date)
```

Bronze rules:

- never synthesize missing market observations;
- never delete old locally retained rows only because a public upstream window later shrinks;
- recent revised upstream observations may replace equal-key rows;
- affected monthly partitions only are rewritten.

### Silver

Silver exposes one canonical daily contract independent of provider shape:

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

Rules:

- OHLC series use `value == close`.
- Scalar series use the source observation as `value`; OHLC fields remain null.
- Natural key is `(series_id, observation_date)`.
- Duplicate keys are invalid after canonicalization.
- Missing dates remain absent/null; Silver does not fabricate market observations to force a daily grid.
- Transformations must be deterministic for identical Bronze input.

### Gold logical dataset

Gold publishes reusable daily market-state features under logical dataset ID:

```text
regime_features_daily
```

Planned initial feature families:

- volatility levels and trailing changes;
- VIX term-structure ratios and slopes;
- trailing standardized VSTOXX and MOVE levels;
- CISS trailing changes;
- euro high-yield OAS trailing changes;
- US 10Y minus US 2Y curve slope;
- Treasury-yield trailing changes;
- euro short-rate level;
- broad USD trailing changes.

Causality rule:

```text
feature(date=t) may use observations dated <= t only
```

Gold must not publish:

```text
risk_on
risk_off
HMM state IDs
regime class labels
portfolio weights
buy/sell signals
prediction targets
forward-looking labels
```

Those belong to downstream modelling/portfolio repositories.

## Physical Lake Layout

Daily macro/index source series are stored in monthly Parquet partitions. Gold is small enough that each published build is a complete immutable snapshot stored as one Parquet file.

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
        build_id=20260817T020000Z/
          data.parquet
        build_id=20260818T020000Z/
          data.parquet
        build_id=20260819T020000Z/
          data.parquet
      manifest.parquet

  state/
    ingestion_state.parquet

  manifests/
    ingestion_runs.parquet
    dataset_inventory.parquet
```

The lake is a runtime artifact and must be ignored by Git.

`lake/manifests/*` contains operational ingestion/inventory metadata. `lake/gold/dataset=regime_features_daily/manifest.parquet` is different: it is the dataset-local Gold publication catalog and is part of the consumer-facing Gold contract.

## Parquet And Polars Contract

Production dataframe behavior is Polars-first.

- pandas must not be introduced into production ingestion/transformation code.
- Parquet is the durable tabular storage format for Bronze, Silver, Gold, state, manifests, and inventory outputs unless a future explicit architecture decision changes the contract.
- Reads across multiple Bronze/Silver monthly partitions must return deterministic ordering.
- Bronze/Silver writes must be atomic at monthly-file granularity: write a temporary file, then replace the destination.
- Bronze/Silver upserts use explicit natural keys and deterministic new-row precedence.
- A logical no-op source rerun must not create duplicate observations.
- Only Bronze/Silver monthly partitions containing changed/new rows may be rewritten.
- Gold builds are immutable snapshots; completed version files are never updated in place.
- Gold manifest replacement must be atomic.

## Gold Build Identity

Every Gold publication attempt has a build ID with exact UTC-sortable format:

```text
YYYYMMDDTHHMMSSZ
```

Example:

```text
20260818T020000Z
```

The build ID is an identity, not the authority for current selection. A lexicographically later build may be failed, incompatible, or not current.

A completed build artifact lives at:

```text
lake/gold/dataset=regime_features_daily/
  versions/build_id=<build_id>/data.parquet
```

Completed build paths are immutable. Reusing an existing completed build ID is an error.

## Gold Manifest Contract

The authoritative publication catalog lives only at:

```text
lake/gold/dataset=regime_features_daily/manifest.parquet
```

It contains one row per attempted build with the following minimum contract:

```text
dataset_id: String
build_id: String
status: String              # building | complete | failed
current: Boolean
started_at_utc: Datetime[UTC]
completed_at_utc: Datetime[UTC] nullable
schema_version: Int64
feature_version: Int64
min_date: Date nullable
max_date: Date nullable
row_count: Int64 nullable
data_path: String nullable
```

Manifest invariants:

- `build_id` is unique within the dataset manifest.
- `status` is one of `building`, `complete`, `failed`.
- only `complete` rows may have `current=true`.
- before the first successful publication, zero rows may be current.
- after a successful publication, exactly one physically retained complete build is current.
- a selectable complete build must have non-null `data_path` pointing to its immutable snapshot.
- `manifest.parquet` ordering is deterministic by `started_at_utc`, then `build_id`.

## Gold Publication State Machine

The publication boundary is the final atomic manifest switch, not creation of a file under `versions/`.

```text
new build requested
      |
      v
manifest: building, current=false
      |
      v
write immutable version data.parquet
      |
      v
validate schema / uniqueness / coverage / row count
      |
      +---------------- failure ----------------+
      |                                         |
      v                                         v
atomic manifest switch                     manifest failed
new = complete,current=true                current=false
old = complete,current=false               old current unchanged
```

Rules:

1. The previous current build remains current while a new build is being created.
2. A new build may become current only after its Parquet artifact is durably written and validated.
3. Promotion and demotion of current rows occur in one atomic manifest replacement.
4. Any failure before that switch leaves the previous current build authoritative.
5. A consumer never needs to inspect an incomplete version directory to decide what is published.

## Downstream Consumer Resolution

Downstream systems such as `portfell` consume the manifest contract, not loader internals.

Resolution algorithm:

```text
1. Read manifest.parquet.
2. Find status=complete AND current=true.
3. If that row's schema_version and feature_version are supported and data_path is non-null, use it.
4. Otherwise select the newest compatible status=complete row with non-null data_path,
   ordered by completed_at_utc DESC, build_id DESC.
5. Read exactly that row's data_path.
6. Never select building or failed rows.
```

This allows a consumer to continue on a previous compatible Gold build during a schema/feature migration without guessing from filenames.

The manifest contract is intentionally data-oriented so consumers do not need to import the `market-regime-loader` Python package.

## Gold Retention

Planned default:

```text
gold_retention_successful_builds = 5
```

The value means five physically retained `complete` builds **including the current build** for each `(schema_version, feature_version)` pair.

Retention rules:

- never prune the current build;
- `building` and `failed` attempts do not count toward the successful-build limit;
- retention is evaluated separately for each semantic `(schema_version, feature_version)` pair;
- oldest eligible non-current complete builds are pruned first by `completed_at_utc`, then `build_id`;
- manifest audit rows remain after physical pruning, but `data_path` becomes null and the row is therefore not selectable;
- retention runs only after a successful publication.

## Bootstrap And Incremental Update Semantics

For each series, planning depends only on durable lake state and an injected current date.

### Bootstrap

When no Bronze observations exist:

```text
mode = bootstrap
request = maximum open/public history exposed by provider
```

"Maximum history" means the maximum history available from the configured open/public source. Paid history that the provider does not expose is outside the repository contract.

### Incremental

When Bronze history exists:

```text
latest = latest stored observation_date
start  = latest - overlap_days
end    = injected current date
```

Default overlap:

```text
7 calendar days
```

The overlap exists so provider corrections can safely replace recent data.

### Provider Capabilities

Providers declare one of two fetch modes:

```text
date_range
full_file
```

`date_range` providers should request only the planned update range.

`full_file` providers may fetch the compact authoritative history file on every update, but merge/write behavior must still limit Bronze changes to missing/revised logical observations and affected monthly partitions.

### State

`lake/state/ingestion_state.parquet` is keyed by:

```text
(provider, series_id)
```

Planned state fields include:

```text
last_success_utc
last_observed_date
last_requested_start
last_requested_end
mode
fetched_row_count
written_row_count
```

State is written only after successful durable ingestion.

## Daily Pipeline Publication Order

The planned `run-daily` sequence is:

```text
1. Bronze update
2. deterministic Silver rebuild
3. canonical Gold assembly
4. immutable Gold version write
5. Gold validation
6. atomic Gold manifest publication
7. Gold retention
8. inventory refresh
```

A failure before step 6 must not change the current Gold build. A failure after a successful step 6 may cause maintenance/inventory work to fail, but consumers still have a complete published Gold build.

## Revision And History-Retention Policy

Public sources may revise recent observations or reduce the amount of free history they expose.

Therefore:

1. equal-key revised Bronze observations may replace recent stored values;
2. incremental requests include a correction overlap;
3. a shorter upstream response must never be interpreted as an instruction to delete older locally retained source history;
4. source truncation or missing history must be visible through manifests/inventory rather than silently rewriting the past;
5. future provider migrations must preserve canonical series identity and document lineage changes;
6. Gold build retention is independent of Bronze source-history retention: pruning an old Gold snapshot never removes Bronze/Silver source history needed to rebuild it.

## Missing-Data Policy

The loader distinguishes "provider returned no observation" from "zero".

- Bronze does not synthesize rows.
- Silver does not forward-fill, backward-fill, interpolate, or create artificial zero observations unless a future dataset contract explicitly defines such behavior.
- Gold trailing transformations operate only on information actually available at or before the feature date.
- Cross-series Gold joins must preserve nulls when an input is unavailable rather than borrow future data.
- Any later as-of alignment must be backward-looking and explicitly documented.

## Operational Manifests And Inventory

Operational metadata remains under:

```text
lake/manifests/ingestion_runs.parquet
lake/manifests/dataset_inventory.parquet
```

`ingestion_runs.parquet` records provider/series run-level source and write outcomes.

`dataset_inventory.parquet` provides per-series coverage metadata such as earliest/latest observation, row count, file count, and duplicate information where meaningful.

These operational manifests do not choose the current Gold build. Gold publication state belongs exclusively to the dataset-local Gold `manifest.parquet`.

## Determinism And Idempotency

For identical source observations and configuration:

- the same natural keys must be produced;
- the same canonical values must be produced;
- the same deterministic row order must be produced;
- repeated ingestion must not create duplicate rows;
- repeated Silver/Gold logical builds must not change feature values;
- each successful published Gold run creates a distinct immutable build identity unless the caller intentionally injects an existing ID, which must be rejected;
- current publication changes only through an atomic manifest state transition;
- wall-clock timestamps may appear only in explicit ingestion/build metadata fields, never in market features.

Tests must inject dates/times rather than use uncontrolled `today()` behavior for planning/build-ID logic.

## Runtime Side-Effect Boundaries

Side effects must remain isolated:

```text
HTTP/network                  -> ingestion provider adapters
Bronze/Silver IO             -> ingestion lake adapters
Gold version file IO         -> ingestion Gold storage adapter
state/operational manifest IO-> ingestion persistence adapters
Gold publication state       -> application publication service + manifest persistence port
planning/orchestration        -> application services
CLI output                    -> api commands
scheduled process wiring      -> scripts
```

An application service may call an ingestion port, but business rules must not be hidden inside HTTP or Parquet utility code.

## Test Strategy

Default tests must be offline.

Provider tests use:

- small committed fixtures; or
- mocked HTTP responses.

Default quality checks must not download real market data.

Network integration tests, when introduced, must be explicitly marked and excluded from the default test command.

Important contract tests include:

- exact registry inventory;
- exact Bronze/Silver and versioned Gold paths;
- natural-key deduplication;
- atomic Bronze/Silver writes;
- immutable Gold version writes;
- no-op ingestion idempotency;
- correction replacement;
- unaffected-month preservation;
- bootstrap versus incremental planning;
- provider-capability behavior;
- Bronze-to-Silver canonicalization;
- Gold causality and no-look-ahead behavior;
- Gold canonical assembly/schema validation;
- build-ID validation;
- Gold manifest schema and invariants;
- atomic current-build switching;
- failure preservation of the previous current build;
- current/latest-compatible consumer selection examples;
- Gold retention and current-build protection;
- state/operational-manifest round-trip;
- sidecar documentation consistency where practical.

## Documentation Sidecars

`README.md` and `ARCHITECTURE.md` are treated as implementation sidecars, not optional prose.

### `README.md`

Owns the concise public/operator view:

- repository purpose;
- scope boundaries;
- supported series overview;
- medallion overview;
- lake layout overview;
- Gold publication/consumer-resolution overview;
- bootstrap/delta behavior;
- current executable/operator surface only after implementation exists.

### `ARCHITECTURE.md`

Owns the durable engineering contract:

- package boundaries and dependency direction;
- dataset/medallion semantics;
- natural keys and physical layout;
- Gold build identity, manifest, publication and retention contracts;
- update/revision/missing-data rules;
- determinism, idempotency, and causality constraints;
- side-effect boundaries and test expectations.

### `BACKLOG.md`

Owns delivery state:

- atomic PR tickets;
- dependencies and parallel lanes;
- exact requirement/acceptance pairing;
- branch, commit, status, and merge traceability.

### Synchronization Rule

A change is not complete if `main` contains code or backlog contracts that conflict with these sidecars.

Any PR changing one or more of the following must update the relevant sidecar(s) in the **same PR**:

```text
repository scope
series registry
provider/source mapping
physical lake layout
Bronze/Silver/Gold contracts
Gold build/version/manifest/publication/retention semantics
state/operational manifests
bootstrap/delta semantics
revision behavior
missing-data behavior
feature semantics
package boundaries
runtime/CLI behavior
quality guarantees
```

Documentation-only corrections may update the sidecars without code changes, but they must not invent executable behavior that does not exist on `main`.

## Relationship To crypto-history-loader

`SergejSchweizer/crypto-history-loader` is the design reference for medallion ownership, deterministic Parquet-lake behavior, explicit dataset contracts, restart safety, and narrow package boundaries.

`market-regime-loader` intentionally does **not** copy crypto-specific complexity such as minute/tick grids, exchange instruments, options surfaces, or daily per-tick partitions. This repository operates on low-frequency daily macro/volatility series, uses monthly Bronze/Silver partitions, and publishes compact immutable Gold snapshots through a dataset-local manifest.

## Current Implementation Status

At this stage, architecture and delivery contracts exist before production code. `BACKLOG.md` defines the implementation order. The versioned Gold publication model described here is a planned contract until its corresponding PRs are merged. This file must be updated as planned contracts become implemented or if the architecture changes during delivery.
