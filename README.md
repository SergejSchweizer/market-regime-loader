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
- Gold features are causal: a feature at `timestamp_m1=t` may only use information available on or before `t`.
- Gold uses the same canonical timestamp name and Polars dtype as `crypto-history-loader`: `timestamp_m1: Datetime(time_unit="us", time_zone="UTC")`.
- Daily source observations are normalized to `00:00:00 UTC` of their source calendar date when entering Gold.
- Every published Gold dataset is an immutable version identified by `build_id`.
- Every immutable Gold build includes `data.parquet`, `manifest.json`, and `feature_profile.png`.
- The dataset root publishes `manifest.parquet`, a deterministic `manifest.json` mirror, and the current `feature_profile.png`.
- Consumers resolve Gold through the dataset-local `manifest.parquet`; JSON and PNG are sidecars, not publication authority.
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

Bronze and Silver use monthly Parquet partitions to avoid a small-file problem. Gold is a compact consumer-facing dataset and is published as immutable full-history snapshots.

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
        build_id=20260818T020000Z/
          data.parquet
          manifest.json
          feature_profile.png
        build_id=20260819T020000Z/
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

### Gold timestamp compatibility

At the Silver -> Gold boundary, `observation_date` is converted to the canonical Gold key used by `crypto-history-loader`:

```text
timestamp_m1: Datetime(time_unit="us", time_zone="UTC")
```

For this daily dataset:

```text
2026-08-18 -> 2026-08-18 00:00:00+00:00
```

Gold contains **no `observation_date` column**. `timestamp_m1` is the first column, unique, strictly increasing, and the join key for all Gold feature families. The `_m1` name is retained intentionally for cross-project schema compatibility even though this dataset has one observation row per source day rather than a one-minute grid.

### Gold features

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

A successful immutable build is stored at:

```text
lake/gold/dataset=regime_features_daily/
  versions/build_id=<YYYYMMDDTHHMMSSZ>/
    data.parquet
    manifest.json
    feature_profile.png
```

`data.parquet` is the complete canonical Gold frame. `manifest.json` is the build-specific JSON lineage/report sidecar, following the same Parquet + JSON-manifest pattern used by `crypto-history-loader`. `feature_profile.png` is a deterministic numeric feature-distribution/profile plot derived from exactly the published frame; `timestamp_m1` is excluded from plotted feature distributions.

Completed build directories are immutable. A later run creates a new build directory and never modifies an already completed one.

### Dataset-root publication sidecars

The dataset root contains:

```text
manifest.parquet
manifest.json
feature_profile.png
```

Their roles are intentionally different:

- `manifest.parquet` is the **authoritative machine-readable publication catalog** and the only source for resolving the current compatible build.
- `manifest.json` is a deterministic JSON mirror of that catalog/current resolution for human inspection and non-Parquet tooling.
- `feature_profile.png` is the plot belonging to the currently published build.

A mismatch between the root JSON/plot and the authoritative Parquet manifest is invalid publication state and must be prevented or rolled back by the publication service.

### Gold manifest catalog

`manifest.parquet` contains one row per attempted build with the planned contract:

```text
dataset_id
build_id
status                    # building | complete | failed
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

`min_timestamp` and `max_timestamp` use the same UTC timestamp type/serialization semantics as the Gold frame rather than separate date-only fields.

Publication rules:

- only `status=complete` may have `current=true`;
- after the first successful publication, exactly one physically retained complete build is current;
- a selectable build requires non-null `data_path`, `build_manifest_path`, and `plot_path`;
- the previous current build remains current until the new Parquet, build JSON, build plot, and root sidecars have all been staged and validated;
- the final authoritative `manifest.parquet` replacement is the publication commit point;
- a failed or incomplete build never becomes current;
- consumers must not select `max(build_id)` or the newest file by mtime.

### Consumer resolution

A downstream consumer such as `portfell` should:

1. read `manifest.parquet`;
2. prefer `status=complete AND current=true` if its `schema_version` and `feature_version` are supported and its three build artifact paths are non-null;
3. otherwise choose the newest compatible `complete` row with all required paths present, ordered by `completed_at_utc DESC, build_id DESC`;
4. read only that row's `data_path`;
5. never select `building` or `failed` rows.

JSON and plot files are not needed for the selection algorithm.

### Retention

The planned default retention policy keeps five successful physical builds **including the current build** for each `(schema_version, feature_version)` pair. Retention treats one build directory as one unit: `data.parquet`, `manifest.json`, and `feature_profile.png` are retained or pruned together. Historical catalog rows remain as audit metadata after physical pruning, with all three artifact-path fields set to null.

## Bootstrap And Daily Delta Behavior

For every registered source series:

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

The planned daily pipeline publishes Gold only after Bronze/Silver processing, Gold assembly, immutable build sidecars, and validation succeed. Root `manifest.parquet` is replaced last and is the publication boundary.

## Planned Repository Structure

```text
api/                 CLI parsing and command output
application/         use cases, registry, contracts, planning, policies
ingestion/           HTTP adapters, provider parsing, Parquet/JSON/plot IO
scripts/             operational entrypoints
lake/                ignored local Bronze/Silver/Gold/state/manifests
tests/               unit, contract, regression, integration tests
BACKLOG.md            authoritative atomic PR plan
ARCHITECTURE.md       durable architecture sidecar
README.md             durable repository/operator sidecar
```

## Documentation Sidecar Contract

`README.md` and `ARCHITECTURE.md` are durable sidecars of the implementation and must remain synchronized with code and `BACKLOG.md`.

A PR is incomplete if it changes repository scope, provider ownership, medallion paths, timestamp naming/types, Bronze/Silver/Gold contracts, Gold versioning, manifest/JSON/plot sidecars, publication/compatibility/retention behavior, runtime behavior, or quality guarantees without updating the applicable sidecars in the same PR.

`BACKLOG.md` is the delivery source of truth. `ARCHITECTURE.md` is the engineering contract. `README.md` is the concise consumer/operator contract. None may intentionally describe behavior that differs from `main`.

## Current Status

The repository is currently at the architecture/backlog stage. `BACKLOG.md` defines the atomic implementation sequence for two parallel weak agents. Production loaders and publication commands should only be documented as executable after their implementing PRs are merged.

## Design Reference

The medallion, timestamp, Gold JSON-manifest, and feature-profile concepts are aligned with `SergejSchweizer/crypto-history-loader`. This repository intentionally retains a simpler daily source model and monthly Bronze/Silver partitions while matching the cross-project Gold timestamp convention and exposing immutable Gold build sidecars.