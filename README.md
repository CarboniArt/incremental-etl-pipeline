# Incremental ETL Pipeline

Scheduled batch job that copies production-planning views from an operational
SQL database into an analytics warehouse every 15 minutes, using a **sliding
window overwrite** through a staging table, with guards that refuse to load a
batch that looks broken.

> **Public demo version.** Sanitized reimplementation of a pipeline I built
> (SQL Server → Google BigQuery). Here both ends are local SQLite files filled
> with synthetic data, so it runs offline with no credentials. See
> [Mock environment](#mock-environment).

## Problem

BI dashboards needed near-real-time order, machine-schedule and reel-queue data
that lived only in the production planning system's database. The first version
of the job truncated and reloaded every view on each run; running it every
15 minutes exposed three issues:

- reloading the full history on every run is wasteful when only recent orders change;
- orders keep changing for weeks after creation (status, produced quantity), so
  a pure append/incremental-by-id load would miss updates;
- if the source returned an empty or partial result (maintenance, network
  hiccup, a broken view), the job would happily wipe good data in the warehouse.

## Solution

- **Sliding window:** each run re-reads only the last `MESES_JANELA` months
  (from the 1st day of the month, default 3) and replaces exactly that window in
  the destination. Small reference views without a date filter are fully reloaded.
- **Staging + atomic swap:** the batch is first written to `<TABLE>__STG`; then a
  single transaction runs `DELETE window` + `INSERT … SELECT FROM staging`. If
  anything fails, the destination keeps its previous state. Staging is emptied afterwards.
- **Data-loss guards:** abort when the view returns 0 rows, or when the new batch
  is less than 50 % of the rows currently stored for the same window (checked
  only above 1,000 rows).
- **Explicit typing:** every column is declared once with its warehouse type and
  normalised with pandas (strings trimmed, empty → NULL, numeric coercion,
  `Decimal` for NUMERIC, timezone stripped from datetimes); a `data_carga`
  timestamp is appended.
- **Operational safety:** lock file so overlapping runs exit immediately
  (stale locks older than 25 min are taken over), up to 3 attempts per view,
  one failing view does not block the others, rotating log file, exit code ≠ 0
  on any error (for the scheduler to alert on).
- `--full` reloads every view entirely (initial load / recovery).

## Architecture

```
  scheduler (every 15 min)
          │
          ▼
  run.py ─► carga.main ── lock file ──┐
                │                     │
     for each view in config.VIEWS    │
                │                     │
     ┌──────────▼──────────┐          │
     │ fonte.ler_view       │  SELECT [cols] FROM [view] WHERE [DataCriacao] >= :corte
     │ (SQLAlchemy)         │
     └──────────┬──────────┘
                ▼
     transformacao.tratar_tipos  (+ data_carga)
                │
     guards: empty batch? volume drop > 50 %?
                │
     ┌──────────▼──────────────────────────────────────┐
     │ armazem                                          │
     │  window views:  load → <TABLE>__STG              │
     │                 BEGIN; DELETE window;            │
     │                 INSERT … SELECT FROM STG; COMMIT │
     │                 DELETE FROM STG                  │
     │  full views:    WRITE_TRUNCATE                   │
     └──────────────────────────────────────────────────┘
```

## Technologies

- **Python 3.11+**, `pandas`, `SQLAlchemy`, `python-dateutil`, `python-dotenv`
- Original: SQL Server (via `pyodbc`) and Google BigQuery (`google-cloud-bigquery`:
  load jobs, parameterised queries, multi-statement transactions)
- This demo: SQLite for both source and warehouse (standard library `sqlite3`)
- `pytest`

## How it works

| Step | Function |
|---|---|
| acquire lock / exit if another run is active | `obter_trava` |
| compute window start (`1st day of month − N months`) | `calcular_corte` |
| read the view (window filter pushed down to the source) | `fonte.ler_view` |
| normalise types, add `data_carga` | `transformacao.tratar_tipos` |
| refuse empty batch / large volume drop | `carregar_view`, `conferir_volume` |
| write staging and swap the window atomically | `sobrescrever_janela`, `trocar_janela` |
| full reload for views without a window | `carga_cheia` |
| retry each view, keep going on failure | `carregar_com_retentativa` |

The job never creates destination tables: they must exist (DDL in
[`sql/armazem.sql`](sql/armazem.sql)), so a typo in the configuration cannot
silently create a new empty table.

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python scripts/preparar_demo.py    # synthetic source (≈5,000 orders) + empty warehouse in data/
python run.py --full               # initial full load
python run.py                      # regular 15-minute run (window only)

python scripts/preparar_demo.py --atualizar       # new orders + status changes in the source
python run.py                                     # window replaced, history untouched

python scripts/preparar_demo.py --simular-perda   # ~80 % of recent orders vanish from the source
python run.py                                     # guard aborts that view, others still load

python -m pytest
```

Settings can be overridden in `.env` (see [`.env.example`](.env.example)); logs go
to `logs/carga.log`.

## Example

```
[INFO] === Inicio da carga (janela desde 01/07/2026 00:00) ===
[INFO] [OK] vw_ConsultaPedidos -> PEDIDOS | 2502 linhas (janela desde 01/07/2026, 2462 substituidas) | leitura 0.1s | total 0.2s
[INFO] [OK] vw_PedidosProgramadosMaquina -> PEDIDOS_PROGRAMADOS_MAQUINA | 905 linhas (janela desde 01/07/2026, 905 substituidas)
[INFO] [OK] vw_BobinasFilaBalanca -> BOBINAS_FILA_BALANCA | 678 linhas (carga cheia)
[INFO] === Fim da carga em 0.4s (0 erro(s)) ===
```

With a partial source:

```
[WARNING] [FALHA] vw_ConsultaPedidos (tentativa 1/3): lote com 492 linhas contra 2462 ja gravadas (queda acima de 50%); carga abortada para nao apagar dado bom | nova tentativa em 20s
[ERROR]   [ERRO] vw_ConsultaPedidos (tentativa 3/3): lote com 492 linhas contra 2462 ja gravadas (queda acima de 50%); ...
[INFO] === Fim da carga em 40.6s (1 erro(s)) ===
```

## Mock environment

| Original | This repository |
|---|---|
| SQL Server database of the production planning system (vendor views) | `data/fonte.db` — SQLite with synthetic tables and three views with the same column layout ([`sql/fonte.sql`](sql/fonte.sql)) |
| Google BigQuery dataset (destination + `__STG` tables) | `data/armazem.db` — SQLite; `ArmazemLocal` exposes the subset of the BigQuery client used by the job (`get_table`, `query`, `load_table_from_dataframe`, transactions) |
| BigQuery parameters (`@corte`) and `BEGIN/COMMIT TRANSACTION` script | SQLite named parameters (`:corte`) and a Python-managed transaction |
| Real customers, papers, machines | `Cliente 0001…0120`, generic paper grades, `MAQ-01/02` |
| Credentials in `.env` | none needed; `FONTE_URL` only accepts `sqlite:///` in this version |

## Project structure

```
run.py                       entry point (python run.py [--full])
src/etl_carga/
├── config.py                views, destination tables, column types, limits
├── carga.py                 orchestration: lock, window, guards, retries, logging
├── fonte.py                 source reader (SQLAlchemy)
├── armazem.py               local warehouse (BigQuery stand-in)
└── transformacao.py         type normalisation
sql/                         DDL for the synthetic source and the warehouse
scripts/preparar_demo.py     synthetic data generator and scenario simulation
tests/                       pytest suite
```

## Future improvements

- Watermark on a `DataAlteracao` column (when the source offers one) to shrink the window.
- Data-quality checks per column (null ratio, duplicate keys) next to the volume guard.
- Emit run metrics (rows, duration, errors) to a monitoring table or dashboard.
- Orchestrate with Airflow/Prefect instead of the OS scheduler.
