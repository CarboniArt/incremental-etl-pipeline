-- Armazem local (substitui o data warehouse em nuvem da versao original).
-- Cada tabela de destino tem uma staging gemea (<TABELA>__STG) usada na troca da janela.
-- A carga nao cria tabelas: elas precisam existir, como no ambiente original.

CREATE TABLE PEDIDOS (
    CodPedido    TEXT,
    DataCriacao  TEXT,
    DataEntrega  TEXT,
    CodCliente   TEXT,
    Cliente      TEXT,
    CodPapel     TEXT,
    Papel        TEXT,
    Gramatura    NUMERIC,
    TipoPapel    TEXT,
    QuantPedida  REAL,
    QuantProg    REAL,
    QuantProd    REAL,
    DataApont    TEXT,
    StatusPedido TEXT,
    data_carga   TEXT
);

CREATE TABLE PEDIDOS_PROGRAMADOS_MAQUINA (
    Maquina     TEXT,
    CodPedido   TEXT,
    DataCriacao TEXT,
    DataEntrega TEXT,
    CodCliente  TEXT,
    Cliente     TEXT,
    CodPapel    TEXT,
    Papel       TEXT,
    Gramatura   REAL,
    QuantPedida REAL,
    QuantProg   REAL,
    QuantProd   REAL,
    DataInicio  TEXT,
    DataFim     TEXT,
    Sequencia   INTEGER,
    data_carga  TEXT
);

CREATE TABLE BOBINAS_FILA_BALANCA (
    CodBobina          TEXT,
    CodPapel           TEXT,
    Papel              TEXT,
    Gramatura          REAL,
    CodPedido          TEXT,
    CodCliente         TEXT,
    Cliente            TEXT,
    DataProducao       TEXT,
    Turma              TEXT,
    TipoMaquina_Origem TEXT,
    Maquina_Origem     TEXT,
    data_carga         TEXT
);

CREATE TABLE PEDIDOS__STG AS SELECT * FROM PEDIDOS WHERE 0;
CREATE TABLE PEDIDOS_PROGRAMADOS_MAQUINA__STG AS SELECT * FROM PEDIDOS_PROGRAMADOS_MAQUINA WHERE 0;

CREATE INDEX ix_pedidos_criacao ON PEDIDOS (DataCriacao);
CREATE INDEX ix_programados_criacao ON PEDIDOS_PROGRAMADOS_MAQUINA (DataCriacao);
