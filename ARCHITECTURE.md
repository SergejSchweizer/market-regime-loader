# Architecture

This document is the durable architecture contract for `market-regime-loader`.

It must remain synchronized with code changes that alter repository scope, supported series, providers, medallion paths, timestamp conventions, dataset contracts, Gold publication/versioning/sidecars, runtime/update behavior, package boundaries, or quality guarantees. `README.md` is the concise consumer/operator sidecar; `BACKLOG.md` is the delivery/ticket source of truth.

## System Shape

`market-regime-loader` is a reusable daily market-state data platform. It downloads maximum open/public history, normalizes provider data into canonical daily series, derives causal market-state features, and publishes immutable Gold snapshots for downstream consumers.

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
              HTTP + parsing        Polars/Parquet/sidecars
                    |                           |
                    +-------------+-------------+
                                  |
                                  v
                  lake/bronze -> lake/silver -> lake/gold
                                                   |
                                                   v
                                      immutable build bundle
                                  parquet + json + png
                                                   |
                                                   v
                                  root publication sidecars
                              manifest.parquet/json + plot
                                                   |
                                                   v
                                      downstream consumers
```

The repository owns data acquisition, normalization, persistence, causal reusable features, coverage metadata, update state, Gold versioning, and Gold publication metadata/sidecars. It does not own regime labels, models, strategy decisions, portfolio allocation, or trading execution.

## Dependency Direction

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

- `api/` may depend on `application/`, but must not implement provider HTTP behavior or persistence rules.
- `application/` owns registry contracts, bootstrap/delta planning, canonical schemas, Gold publication state transitions, and deterministic policy.
- `ingestion/` owns HTTP/parsing details and physical Parquet/JSON/PNG persistence.
- `ingestion/` must not own CLI parsing, regime classification, portfolio logic, or trading behavior.
- Consumers read published contracts rather than import provider internals.
- Consumers must not infer the current Gold build from filesystem ordering or modification timestamps.

## Layer Ownership

| Layer | Owns | Must not own |
|---|---|---|
| `api/` | CLI parsing, command wiring, output shape | provider requests, persistence internals, model logic |
| `application/` | registry, provider capability, range planning, medallion contracts, timestamp policy, feature contracts, publication state machine, validation | HTTP parsing internals, low-level file replacement, strategy logic |
| `ingestion/` | provider adapters, Polars/Parquet IO, JSON serialization, feature-profile plot persistence, filesystem paths | CLI policy, regime decisions, portfolio allocation |
| `scripts/` | schedulable operational entrypoints | hidden domain rules |
| `tests/` | unit, contract, regression, integration, architecture validation | production behavior |

## Initial Series Registry

The first implementation contains exactly:

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
CBOE   -> vix, vix9d, vix3m, vix6m, vix1y
STOXX  -> vstoxx
Yahoo  -> move
ECB    -> ciss, estr
FRED   -> euro_hy_oas, us_2y, us_10y, usd_broad
```

Every registry entry declares `series_id`, provider, source ID/file, unit, native shape, frequency, bootstrap strategy, and provider capability (`date_range` or `full_file`). No unregistered series may be ingested or published.

## Medallion Data Flow

```text
Bronze
  provider-shaped observations
  monthly partitions
  audit-friendly ingestion metadata
             |
             v
Silver
  canonical daily long-form series
  observation_date: Date
  no synthetic observations
             |
             v
Gold logical frame
  timestamp_m1: Datetime(us, UTC)
  reusable causal features
             |
             v
Gold immutable build
  data.parquet
  manifest.json
  feature_profile.png
             |
             v
Dataset-root publication
  manifest.parquet  <- authority
  manifest.json     <- deterministic mirror
  feature_profile.png <- current visual sidecar
```

## Bronze Contract

Required common fields:

```text
series_id: String
provider: String
observation_date: Date
fetched_at_utc: Datetime(time_zone="UTC")
source_id: String
source_url: String
```

OHLC providers retain `open`, `high`, `low`, `close`; scalar providers retain `value`.

Natural key:

```text
(provider, series_id, observation_date)
```

Bronze never synthesizes observations, never deletes retained history merely because an upstream free window shrinks, and rewrites only affected monthly partitions.

## Silver Contract

Silver exposes one provider-independent daily schema:

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

Rules:

- OHLC series use `value == close`.
- Scalar series use source `value`; OHLC fields remain null.
- Natural key is `(series_id, observation_date)`.
- Duplicate keys are invalid after canonicalization.
- Missing dates remain missing; no forward-fill/back-fill/interpolation occurs.

## Gold Timestamp Contract

Gold deliberately matches the canonical timestamp convention used in `crypto-history-loader`.

The first and only temporal join key is:

```text
timestamp_m1: Datetime(time_unit="us", time_zone="UTC")
```

No `observation_date` column is allowed in Gold.

Because the market-regime sources are daily, the Silver date is converted deterministically to UTC midnight:

```text
observation_date = 2026-08-18
        ->
timestamp_m1 = 2026-08-18T00:00:00.000000+00:00
```

The `_m1` name is an interoperability convention, not a claim that this dataset contains a complete one-minute grid. The Gold dataset remains daily-frequency: at most one canonical row exists for a source calendar date.

Gold timestamp invariants:

- dtype is exactly Polars `Datetime(time_unit="us", time_zone="UTC")`;
- values are UTC midnight for the represented source day;
- rows are strictly increasing by `timestamp_m1`;
- `timestamp_m1` is unique;
- all cross-feature joins use `timestamp_m1`;
- feature calculations remain causal relative to the represented source day.

## Gold Logical Dataset

Logical dataset ID:

```text
regime_features_daily
```

Initial feature families:

- volatility levels, trailing changes, and trailing standardized values;
- VIX term-structure ratios/slopes;
- CISS changes;
- euro HY OAS changes;
- US 2Y/10Y levels, changes, and 10Y-minus-2Y slope;
- €STR level/change;
- broad USD level/change.

Gold does not publish HMM states, `risk_on`/`risk_off`, signals, targets, or portfolio weights.

## Physical Lake Layout

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

Bronze/Silver monthly partitioning is optimized for incremental source maintenance. Gold is small enough that every successful build is a complete immutable snapshot.

`lake/manifests/*` contains operational ingestion metadata. `lake/gold/dataset=regime_features_daily/manifest.parquet` is different: it is the consumer-facing Gold publication authority.

## Gold Build Bundle

Every publication attempt has a build ID formatted exactly:

```text
YYYYMMDDTHHMMSSZ
```

A successful completed build directory contains exactly the required consumer/audit artifacts:

```text
versions/build_id=<build_id>/
  data.parquet
  manifest.json
  feature_profile.png
```

### `data.parquet`

Contains the full canonical Gold frame. Its first column is `timestamp_m1`; all remaining columns are deterministic numeric-or-null regime features. A completed file is immutable.

### build `manifest.json`

The build JSON follows the same Parquet + JSON-manifest pattern used by `crypto-history-loader`. It is deterministic (`sort_keys` semantics), UTF-8, and records at least:

```text
dataset_id
build_id
schema_version
feature_version
status
started_at_utc
completed_at_utc
rows_out
columns
min_timestamp
max_timestamp
data_path
plot_path
```

It describes that immutable build only. It is not the multi-build consumer selection authority.

### build `feature_profile.png`

The build plot is generated from exactly the frame written to `data.parquet`. It is a deterministic numeric feature distribution/profile visualization analogous to the Gold feature plot in `crypto-history-loader`.

Rules:

- `timestamp_m1` is excluded from distributions;
- only numeric Gold feature columns are plotted;
- no sampling dependent on wall-clock/random state is allowed;
- plot generation is mandatory for a successful published build;
- a plot failure prevents that build from becoming current.

## Dataset-Root Gold Sidecars

The dataset root contains three stable files:

```text
manifest.parquet
manifest.json
feature_profile.png
```

### Root `manifest.parquet`

This is the only authoritative current-build catalog. It contains one row per attempted build with:

```text
dataset_id: String
build_id: String
status: String              # building | complete | failed
current: Boolean
started_at_utc: Datetime(time_zone="UTC")
completed_at_utc: Datetime(time_zone="UTC") nullable
schema_version: Int64
feature_version: Int64
min_timestamp: Datetime(time_unit="us", time_zone="UTC") nullable
max_timestamp: Datetime(time_unit="us", time_zone="UTC") nullable
row_count: Int64 nullable
data_path: String nullable
build_manifest_path: String nullable
plot_path: String nullable
```

Manifest invariants:

- `build_id` is unique;
- only `complete` may be current;
- before first successful publication there may be zero current rows;
- afterward exactly one physically retained complete build is current;
- selectable rows require all three artifact paths non-null;
- ordering is deterministic by `started_at_utc`, then `build_id`.

### Root `manifest.json`

This is a deterministic JSON mirror of the authoritative catalog, intended for inspection and non-Parquet tooling. Its top-level shape is:

```json
{
  "dataset_id": "regime_features_daily",
  "current_build_id": "20260818T020000Z",
  "builds": []
}
```

`builds` serializes the same logical rows and ordering as `manifest.parquet`. The JSON must never independently choose a different current build. A consistency test must prove that its current build and build records correspond to the Parquet catalog.

### Root `feature_profile.png`

This is the feature profile for the build identified as current by `manifest.parquet`. It is a stable operator-facing path; version-specific historical plots remain under their immutable build directories.

## Publication Transaction

The root `manifest.parquet` replacement is the **commit point**. JSON and PNG are required sidecars but do not independently publish a build.

Planned sequence:

```text
1. register attempted build as building,current=false
2. create immutable build data.parquet
3. create immutable build manifest.json
4. create immutable build feature_profile.png
5. validate all three build artifacts and Gold schema/timestamp/coverage
6. build next catalog in memory
7. stage root manifest.json mirror
8. stage root feature_profile.png
9. stage root manifest.parquet
10. transactionally replace root JSON/PNG and replace manifest.parquet last
```

Failure policy:

- the previous authoritative `manifest.parquet` remains unchanged until the final commit point;
- supplemental root files are staged and rollback-safe;
- if any build artifact or root sidecar fails validation/replacement before the commit point, the old current build remains authoritative;
- the failed attempted build is recorded non-current when a valid catalog update can be safely written;
- consumers never need to inspect incomplete version directories.

This is transaction-like filesystem publication with rollback; it does not rely on pretending that three independent filesystem renames are one hardware-atomic operation.

## Consumer Resolution

Consumers such as `portfell` use only the root Parquet catalog for selection:

```text
1. Read manifest.parquet.
2. Prefer status=complete AND current=true.
3. Require supported schema_version and feature_version.
4. Require non-null data_path, build_manifest_path, and plot_path.
5. If current is incompatible, choose newest compatible complete row by
   completed_at_utc DESC, build_id DESC.
6. Read exactly data_path.
7. Never select building or failed rows.
```

The JSON/PNG sidecars are informational/audit/visual artifacts and are not required by `portfell` to locate the data frame.

## Retention

Default planned retention:

```text
gold_retention_successful_builds = 5
```

Retention is evaluated per `(schema_version, feature_version)` pair. One physical build is a directory bundle; its `data.parquet`, `manifest.json`, and `feature_profile.png` are retained or pruned together.

Rules:

- never prune current;
- building/failed attempts do not count toward the successful-build limit;
- different semantic version pairs are isolated;
- oldest eligible non-current complete directories are pruned first;
- audit catalog rows remain after physical pruning;
- pruned rows set `data_path`, `build_manifest_path`, and `plot_path` to null and become unselectable.

## Parquet, JSON, Plot, And Polars Contract

- Production dataframe operations are Polars-first; pandas is not introduced into production transformation code.
- Bronze/Silver and Gold tabular data use Parquet.
- JSON sidecars are UTF-8, deterministic, and written via temporary file + fsync + replace semantics.
- Feature-profile PNG generation uses a deterministic plotting function and the exact published frame.
- Bronze/Silver writes are atomic at monthly-file granularity.
- Gold completed build directories are immutable.
- Root publication sidecars use staging and rollback, with `manifest.parquet` replaced last as commit point.
- A no-op rerun does not create duplicate logical source observations; Gold build policy may additionally avoid publication when input identity is unchanged if implemented by a later explicit contract.

## Bootstrap And Incremental Source Update

When no Bronze history exists, request maximum open/public history. When history exists:

```text
latest = latest stored observation_date
start  = latest - overlap_days
end    = injected current date
```

Default overlap is seven calendar days. `date_range` providers request that range; `full_file` providers may refetch their compact authoritative history but merge only missing/revised rows. Upstream truncation never deletes older local history.

## Daily Pipeline Publication Order

```text
1. Bronze update
2. deterministic Silver rebuild
3. Gold timestamp normalization and feature assembly
4. immutable data.parquet write
5. immutable build manifest.json
6. immutable build feature_profile.png
7. Gold validation
8. root JSON/PNG staging
9. authoritative manifest.parquet publication
10. Gold retention
11. inventory refresh
```

Any failure before step 9 leaves the previous current Gold build authoritative.

## Missing-Data And Causality Policy

- Bronze does not synthesize observations.
- Silver does not fill absent source days.
- Gold may outer-join feature families but retains nulls when inputs are unavailable.
- Rolling features use only current/past observations.
- No centered windows or future values are allowed.
- Converting a daily source date to UTC midnight does not change information availability; it is a schema interoperability representation. Any later publication-time/availability-time model must be explicit before using data intraday.

## Testing Contract

Default tests are offline. Provider tests use small fixtures or mocked HTTP responses.

Required Gold contract tests include:

- `timestamp_m1` exact name and position;
- exact `Datetime(us, UTC)` dtype;
- daily date -> UTC-midnight conversion;
- no `observation_date` in Gold;
- strict timestamp uniqueness/order;
- causal feature calculations;
- immutable version paths;
- deterministic build JSON;
- deterministic numeric feature-profile PNG generation;
- JSON/Parquet catalog consistency;
- root plot corresponds to current build;
- publication failure rollback at each build/root sidecar stage;
- current/compatible consumer resolution;
- bundle-level retention.

## Documentation Sidecars

`README.md` and `ARCHITECTURE.md` are implementation sidecars. `BACKLOG.md` is the delivery contract.

Any PR changing scope, series registry, providers, physical lake layout, timestamp semantics, Bronze/Silver/Gold schemas, build bundles, root manifests/plots, publication/retention behavior, feature semantics, package boundaries, CLI behavior, or quality guarantees must update the applicable sidecars in the same PR.

## Relationship To `crypto-history-loader`

`crypto-history-loader` is the design reference for deterministic Medallion ownership, Polars/Parquet lake behavior, explicit Gold contracts, restart safety, `timestamp_m1`, JSON Gold manifests, and numeric feature-profile plots.

`market-regime-loader` intentionally does not copy crypto-specific minute/tick grids, exchange instrument structures, options surfaces, or high-frequency partitioning. Its source cadence is daily, but its Gold temporal schema is deliberately compatible with the reference repository.