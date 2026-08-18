# MARKET-REGIME-LOADER

Reusable daily market-regime data loader for quantitative research and portfolio systems.

The repository downloads the maximum history available from configured open/public market-data sources, stores that history in a deterministic Parquet lake, and then performs restart-safe daily delta updates through the current date. Data processing is Polars-first and follows a Bronze -> Silver -> Gold medallion architecture.

## Purpose

`market-regime-loader` is a shared data layer. It provides clean, reusable market-state inputs and causal derived features for downstream projects such as portfolio optimizers, regime classifiers, backtests, or trading systems.

This repository does **not** own portfolio construction, HMM state assignment, `risk_on` / `risk_off` labels, trading signals, targets, or strategy decisions.

```text
Public/Open Sources
       |
       v
     Bronze
 provider-shaped history
       |
       v
     Silver
 canonical daily series
       |
       v
      Gold
 causal reusable features
       |
       +--------------------+--------------------+
       |                    |                    |
       v                    v                    v
   portfell          regime models       future consumers
```

## Core Guarantees

- Maximum available public history is fetched on first bootstrap.
- Subsequent runs fetch only the missing/revisable delta where the provider supports bounded date queries.
- Incremental ingestion uses a configurable overlap window so recent upstream corrections can replace stored values safely.
- Full-file providers may be re-downloaded, but only changed or missing observations are merged into the lake.
- Older locally retained history is never deleted merely because an upstream free source later exposes a shorter range.
- Writes are deterministic, idempotent, duplicate-safe, restart-safe, and limited to affected monthly Bronze/Silver partitions.
- Production dataframe operations use Polars, not pandas.
- Parquet is the durable tabular storage format.
- Gold features are causal: a feature for date `t` may only use information dated `<= t`.
- Every published Gold dataset is an immutable version identified by `build_id`.
- Consumers resolve Gold through the dataset-local `manifest.parquet`; they never infer the current build from directory ordering or file modification time.
- A failed Gold build never replaces the previous current build.

## Initial Series Catalog

| Canonical ID | Primary source | Market information |
|---|---|---|
| `vix` | CBOE | S&P 500 implied volatility |
| `vix9d` | CBOE | short-horizon S&P 500 implied volatility |
| `vix3m` | CBOE | 3-month S&P 500 implied volatility |
| `vix6m` | CBOE | 6-month S&P 500 implied volatility |
| `vix1y` | CBOE | 1-year S&P 500 implied volatility |
| `vstoxx` | STOXX | Euro-area equity implied volatility |
| `move` | Yahoo Finance | US Treasury implied volatility |
| `ciss` | ECB | euro-area systemic financial stress |
| `estr` | ECB | euro short-term rate |
| `euro_hy_oas` | FRED | euro high-yield credit spread |
| `us_2y` | FRED | US 2-year Treasury yield |
| `us_10y` | FRED | US 10-year Treasury yield |
| `usd_broad` | FRED | broad US-dollar index |

The initial implementation is intentionally limited to this catalog. Additional series require an explicit backlog PR and corresponding contract/documentation updates.

## Medallion Lake

The physical lake is optimized for low-frequency daily data. Bronze and Silver use monthly Parquet partitions to avoid the small-file problem. Gold is smaller and is published as immutable full-dataset snapshots.

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

### Bronze

Bronze keeps provider-shaped observations plus ingestion metadata. It may normalize names and physical types, but it must not create regime features or model outputs.

Common identity:

```text
(provider, series_id, observation_date)
```

### Silver

Silver exposes all providers through one canonical daily contract:

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

For OHLC sources, `value == close`. For scalar sources, `value` contains the observation and OHLC fields are null.

Canonical identity:

```text
(series_id, observation_date)
```

### Gold

Gold contains reusable, causal market-state features, including planned families such as:

- volatility levels and trailing changes;
- VIX term-structure ratios and slopes;
- trailing standardized VSTOXX and MOVE levels;
- CISS changes;
- euro high-yield OAS changes;
- US 10Y minus US 2Y yield-curve slope;
- Treasury-yield trailing changes;
- euro short-rate level;
- broad USD trailing changes.

Gold does not assign regimes or portfolio actions.

## Published Gold Contract

A successful Gold build is stored at:

```text
lake/gold/
└── dataset=regime_features_daily/
    ├── versions/
    │   └── build_id=<YYYYMMDDTHHMMSSZ>/
    │       └── data.parquet
    └── manifest.parquet
```

Completed build directories are immutable. A later run creates a new build directory; it does not modify the previously published Gold snapshot.

The dataset-local `manifest.parquet` is the authoritative publication catalog. Planned fields include:

```text
dataset_id
build_id
status                # building | complete | failed
current
started_at_utc
completed_at_utc
schema_version
feature_version
min_date
max_date
row_count
data_path
```

Publication rules:

- only `status=complete` may have `current=true`;
- after the first successful publication, exactly one retained build is current;
- the previous current build remains current until a new build has been fully written and validated;
- a failed or incomplete build never becomes current;
- consumers must not select `max(build_id)` or the newest file by mtime as a substitute for manifest resolution.

### Consumer resolution

A downstream consumer such as `portfell` should resolve Gold as follows:

1. read `manifest.parquet`;
2. prefer the row where `status=complete` and `current=true` if its `schema_version` and `feature_version` are supported;
3. if the current build is incompatible, choose the newest compatible `complete` row with a non-null `data_path`, ordered by `completed_at_utc DESC, build_id DESC`;
4. read only the selected row's `data_path`;
5. never select `building` or `failed` rows.

This permits controlled consumer upgrades and rollback without coupling consumers to the loader's filesystem discovery logic.

### Retention

The planned default retention policy keeps five successful physical builds **including the current build** for each `(schema_version, feature_version)` pair. The current build is never pruned. Historical manifest rows remain as audit metadata even when an older physical build is pruned.

## Bootstrap And Daily Delta Behavior

For every registered series:

```text
No Bronze history
      |
      v
bootstrap maximum available history
      |
      v
monthly Bronze Parquet

Existing Bronze history
      |
      v
latest stored observation date
      |
      v
latest date - correction overlap
      |
      v
fetch through injected current date
      |
      v
upsert changed/new observations only
```

The default planned correction overlap is seven calendar days. Provider capability is explicit: a provider is either range-query capable or a compact full-file source. The logical result must remain idempotent in both cases.

The planned daily pipeline publishes Gold only after Bronze/Silver processing, Gold assembly, immutable version write, and validation succeed. The final manifest switch is the publication boundary.

## Planned Repository Structure

The implementation follows the same narrow dependency principle used in `crypto-history-loader`, adapted to daily macro/volatility data:

```text
api/                 CLI parsing and command output
application/         use cases, registry, contracts, planning, policies
ingestion/           HTTP adapters, provider parsing, Parquet lake IO
scripts/             operational entrypoints
lake/                ignored local Bronze/Silver/Gold/state/manifests
tests/               unit, contract, regression, integration tests
BACKLOG.md            authoritative atomic PR plan
ARCHITECTURE.md       durable architecture sidecar
README.md             durable repository/operator sidecar
```

See `ARCHITECTURE.md` for layer ownership and invariants and `BACKLOG.md` for the atomic implementation sequence.

## Documentation Sidecar Contract

`README.md` and `ARCHITECTURE.md` are **durable sidecars of the implementation** and must remain synchronized with the code and backlog.

A PR is incomplete if it changes any of the following without updating the applicable sidecar content in the same PR:

- repository scope or supported series;
- provider/source ownership;
- medallion semantics or physical lake paths;
- Bronze, Silver, Gold, state, or manifest contracts;
- Gold build versioning, publication, compatibility, or retention behavior;
- bootstrap/delta/revision behavior;
- package boundaries or dependency direction;
- CLI/runtime behavior documented for operators;
- deterministic, idempotency, causality, or missing-data rules.

`BACKLOG.md` remains the delivery/ticket source of truth. `ARCHITECTURE.md` remains the architecture contract. `README.md` remains the concise consumer/operator entry point. None of these documents may intentionally describe behavior that differs from `main`.

## Current Status

The repository is currently at the architecture/backlog stage. `BACKLOG.md` defines the atomic implementation sequence for two parallel weak agents. Production loaders, Gold publication, and CLI commands should only be documented as executable after their implementing PRs are merged into `main`.

## Design Reference

The medallion and lake-boundary approach is derived from `SergejSchweizer/crypto-history-loader`, but this repository intentionally uses a simpler daily-series model and monthly Bronze/Silver partitions rather than copying minute/tick-specific complexity. Gold uses immutable build snapshots plus a dataset-local manifest because it is the stable consumer-facing interface.
