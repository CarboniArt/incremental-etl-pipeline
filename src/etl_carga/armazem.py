import datetime as dt
import decimal
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

WRITE_TRUNCATE = "WRITE_TRUNCATE"
WRITE_APPEND = "WRITE_APPEND"


class TabelaNaoEncontrada(LookupError):
    pass


@dataclass(frozen=True)
class Tabela:
    nome: str
    num_rows: int


def _valor_sql(valor):
    if valor is None or valor is pd.NA or valor is pd.NaT:
        return None
    if isinstance(valor, float) and pd.isna(valor):
        return None
    if isinstance(valor, pd.Timestamp):
        return valor.to_pydatetime().strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(valor, dt.datetime):
        return valor.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(valor, dt.date):
        return valor.isoformat()
    if isinstance(valor, decimal.Decimal):
        return str(valor)
    if hasattr(valor, "item"):
        return valor.item()
    return valor


class ArmazemLocal:
    def __init__(self, arquivo):
        self.arquivo = Path(arquivo)
        if not self.arquivo.is_file():
            raise TabelaNaoEncontrada(
                f"armazem {self.arquivo} nao existe; rode scripts/preparar_demo.py"
            )

    def _conectar(self):
        return sqlite3.connect(self.arquivo)

    def get_table(self, nome):
        with self._conectar() as conexao:
            existe = conexao.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (nome,)
            ).fetchone()
            if not existe:
                raise TabelaNaoEncontrada(nome)
            (total,) = conexao.execute(f"SELECT COUNT(*) FROM `{nome}`").fetchone()
        return Tabela(nome, total)

    def query(self, sql, parametros=None):
        with self._conectar() as conexao:
            conexao.row_factory = sqlite3.Row
            return conexao.execute(sql, parametros or {}).fetchall()

    def transacao(self, comandos):
        conexao = self._conectar()
        try:
            with conexao:
                for sql, parametros in comandos:
                    conexao.execute(sql, parametros or {})
        finally:
            conexao.close()

    def load_table_from_dataframe(self, df, destino, schema, write_disposition=WRITE_TRUNCATE):
        self.get_table(destino)
        nomes = [nome for nome, _ in schema]
        campos = ", ".join(f"`{nome}`" for nome in nomes)
        marcadores = ", ".join("?" for _ in nomes)
        linhas = [
            tuple(_valor_sql(valor) for valor in linha)
            for linha in df[nomes].itertuples(index=False, name=None)
        ]

        conexao = self._conectar()
        try:
            with conexao:
                if write_disposition == WRITE_TRUNCATE:
                    conexao.execute(f"DELETE FROM `{destino}`")
                conexao.executemany(
                    f"INSERT INTO `{destino}` ({campos}) VALUES ({marcadores})", linhas
                )
        finally:
            conexao.close()
