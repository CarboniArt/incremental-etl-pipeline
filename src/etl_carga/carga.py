import argparse
import logging
import os
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler

from dateutil.relativedelta import relativedelta

from . import config
from .armazem import WRITE_TRUNCATE, ArmazemLocal, TabelaNaoEncontrada
from .fonte import conectar_fonte, ler_view
from .transformacao import montar_schema, tratar_tipos

log = logging.getLogger("carga")


def configurar_log():
    config.PASTA_LOG.mkdir(parents=True, exist_ok=True)

    formato = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%d/%m/%Y %H:%M:%S"
    )

    arquivo = RotatingFileHandler(
        config.PASTA_LOG / "carga.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    arquivo.setFormatter(formato)

    console = logging.StreamHandler()
    console.setFormatter(formato)

    log.setLevel(logging.INFO)
    log.handlers.clear()
    log.addHandler(arquivo)
    log.addHandler(console)


def obter_trava(arquivo_trava=None):
    arquivo_trava = arquivo_trava or config.ARQUIVO_TRAVA
    if os.path.exists(arquivo_trava):
        idade_min = (time.time() - os.path.getmtime(arquivo_trava)) / 60

        if idade_min < config.TRAVA_EXPIRA_MIN:
            log.warning(
                "Execucao anterior ainda em andamento (trava com %.1f min). Saindo.",
                idade_min,
            )
            return False

        log.warning(
            "Trava abandonada com %.1f min (execucao anterior travou). Assumindo.",
            idade_min,
        )

    with open(arquivo_trava, "w", encoding="utf-8") as arquivo:
        arquivo.write(f"{os.getpid()} {datetime.now():%d/%m/%Y %H:%M:%S}")

    return True


def liberar_trava(arquivo_trava=None):
    try:
        os.remove(arquivo_trava or config.ARQUIVO_TRAVA)
    except OSError:
        pass


def caminho_tabela(tabela_destino):
    return tabela_destino


def caminho_staging(tabela_destino):
    return f"{caminho_tabela(tabela_destino)}{config.SUFIXO_STAGING}"


def parametros_corte(corte):
    return {"corte": corte.strftime("%Y-%m-%d %H:%M:%S")}


def garantir_tabela(armazem, caminho, papel):
    try:
        return armazem.get_table(caminho)
    except TabelaNaoEncontrada:
        raise RuntimeError(
            f"tabela {papel} `{caminho}` nao existe no armazem e este script "
            "nao cria tabela; crie-a com sql/armazem.sql "
            "(scripts/preparar_demo.py faz isso na demo)"
        ) from None


def linhas_na_tabela(armazem, tabela_destino):
    return garantir_tabela(
        armazem, caminho_tabela(tabela_destino), "de destino"
    ).num_rows


def linhas_na_janela(armazem, tabela_destino, filtro_destino, corte):
    destino = caminho_tabela(tabela_destino)
    garantir_tabela(armazem, destino, "de destino")

    consulta = f"SELECT COUNT(*) AS total FROM `{destino}` WHERE {filtro_destino}"
    (linha,) = armazem.query(consulta, parametros_corte(corte))
    return linha["total"]


def conferir_volume(linhas_atuais, linhas_novas):
    if linhas_atuais < config.MINIMO_PARA_CHECAR:
        return

    if linhas_novas < linhas_atuais * config.LIMITE_QUEDA:
        raise RuntimeError(
            f"lote com {linhas_novas} linhas contra {linhas_atuais} ja gravadas "
            f"(queda acima de {(1 - config.LIMITE_QUEDA) * 100:.0f}%); carga abortada "
            "para nao apagar dado bom"
        )


def gravar_staging(armazem, df, tabela_destino, schema):
    staging = caminho_staging(tabela_destino)
    garantir_tabela(armazem, staging, "de staging")

    armazem.load_table_from_dataframe(df, staging, schema, write_disposition=WRITE_TRUNCATE)

    return staging


def limpar_staging(armazem, staging):
    try:
        armazem.transacao([(f"DELETE FROM `{staging}`", None)])
    except Exception as erro:
        log.warning("Nao foi possivel esvaziar a staging %s: %s", staging, erro)


def trocar_janela(armazem, tabela_destino, staging, schema, filtro_destino, corte):
    campos = ", ".join(f"`{nome}`" for nome, _ in schema)
    destino = caminho_tabela(tabela_destino)

    armazem.transacao(
        [
            (f"DELETE FROM `{destino}` WHERE {filtro_destino}", parametros_corte(corte)),
            (f"INSERT INTO `{destino}` ({campos}) SELECT {campos} FROM `{staging}`", None),
        ]
    )


def carga_cheia(armazem, df, tabela_destino, schema):
    armazem.load_table_from_dataframe(
        df, caminho_tabela(tabela_destino), schema, write_disposition=WRITE_TRUNCATE
    )


def sobrescrever_janela(armazem, df, tabela_destino, schema, filtro_destino, corte):
    staging = gravar_staging(armazem, df, tabela_destino, schema)

    try:
        trocar_janela(armazem, tabela_destino, staging, schema, filtro_destino, corte)
    finally:
        limpar_staging(armazem, staging)


def carregar_view(engine, armazem, nome_view, config_view, momento_carga, corte, full):
    colunas = config_view["colunas"]
    tabela_destino = config_view["tabela_destino"]
    schema = montar_schema(colunas)

    com_janela = bool(config_view.get("filtro_destino")) and not full
    filtro_origem = config_view.get("filtro_origem") if com_janela else None
    filtro_destino = config_view.get("filtro_destino") if com_janela else None

    inicio = time.time()

    df = ler_view(engine, nome_view, colunas, filtro_origem, corte)
    df = tratar_tipos(df, colunas)
    df["data_carga"] = momento_carga

    if df.empty:
        raise RuntimeError(
            "view retornou 0 linhas; carga abortada para nao apagar dado bom"
        )

    leitura = time.time() - inicio

    if com_janela:
        linhas_atuais = linhas_na_janela(armazem, tabela_destino, filtro_destino, corte)
        conferir_volume(linhas_atuais, len(df))
        sobrescrever_janela(armazem, df, tabela_destino, schema, filtro_destino, corte)
        modo = f"janela desde {corte:%d/%m/%Y}, {linhas_atuais} substituidas"
    else:
        linhas_atuais = linhas_na_tabela(armazem, tabela_destino)
        conferir_volume(linhas_atuais, len(df))
        carga_cheia(armazem, df, tabela_destino, schema)
        modo = "carga cheia"

    log.info(
        "[OK] %s -> %s | %d linhas (%s) | leitura %.1fs | total %.1fs",
        nome_view,
        tabela_destino,
        len(df),
        modo,
        leitura,
        time.time() - inicio,
    )


def carregar_com_retentativa(
    engine, armazem, nome_view, config_view, momento_carga, corte, full, espera=None
):
    espera = config.ESPERA_ENTRE_TENTATIVAS if espera is None else espera
    for tentativa in range(1, config.TENTATIVAS + 1):
        try:
            carregar_view(
                engine, armazem, nome_view, config_view, momento_carga, corte, full
            )
            return True

        except Exception as erro:
            if tentativa == config.TENTATIVAS:
                log.error(
                    "[ERRO] %s (tentativa %d/%d): %s",
                    nome_view,
                    tentativa,
                    config.TENTATIVAS,
                    erro,
                )
                return False

            log.warning(
                "[FALHA] %s (tentativa %d/%d): %s | nova tentativa em %ds",
                nome_view,
                tentativa,
                config.TENTATIVAS,
                erro,
                espera,
            )
            time.sleep(espera)

    return False


def calcular_corte(agora, meses=None):
    meses = config.MESES_JANELA if meses is None else meses
    return (agora - relativedelta(months=meses)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )


def main(argv=None):
    argumentos = argparse.ArgumentParser(description="Carga incremental: sistema de producao -> armazem")
    argumentos.add_argument(
        "--full",
        action="store_true",
        help="recarrega as views inteiras (WRITE_TRUNCATE), ignorando a janela",
    )
    opcoes = argumentos.parse_args(argv)

    configurar_log()

    if not obter_trava():
        return 0

    inicio = time.time()
    corte = calcular_corte(datetime.now())

    log.info(
        "=== Inicio da carga (%s) ===",
        "FULL" if opcoes.full else f"janela desde {corte:%d/%m/%Y %H:%M}",
    )

    engine = None
    erros = 0

    try:
        engine = conectar_fonte(config.FONTE_URL)
        armazem = ArmazemLocal(config.ARMAZEM_ARQUIVO)

        momento_carga = datetime.now().replace(microsecond=0)

        for nome_view, config_view in config.VIEWS.items():
            if not carregar_com_retentativa(
                engine, armazem, nome_view, config_view, momento_carga, corte, opcoes.full
            ):
                erros += 1

    except Exception as erro:
        log.exception("Falha geral na carga: %s", erro)
        erros += 1

    finally:
        if engine is not None:
            engine.dispose()
        liberar_trava()

    log.info("=== Fim da carga em %.1fs (%d erro(s)) ===", time.time() - inicio, erros)

    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
