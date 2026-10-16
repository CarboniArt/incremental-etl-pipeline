import decimal

import pandas as pd

COLUNA_CARGA = ("data_carga", "DATETIME")


def montar_schema(colunas):
    return [*colunas, COLUNA_CARGA]


def tratar_tipos(df, colunas):
    for nome, tipo in colunas:
        if nome not in df.columns:
            df[nome] = pd.NA

        serie = df[nome]

        if tipo == "STRING":
            df[nome] = serie.astype("string").str.strip().replace({"": pd.NA})
        elif tipo == "INT64":
            df[nome] = pd.to_numeric(serie, errors="coerce").astype("Int64")
        elif tipo == "FLOAT64":
            df[nome] = pd.to_numeric(serie, errors="coerce")
        elif tipo == "NUMERIC":
            df[nome] = pd.to_numeric(serie, errors="coerce").apply(
                lambda x: decimal.Decimal(str(x)) if pd.notna(x) else None
            )
        elif tipo == "DATE":
            df[nome] = pd.to_datetime(serie, errors="coerce").dt.date
        elif tipo == "DATETIME":
            data = pd.to_datetime(serie, errors="coerce")
            if getattr(data.dtype, "tz", None) is not None:
                data = data.dt.tz_localize(None)
            df[nome] = data

    return df[[nome for nome, _ in colunas]]
