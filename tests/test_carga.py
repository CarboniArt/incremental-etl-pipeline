import decimal
import os
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from etl_carga import carga, config
from etl_carga.armazem import ArmazemLocal, TabelaNaoEncontrada
from etl_carga.fonte import FonteNaoSuportada, conectar_fonte
from etl_carga.transformacao import montar_schema, tratar_tipos

SQL = Path(__file__).resolve().parents[1] / "sql"
CORTE = datetime(2026, 7, 1)
MOMENTO = datetime(2026, 10, 8, 9, 0)
VIEW_PEDIDOS = "vw_ConsultaPedidos"


def criar_base(caminho, ddl):
    conexao = sqlite3.connect(caminho)
    conexao.executescript((SQL / ddl).read_text(encoding="utf-8"))
    return conexao


def inserir_pedidos(conexao, quantidade, inicio=datetime(2026, 6, 20), status="Aberto"):
    conexao.execute("INSERT OR IGNORE INTO clientes VALUES ('CLI-0001', 'Cliente 0001')")
    conexao.execute("INSERT OR IGNORE INTO papeis VALUES ('KRA080', 'Papel Kraft 80 g/m2', 80, 'KRAFT')")
    linhas = [
        (
            f"PED-{i:06d}",
            (inicio + pd.Timedelta(hours=6 * i)).strftime("%Y-%m-%d %H:%M:%S"),
            None, "CLI-0001", "KRA080", 10.0 + i, None, None, None, status,
        )
        for i in range(quantidade)
    ]
    conexao.executemany(
        "INSERT OR REPLACE INTO pedidos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", linhas
    )
    conexao.commit()


@pytest.fixture
def ambiente(tmp_path):
    fonte = criar_base(tmp_path / "fonte.db", "fonte.sql")
    criar_base(tmp_path / "armazem.db", "armazem.sql").close()
    engine = conectar_fonte(f"sqlite:///{(tmp_path / 'fonte.db').as_posix()}")
    yield fonte, engine, ArmazemLocal(tmp_path / "armazem.db")
    engine.dispose()
    fonte.close()


def carregar_pedidos(engine, armazem, full=False):
    carga.carregar_view(
        engine, armazem, VIEW_PEDIDOS, config.VIEWS[VIEW_PEDIDOS], MOMENTO, CORTE, full
    )


def total(armazem, tabela, onde="1=1"):
    (linha,) = armazem.query(f"SELECT COUNT(*) AS n FROM `{tabela}` WHERE {onde}")
    return linha["n"]


def test_tratar_tipos_normaliza_cada_tipo():
    colunas = [
        ("texto", "STRING"),
        ("inteiro", "INT64"),
        ("real", "FLOAT64"),
        ("decimal", "NUMERIC"),
        ("dia", "DATE"),
        ("momento", "DATETIME"),
        ("ausente", "STRING"),
    ]
    df = pd.DataFrame(
        {
            "texto": ["  a ", ""],
            "inteiro": ["7", "x"],
            "real": ["1.5", None],
            "decimal": [80, None],
            "dia": ["2026-10-01 13:00", "lixo"],
            "momento": ["2026-10-01 13:45:00", None],
            "extra": [1, 2],
        }
    )

    resultado = tratar_tipos(df, colunas)

    assert list(resultado.columns) == [nome for nome, _ in colunas]
    assert resultado["texto"].tolist()[0] == "a" and pd.isna(resultado["texto"][1])
    assert resultado["inteiro"].tolist()[0] == 7 and pd.isna(resultado["inteiro"][1])
    assert resultado["decimal"][0] == decimal.Decimal("80")
    assert resultado["dia"][0] == date(2026, 10, 1) and pd.isna(resultado["dia"][1])
    assert resultado["momento"][0] == pd.Timestamp("2026-10-01 13:45:00")
    assert resultado["ausente"].isna().all()


def test_schema_ganha_a_coluna_de_carga():
    assert montar_schema([("a", "STRING")]) == [("a", "STRING"), ("data_carga", "DATETIME")]


@pytest.mark.parametrize(
    "atuais,novas,aborta",
    [(999, 0, False), (1000, 500, False), (1000, 499, True), (5000, 4000, False)],
)
def test_conferir_volume(atuais, novas, aborta):
    if aborta:
        with pytest.raises(RuntimeError, match="queda acima de 50%"):
            carga.conferir_volume(atuais, novas)
    else:
        carga.conferir_volume(atuais, novas)


def test_corte_e_o_primeiro_dia_de_tres_meses_atras():
    assert carga.calcular_corte(datetime(2026, 10, 8, 14, 30)) == datetime(2026, 7, 1)
    assert carga.calcular_corte(datetime(2026, 1, 31), meses=1) == datetime(2025, 12, 1)


def test_trava_recente_impede_execucao_concorrente(tmp_path):
    trava = tmp_path / "carga.lock"
    assert carga.obter_trava(trava) is True
    assert carga.obter_trava(trava) is False
    carga.liberar_trava(trava)
    assert not trava.exists()


def test_trava_abandonada_e_assumida(tmp_path):
    trava = tmp_path / "carga.lock"
    trava.write_text("123", encoding="utf-8")
    antigo = time.time() - (config.TRAVA_EXPIRA_MIN + 1) * 60
    os.utime(trava, (antigo, antigo))

    assert carga.obter_trava(trava) is True


def test_fonte_recusa_banco_externo():
    with pytest.raises(FonteNaoSuportada):
        conectar_fonte("mssql+pyodbc:///?odbc_connect=...")


def test_janela_substitui_so_o_periodo_recente(ambiente):
    fonte, engine, armazem = ambiente
    inserir_pedidos(fonte, 60)
    carregar_pedidos(engine, armazem, full=True)
    antigos = total(armazem, "PEDIDOS", "DataCriacao < '2026-07-01'")

    fonte.execute("UPDATE pedidos SET status = 'Faturado'")
    fonte.commit()
    carregar_pedidos(engine, armazem)

    assert total(armazem, "PEDIDOS") == 60
    assert total(armazem, "PEDIDOS", "StatusPedido = 'Faturado'") == 60 - antigos
    assert total(armazem, "PEDIDOS", "DataCriacao < '2026-07-01' AND StatusPedido = 'Aberto'") == antigos
    assert total(armazem, "PEDIDOS__STG") == 0


def test_carga_grava_tipos_legiveis(ambiente):
    fonte, engine, armazem = ambiente
    inserir_pedidos(fonte, 3, inicio=datetime(2026, 9, 1))
    carregar_pedidos(engine, armazem)

    (linha,) = armazem.query("SELECT * FROM PEDIDOS WHERE CodPedido = 'PED-000001'")
    assert linha["DataCriacao"] == "2026-09-01 06:00:00"
    assert linha["Gramatura"] == 80
    assert linha["data_carga"] == "2026-10-08 09:00:00"


def test_view_vazia_aborta_sem_apagar(ambiente):
    fonte, engine, armazem = ambiente
    inserir_pedidos(fonte, 10, inicio=datetime(2026, 9, 1))
    carregar_pedidos(engine, armazem)
    fonte.execute("DELETE FROM pedidos")
    fonte.commit()

    with pytest.raises(RuntimeError, match="0 linhas"):
        carregar_pedidos(engine, armazem)
    assert total(armazem, "PEDIDOS") == 10


def test_staging_ausente_e_erro_explicito(ambiente):
    fonte, engine, armazem = ambiente
    inserir_pedidos(fonte, 5, inicio=datetime(2026, 9, 1))
    armazem.transacao([("DROP TABLE PEDIDOS__STG", None)])

    with pytest.raises(RuntimeError, match="nao cria tabela"):
        carregar_pedidos(engine, armazem)


def test_troca_da_janela_e_atomica(ambiente):
    fonte, engine, armazem = ambiente
    inserir_pedidos(fonte, 8, inicio=datetime(2026, 9, 1))
    carregar_pedidos(engine, armazem)

    schema_quebrado = [("CodPedido", "STRING"), ("ColunaInexistente", "STRING")]
    with pytest.raises(sqlite3.OperationalError):
        carga.trocar_janela(
            armazem, "PEDIDOS", "PEDIDOS__STG", schema_quebrado, "DataCriacao >= :corte", CORTE
        )
    assert total(armazem, "PEDIDOS") == 8


def test_retentativa_desiste_e_devolve_falso(ambiente, monkeypatch):
    _, engine, armazem = ambiente
    chamadas = []

    def falha(*args, **kwargs):
        chamadas.append(1)
        raise RuntimeError("origem fora do ar")

    monkeypatch.setattr(carga, "carregar_view", falha)
    resultado = carga.carregar_com_retentativa(
        engine, armazem, VIEW_PEDIDOS, config.VIEWS[VIEW_PEDIDOS], MOMENTO, CORTE, False, espera=0
    )

    assert resultado is False
    assert len(chamadas) == config.TENTATIVAS


def test_armazem_inexistente(tmp_path):
    with pytest.raises(TabelaNaoEncontrada):
        ArmazemLocal(tmp_path / "nao-existe.db")
