import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ / ".env")

FONTE_URL = os.getenv("FONTE_URL", f"sqlite:///{(RAIZ / 'data' / 'fonte.db').as_posix()}")
ARMAZEM_ARQUIVO = Path(os.getenv("ARMAZEM_ARQUIVO", RAIZ / "data" / "armazem.db"))

ARQUIVO_TRAVA = RAIZ / "carga.lock"
PASTA_LOG = RAIZ / "logs"

TRAVA_EXPIRA_MIN = int(os.getenv("TRAVA_EXPIRA_MIN", 25))
TENTATIVAS = int(os.getenv("TENTATIVAS", 3))
ESPERA_ENTRE_TENTATIVAS = int(os.getenv("ESPERA_ENTRE_TENTATIVAS", 20))
MESES_JANELA = int(os.getenv("MESES_JANELA", 3))

SUFIXO_STAGING = "__STG"

LIMITE_QUEDA = 0.5
MINIMO_PARA_CHECAR = 1000

VIEWS = {
    "vw_ConsultaPedidos": {
        "tabela_destino": "PEDIDOS",
        "filtro_origem": "[DataCriacao] >= :corte",
        "filtro_destino": "DataCriacao >= :corte",
        "colunas": [
            ("CodPedido", "STRING"),
            ("DataCriacao", "DATETIME"),
            ("DataEntrega", "DATETIME"),
            ("CodCliente", "STRING"),
            ("Cliente", "STRING"),
            ("CodPapel", "STRING"),
            ("Papel", "STRING"),
            ("Gramatura", "NUMERIC"),
            ("TipoPapel", "STRING"),
            ("QuantPedida", "FLOAT64"),
            ("QuantProg", "FLOAT64"),
            ("QuantProd", "FLOAT64"),
            ("DataApont", "DATETIME"),
            ("StatusPedido", "STRING"),
        ],
    },
    "vw_PedidosProgramadosMaquina": {
        "tabela_destino": "PEDIDOS_PROGRAMADOS_MAQUINA",
        "filtro_origem": "[DataCriacao] >= :corte",
        "filtro_destino": "DataCriacao >= :corte",
        "colunas": [
            ("Maquina", "STRING"),
            ("CodPedido", "STRING"),
            ("DataCriacao", "DATETIME"),
            ("DataEntrega", "DATE"),
            ("CodCliente", "STRING"),
            ("Cliente", "STRING"),
            ("CodPapel", "STRING"),
            ("Papel", "STRING"),
            ("Gramatura", "FLOAT64"),
            ("QuantPedida", "FLOAT64"),
            ("QuantProg", "FLOAT64"),
            ("QuantProd", "FLOAT64"),
            ("DataInicio", "DATETIME"),
            ("DataFim", "DATETIME"),
            ("Sequencia", "INT64"),
        ],
    },
    "vw_BobinasFilaBalanca": {
        "tabela_destino": "BOBINAS_FILA_BALANCA",
        "filtro_origem": None,
        "filtro_destino": None,
        "colunas": [
            ("CodBobina", "STRING"),
            ("CodPapel", "STRING"),
            ("Papel", "STRING"),
            ("Gramatura", "FLOAT64"),
            ("CodPedido", "STRING"),
            ("CodCliente", "STRING"),
            ("Cliente", "STRING"),
            ("DataProducao", "DATETIME"),
            ("Turma", "STRING"),
            ("TipoMaquina_Origem", "STRING"),
            ("Maquina_Origem", "STRING"),
        ],
    },
}
