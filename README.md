# MARKET-REGIME-LOADER

Reusable daily market-state loader for quantitative research and portfolio systems.

The repository acquires open/public market and macro series, preserves their historical observations in a deterministic Parquet lake, normalizes them into a canonical daily schema, derives causal market-state features, and publishes immutable Gold snapshots for downstream consumers.

The project is intentionally a **data product**, not a trading system. It does not own HMM states, `risk_on`/`risk_off` labels, prediction targets, portfolio weights, or execution decisions.

## Status

The reviewed medallion architecture is implemented through the atomic PR sequence in `BACKLOG.md`: provider ingestion, incremental Bronze, canonical Silver, causal Gold features, immutable Gold bundles, authoritative catalog publication, materialized root views, retention, and the operational CLI are covered by the repository quality gates.

Before implementing a backlog PR, coding agents must read `AGENTS.md`, `BACKLOG.md`, and `ARCHITECTURE.md`.

## Architecture

The implementation uses **hexagonal architecture (Ports and Adapters)** with dependency injection and composition.

```text
                         api / scripts
                              |
                              v
                         application
                    use cases + policies
                    /                 \
                   v                   v
          persistence ports       provider ports
                   ^                   ^
                   |                   |
        Parquet/JSON/PNG         HTTP/provider
        repository adapters       adapters
                   \                   /
                    +--------+---------+
                             |
                             v
                 Bronze -> Silver -> Gold
```

Core design patterns are deliberately explicit:

- **Adapter** for provider and persistence implementations.
- **Strategy** for retry, update/reconciliation, and consumer-resolution policies.
- **Registry/Factory** for canonical provider/series routing; orchestration must not use provider `if/elif` ladders.
- **Repository** for Bronze, Silver, ingestion state, run manifests, Gold build storage, and the Gold catalog.
- **Unit of Work** for one-series ingestion durability and Gold publication commit boundaries.
- **State Machine** for Gold publication: `building -> complete|failed`.
- **Materialized View** for root Gold JSON/PNG, derived from authoritative `manifest.parquet`.
- **Mark-and-Sweep** for safe Gold retention: make a build unselectable before deleting physical files.
- **Command** for CLI adapters that call application use cases without embedding business logic.

Prefer `typing.Protocol`, immutable contracts, pure transformations, and constructor injection over inheritance-heavy frameworks.

## Initial Series Catalog

| Canonical ID | Primary source | Purpose |
|---|---|---|
| `vix` | CBOE | S&P 500 implied volatility |
| `vix9d` | CBOE | short-horizon implied volatility |
| `vix3m` | CBOE | 3-month implied volatility |
| `vix6m` | CBOE | 6-month implied volatility |
| `vix1y` | CBOE | 1-year implied volatility |
| `vstoxx` | STOXX | Euro-area equity implied volatility |
| `move` | Yahoo Finance | US Treasury implied volatility |
| `ciss` | ECB | euro-area systemic stress |
| `estr` | ECB | euro short-term rate |
| `euro_hy_oas` | FRED | euro high-yield credit spread |
| `us_2y` | FRED | US 2-year Treasury yield |
| `us_10y` | FRED | US 10-year Treasury yield |
| `usd_broad` | FRED | broad US-dollar index |

No additional MVP series may be introduced without a separate backlog PR and matching contract updates.

## Source Update Policy

The loader distinguishes three explicit operation modes:

```text
bootstrap   -> first complete public history when no Bronze exists
update      -> normal delta-only execution for an existing series
reconcile   -> explicit operator-requested full-history reconciliation
```

### Normal update is delta-only

For an existing series, the authoritative Bronze data determines:

```text
latest_stored_date = max(Bronze.observation_date)
request_start      = latest_stored_date - overlap_days
request_end        = injected_today
```

Default `overlap_days = 7` calendar days so recent source corrections can still replace equal-key observations. The normal `update` command and `run-daily` **never automatically switch to full-history reconciliation**.

Example:

```text
Bronze min date:       2000-01-03
Bronze latest date:    2026-08-18
injected today:        2026-08-19
overlap:               7 days

normal request window: 2026-08-11 .. 2026-08-19
```

The request must **not** start from `2000-01-03`. The oldest retained date is irrelevant to normal delta planning.

For `date_range` providers, the network request must use those exact bounds. Providers may not silently expand a normal update into a maximum-history query.

For `full_file` providers such as the catalogued CBOE/STOXX sources, the public source may only expose a complete file. In that case the complete remote object may have to be downloaded, but the adapter must restrict the logical update/diff to the requested delta window before persistence. Consequently, normal execution still rewrites only inserted/revised delta rows and affected monthly partitions. The project must not claim network-level delta retrieval where the upstream source does not support it.

A provider response outside the normal logical window must not enlarge the accepted update scope. For bounded providers, out-of-window rows are an adapter/contract error; for full-file providers, out-of-window rows are ignored for the normal delta diff.

### Explicit reconciliation

`reconcile` is a separate explicit command. It may request maximum currently exposed history to detect older revisions outside the overlap window. It is **not invoked automatically by `run-daily`**. If operators want periodic reconciliation, they schedule the explicit `reconcile` command separately.

A shorter upstream response is never interpreted as permission to delete older retained history. Equal-key observations may be revised. Explicit deletion semantics require an explicit provider contract and are not inferred from omission.

## Medallion Lake

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

Bronze and Silver use deterministic monthly partitions. Gold is small enough to publish complete immutable snapshots.

## Bronze

Bronze preserves provider-shaped observations plus safe ingestion metadata.

Common contract:

```text
series_id: String
provider: String
observation_date: Date
fetched_at_utc: Datetime(time_zone="UTC")
source_id: String
source_url: String
```

Provider payload is either OHLC (`open/high/low/close`) or scalar (`value`). Natural key:

```text
(provider, series_id, observation_date)
```

## Silver

Canonical daily long-form contract:

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

OHLC sources use `value == close`; scalar sources use `value` and null OHLC fields. Silver never fills missing dates.

## Gold

Gold uses the same temporal key convention as `crypto-history-loader`:

```text
timestamp_m1: Datetime(time_unit="us", time_zone="UTC")
```

Daily source dates map to UTC midnight. This is **observation-day identity**, not provider release time or tradability time. Gold contains no `observation_date` column.

Feature semantics are fixed and causal:

- `delta_Nobs(t) = x(t) - x(previous Nth valid observation)`;
- 60-observation z-scores use the last 60 valid observations including `t` and population standard deviation (`ddof=0`);
- no forward fill, backward fill, interpolation, centered windows, or implicit as-of carry;
- same-series rolling operations count valid observations, not calendar days;
- cross-series ratios/spreads require the same `timestamp_m1`;
- final Gold contains nulls but no NaN or infinity.

Initial semantic versions:

```text
schema_version  = 1
feature_version = 1
```

Schema version changes for column name/order/type changes. Feature version changes for formula/parameter changes that preserve schema.

## Immutable Gold Build Bundle

Each successful build directory is creation-only:

```text
versions/build_id=<YYYYMMDDTHHMMSSZ>/
  data.parquet
  manifest.json
  feature_profile.png
```

`data.parquet` is the canonical full-history Gold frame.

Build `manifest.json` describes the immutable **artifact bundle**, including dataset/build identity, semantic versions, ordered columns, row/timestamp bounds, `data_sha256`, `feature_set_hash`, source Git commit, and plot path. It does **not** own publication lifecycle status; `building|complete|failed` belongs only to the root catalog.

`feature_profile.png` is a deterministic numeric feature-profile plot generated from the exact Gold frame; `timestamp_m1` is excluded.

## Authoritative Gold Catalog

The publication authority is:

```text
lake/gold/dataset=regime_features_daily/manifest.parquet
```

Catalog fields:

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
pruned_at_utc
```

Only `manifest.parquet` chooses the current build. Consumers must never use directory order, mtime, or `max(build_id)`.

Consumer resolution is policy-driven:

- `strict_current` is the safe default: current must be compatible/selectable or resolution fails.
- `latest_compatible` is an explicit resilience policy: when current is incompatible, select the newest compatible complete, non-pruned catalog row.

Catalog resolution itself is pure and does not inspect the filesystem. Opening the selected immutable bundle performs physical integrity checks.

## Root JSON And Plot Are Materialized Views

The dataset root also exposes:

```text
manifest.json
feature_profile.png
```

These are **rebuildable materialized views** of authoritative `manifest.parquet` and its current build. They do not participate in consumer selection.

This avoids pretending that three independent filesystem replacements can be one atomic transaction. The atomic catalog replacement is the publication commit. Root JSON/PNG are regenerated and verified immediately afterward and reconciled on startup after interruption.

## Publication State Machine

```text
new attempt
    |
    v
building,current=false
    |
    +--> build/validate immutable bundle
    |          |
    |          +-- failure --> failed,current=false
    |
    v
atomic catalog promotion
new=complete,current=true
old=current=false
    |
    v
refresh root materialized views
```

A previous current build remains authoritative until the atomic catalog promotion. Filesystem presence never auto-promotes an interrupted build.

## Retention

Default retention keeps five physical successful builds per `(schema_version, feature_version)` pair, including current.

Retention uses mark-and-sweep:

1. choose an eligible non-current complete build;
2. atomically mark it unselectable in the catalog by nulling artifact paths and setting `pruned_at_utc`;
3. delete the immutable physical bundle;
4. if deletion is interrupted, the remaining files are safe orphans and cleanup retries later.

The catalog is therefore never left pointing at a partially deleted selectable bundle.

## Operational CLI

Install/sync the project and use the console entry point:

```bash
uv sync
uv run market-regime-loader --help
```

The exact command surface is:

```text
bootstrap
update
reconcile
silver-build
gold-build
inventory
run-daily
```

Global options such as `--lake-root`, `--today`, and `--overlap-days` precede the subcommand. `--series` follows commands that accept a series restriction.

Examples:

```bash
# First explicit maximum-history load for selected series.
uv run market-regime-loader \
  --lake-root /srv/market-regime/lake \
  bootstrap --series vix --series us_10y

# Normal bounded source update only.
uv run market-regime-loader \
  --lake-root /srv/market-regime/lake \
  update --series us_10y

# Explicit operator reconciliation; never invoked by run-daily.
uv run market-regime-loader \
  --lake-root /srv/market-regime/lake \
  reconcile --series us_10y

# Full operational daily path.
uv run market-regime-loader \
  --lake-root /srv/market-regime/lake \
  run-daily

# Rebuild and print the local inventory.
uv run market-regime-loader \
  --lake-root /srv/market-regime/lake \
  inventory --json
```

### Daily pipeline contract

`run-daily` is deliberately **delta-only** for sources:

```text
recover interrupted Gold publication/root views
        -> Bronze update (or bootstrap only when that series has no Bronze)
        -> selected Silver rebuild
        -> full canonical Gold from all 13 available Silver series
        -> immutable bundle + physical validation
        -> authoritative catalog promotion
        -> root materialized-view refresh
        -> Gold retention
        -> inventory refresh
```

For existing Bronze the request window is always:

```text
max(Bronze.observation_date) - overlap_days .. injected today
```

With the default overlap this is seven calendar days. `run-daily` has no hidden call path to source `reconcile`, maximum-history loading, or the historical minimum. An explicit `--series` restricts Bronze/Silver work only; Gold remains a full canonical dataset and therefore requires all 13 Silver inputs to exist.

### Runtime configuration

Use a **persistent** lake path. A container-local ephemeral path would lose the incremental state and defeat delta planning.

FRED-backed source commands require:

```bash
export FRED_API_KEY='...'
```

The key is runtime configuration only and is sanitized from structured CLI logs and persisted failure metadata.

Gold-capable commands (`gold-build`, `run-daily`) record the source Git commit in each immutable build manifest. In a Git checkout the CLI resolves `git rev-parse HEAD`; packaged/deployed environments should set explicitly:

```bash
export MARKET_REGIME_GIT_COMMIT='<40-or-64-character-lowercase-hex-commit>'
```

The optional testing/debugging flag `--today YYYY-MM-DD` injects the planning date deterministically. Production scheduling normally omits it.

### Scheduling

The data lake is intended to run on the deployment host/NAS, not as scheduled GitHub Actions ingestion. The checked-in crontab template schedules the delta-only update every **Saturday at 10:00 in the deployment host's local time zone**:

```cron
0 10 * * 6 cd /srv/market-regime-loader && /usr/local/bin/uv run market-regime-loader --lake-root /srv/market-regime/lake run-daily >> /var/log/market-regime-loader.log 2>&1
```

Install it for the service account after reviewing the absolute paths for that host:

```bash
crontab ops/market-regime-loader.cron
```

The cron command is intentionally only `run-daily`, so it preserves the normal bounded delta-update contract and never performs an implicit source reconciliation.

Equivalent systemd service command:

```text
WorkingDirectory=/srv/market-regime-loader
ExecStart=/usr/local/bin/uv run market-regime-loader --lake-root /srv/market-regime/lake run-daily
```

If periodic maximum-history reconciliation is desired, schedule it **separately** and less frequently, for example weekly:

```cron
30 3 * * 0 cd /srv/market-regime-loader && /usr/local/bin/uv run market-regime-loader --lake-root /srv/market-regime/lake reconcile >> /var/log/market-regime-reconcile.log 2>&1
```

Keeping these schedules separate makes the normal daily delta guarantee observable and testable.

## Quality Gates

Required push and merge checks:

```text
lint
type
unit
integration
coverage
```

`lint`, `type`, `unit`, and offline `integration` run in parallel. Unit and integration suites produce independent coverage data. The `coverage` gate combines them and requires total production-code line coverage:

```text
>= 90.0%
```

Live provider tests are marked `network` and are excluded from required gates.

`main` is intended to be protected: no direct pushes, required pull request, required five checks, no force push/delete, squash merge, and repository auto-merge. Implementation PRs enable auto-merge so GitHub merges them only after all required merge-gate conditions pass.

## Repository Structure

```text
api/                 CLI adapters only
application/         use cases, contracts, policies, ports
application/ports/   provider/persistence/clock/sleeper interfaces
ingestion/           provider + filesystem adapters
scripts/             operational wrappers and repo tooling
tests/unit/          deterministic unit tests
tests/integration/   offline component/E2E tests
tests/fixtures/      committed small fixtures
lake/                ignored runtime data
AGENTS.md             coding-agent rules
BACKLOG.md            implementation source of truth
ARCHITECTURE.md       durable engineering contract
README.md             operator/consumer contract
```

## Documentation Contract

`BACKLOG.md`, `ARCHITECTURE.md`, `README.md`, and `AGENTS.md` must not intentionally contradict one another. A PR that changes a documented contract updates the relevant sidecars in the same PR.
