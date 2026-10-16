import pandas as pd
import sqlalchemy


class FonteNaoSuportada(RuntimeError):
    pass


def conectar_fonte(url):
    if not url.startswith("sqlite:///"):
        raise FonteNaoSuportada(
            "esta versao publica so le de um SQLite local (FONTE_URL=sqlite:///...); "
            "rode scripts/preparar_demo.py para gerar a base sintetica"
        )
    return sqlalchemy.create_engine(url, pool_pre_ping=True)


def ler_view(engine, nome_view, colunas, filtro_origem, corte):
    campos = ", ".join(f"[{nome}]" for nome, _ in colunas)
    query = f"SELECT {campos} FROM [{nome_view}]"
    parametros = {}

    if filtro_origem:
        query += f" WHERE {filtro_origem}"
        parametros["corte"] = corte.strftime("%Y-%m-%d %H:%M:%S")

    with engine.connect() as conexao:
        return pd.read_sql(sqlalchemy.text(query), conexao, params=parametros)
