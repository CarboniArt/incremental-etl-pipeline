# Incremental ETL Pipeline

Job em lote agendado que copia views de planejamento de produção de um banco
SQL operacional para um data warehouse analítico a cada 15 minutos, usando
**sobrescrita por janela deslizante** através de uma tabela de staging, com
travas que se recusam a carregar um lote que pareça quebrado.

> **Versão pública de demonstração.** Reimplementação sanitizada de um pipeline
> que construí (SQL Server → Google BigQuery). Aqui as duas pontas são arquivos
> SQLite locais preenchidos com dados sintéticos, então tudo roda offline e sem
> credenciais. Veja [Ambiente simulado](#ambiente-simulado).

## Problema

Os dashboards de BI precisavam de dados quase em tempo real de pedidos,
programação de máquinas e fila de bobinas, que existiam apenas no banco do
sistema de planejamento da produção. A primeira versão do job truncava e
recarregava todas as views a cada execução; rodando a cada 15 minutos, isso
expôs três problemas:

- recarregar todo o histórico a cada execução é desperdício quando só os pedidos recentes mudam;
- os pedidos continuam mudando por semanas após a criação (status, quantidade
  produzida), então uma carga apenas incremental por id perderia atualizações;
- se a origem retornasse um resultado vazio ou parcial (manutenção, instabilidade
  de rede, view quebrada), o job apagaria sem hesitar dados bons no warehouse.

## Solução

- **Janela deslizante:** cada execução relê apenas os últimos `MESES_JANELA`
  meses (a partir do dia 1º do mês, padrão 3) e substitui exatamente essa janela
  no destino. Views de referência pequenas, sem filtro de data, são recarregadas por completo.
- **Staging + troca atômica:** o lote é gravado primeiro em `<TABELA>__STG`;
  depois uma única transação executa `DELETE da janela` + `INSERT … SELECT FROM staging`.
  Se algo falhar, o destino mantém o estado anterior. A staging é esvaziada ao final.
- **Travas contra perda de dados:** aborta quando a view retorna 0 linhas, ou
  quando o novo lote tem menos de 50 % das linhas já gravadas para a mesma janela
  (verificado apenas acima de 1.000 linhas).
- **Tipagem explícita:** cada coluna é declarada uma única vez com o seu tipo no
  warehouse e normalizada com pandas (strings com trim, vazio → NULL, conversão
  numérica, `Decimal` para NUMERIC, fuso horário removido das datas); é
  acrescentado um timestamp `data_carga`.
- **Segurança operacional:** arquivo de lock para que execuções sobrepostas
  saiam imediatamente (locks abandonados com mais de 25 min são assumidos), até
  3 tentativas por view, uma view com falha não bloqueia as demais, arquivo de
  log rotativo, código de saída ≠ 0 em qualquer erro (para o agendador alertar).
- `--full` recarrega todas as views por completo (carga inicial / recuperação).

## Arquitetura

```
  agendador (a cada 15 min)
          │
          ▼
  run.py ─► carga.main ── arquivo de lock ──┐
                │                           │
     para cada view em config.VIEWS         │
                │                           │
     ┌──────────▼──────────┐                │
     │ fonte.ler_view       │  SELECT [cols] FROM [view] WHERE [DataCriacao] >= :corte
     │ (SQLAlchemy)         │
     └──────────┬──────────┘
                ▼
     transformacao.tratar_tipos  (+ data_carga)
                │
     travas: lote vazio? queda de volume > 50 %?
                │
     ┌──────────▼──────────────────────────────────────┐
     │ armazem                                          │
     │  views c/ janela: carga → <TABELA>__STG          │
     │                 BEGIN; DELETE janela;            │
     │                 INSERT … SELECT FROM STG; COMMIT │
     │                 DELETE FROM STG                  │
     │  views cheias:  WRITE_TRUNCATE                   │
     └──────────────────────────────────────────────────┘
```

## Tecnologias

- **Python 3.11+**, `pandas`, `SQLAlchemy`, `python-dateutil`, `python-dotenv`
- Original: SQL Server (via `pyodbc`) e Google BigQuery (`google-cloud-bigquery`:
  load jobs, queries parametrizadas, transações com múltiplas instruções)
- Esta demo: SQLite para origem e warehouse (`sqlite3` da biblioteca padrão)
- `pytest`

## Como funciona

| Etapa | Função |
|---|---|
| obter o lock / sair se outra execução estiver ativa | `obter_trava` |
| calcular o início da janela (`dia 1º do mês − N meses`) | `calcular_corte` |
| ler a view (filtro da janela aplicado na origem) | `fonte.ler_view` |
| normalizar tipos, adicionar `data_carga` | `transformacao.tratar_tipos` |
| recusar lote vazio / grande queda de volume | `carregar_view`, `conferir_volume` |
| gravar a staging e trocar a janela de forma atômica | `sobrescrever_janela`, `trocar_janela` |
| recarga completa para views sem janela | `carga_cheia` |
| retentar cada view, seguir em frente em caso de falha | `carregar_com_retentativa` |

O job nunca cria tabelas de destino: elas precisam existir (DDL em
[`sql/armazem.sql`](sql/armazem.sql)), para que um erro de digitação na
configuração não crie silenciosamente uma tabela nova e vazia.

## Executando localmente

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python scripts/preparar_demo.py    # origem sintética (≈5.000 pedidos) + warehouse vazio em data/
python run.py --full               # carga completa inicial
python run.py                      # execução regular de 15 minutos (somente a janela)

python scripts/preparar_demo.py --atualizar       # novos pedidos + mudanças de status na origem
python run.py                                     # janela substituída, histórico intacto

python scripts/preparar_demo.py --simular-perda   # ~80 % dos pedidos recentes somem da origem
python run.py                                     # a trava aborta essa view, as outras carregam normalmente

python -m pytest
```

As configurações podem ser sobrescritas em `.env` (veja [`.env.example`](.env.example));
os logs vão para `logs/carga.log`.

## Exemplo

```
[INFO] === Inicio da carga (janela desde 01/07/2026 00:00) ===
[INFO] [OK] vw_ConsultaPedidos -> PEDIDOS | 2502 linhas (janela desde 01/07/2026, 2462 substituidas) | leitura 0.1s | total 0.2s
[INFO] [OK] vw_PedidosProgramadosMaquina -> PEDIDOS_PROGRAMADOS_MAQUINA | 905 linhas (janela desde 01/07/2026, 905 substituidas)
[INFO] [OK] vw_BobinasFilaBalanca -> BOBINAS_FILA_BALANCA | 678 linhas (carga cheia)
[INFO] === Fim da carga em 0.4s (0 erro(s)) ===
```

Com uma origem parcial:

```
[WARNING] [FALHA] vw_ConsultaPedidos (tentativa 1/3): lote com 492 linhas contra 2462 ja gravadas (queda acima de 50%); carga abortada para nao apagar dado bom | nova tentativa em 20s
[ERROR]   [ERRO] vw_ConsultaPedidos (tentativa 3/3): lote com 492 linhas contra 2462 ja gravadas (queda acima de 50%); ...
[INFO] === Fim da carga em 40.6s (1 erro(s)) ===
```

## Ambiente simulado

| Original | Este repositório |
|---|---|
| Banco SQL Server do sistema de planejamento da produção (views do fornecedor) | `data/fonte.db` — SQLite com tabelas sintéticas e três views com o mesmo layout de colunas ([`sql/fonte.sql`](sql/fonte.sql)) |
| Dataset do Google BigQuery (tabelas de destino + `__STG`) | `data/armazem.db` — SQLite; `ArmazemLocal` expõe o subconjunto do cliente BigQuery usado pelo job (`get_table`, `query`, `load_table_from_dataframe`, transações) |
| Parâmetros do BigQuery (`@corte`) e script `BEGIN/COMMIT TRANSACTION` | parâmetros nomeados do SQLite (`:corte`) e transação gerenciada em Python |
| Clientes, papéis e máquinas reais | `Cliente 0001…0120`, tipos de papel genéricos, `MAQ-01/02` |
| Credenciais no `.env` | nenhuma necessária; `FONTE_URL` só aceita `sqlite:///` nesta versão |

## Estrutura do projeto

```
run.py                       ponto de entrada (python run.py [--full])
src/etl_carga/
├── config.py                views, tabelas de destino, tipos de coluna, limites
├── carga.py                 orquestração: lock, janela, travas, retentativas, logs
├── fonte.py                 leitor da origem (SQLAlchemy)
├── armazem.py               warehouse local (substituto do BigQuery)
└── transformacao.py         normalização de tipos
sql/                         DDL da origem sintética e do warehouse
scripts/preparar_demo.py     gerador de dados sintéticos e simulação de cenários
tests/                       suíte pytest
```

## Melhorias futuras

- Watermark em uma coluna `DataAlteracao` (quando a origem oferecer) para reduzir a janela.
- Verificações de qualidade de dados por coluna (proporção de nulos, chaves duplicadas) junto com a trava de volume.
- Emitir métricas de execução (linhas, duração, erros) para uma tabela ou dashboard de monitoramento.
- Orquestrar com Airflow/Prefect em vez do agendador do sistema operacional.
