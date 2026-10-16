-- Origem simulada: base do sistema de planejamento da producao (versao sintetica).
-- As views reproduzem o formato das views consumidas pela carga original.

CREATE TABLE clientes (
    cod_cliente TEXT PRIMARY KEY,
    nome        TEXT NOT NULL
);

CREATE TABLE papeis (
    cod_papel TEXT PRIMARY KEY,
    descricao TEXT NOT NULL,
    gramatura REAL NOT NULL,
    tipo      TEXT NOT NULL
);

CREATE TABLE pedidos (
    cod_pedido   TEXT PRIMARY KEY,
    data_criacao TEXT NOT NULL,
    data_entrega TEXT,
    cod_cliente  TEXT NOT NULL REFERENCES clientes (cod_cliente),
    cod_papel    TEXT NOT NULL REFERENCES papeis (cod_papel),
    quant_pedida REAL NOT NULL,
    quant_prog   REAL,
    quant_prod   REAL,
    data_apont   TEXT,
    status       TEXT NOT NULL
);

CREATE TABLE programacao (
    maquina     TEXT NOT NULL,
    cod_pedido  TEXT NOT NULL REFERENCES pedidos (cod_pedido),
    data_inicio TEXT NOT NULL,
    data_fim    TEXT NOT NULL,
    sequencia   INTEGER NOT NULL
);

CREATE TABLE bobinas (
    cod_bobina      TEXT PRIMARY KEY,
    cod_pedido      TEXT NOT NULL REFERENCES pedidos (cod_pedido),
    data_producao   TEXT NOT NULL,
    turma           TEXT NOT NULL,
    tipo_maquina    TEXT NOT NULL,
    maquina         TEXT NOT NULL,
    na_fila_balanca INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX ix_pedidos_criacao ON pedidos (data_criacao);

CREATE VIEW vw_ConsultaPedidos AS
SELECT
    p.cod_pedido   AS CodPedido,
    p.data_criacao AS DataCriacao,
    p.data_entrega AS DataEntrega,
    c.cod_cliente  AS CodCliente,
    c.nome         AS Cliente,
    pa.cod_papel   AS CodPapel,
    pa.descricao   AS Papel,
    pa.gramatura   AS Gramatura,
    pa.tipo        AS TipoPapel,
    p.quant_pedida AS QuantPedida,
    p.quant_prog   AS QuantProg,
    p.quant_prod   AS QuantProd,
    p.data_apont   AS DataApont,
    p.status       AS StatusPedido
FROM pedidos p
JOIN clientes c ON c.cod_cliente = p.cod_cliente
JOIN papeis pa  ON pa.cod_papel = p.cod_papel;

CREATE VIEW vw_PedidosProgramadosMaquina AS
SELECT
    pr.maquina          AS Maquina,
    p.cod_pedido        AS CodPedido,
    p.data_criacao      AS DataCriacao,
    DATE(p.data_entrega) AS DataEntrega,
    c.cod_cliente       AS CodCliente,
    c.nome              AS Cliente,
    pa.cod_papel        AS CodPapel,
    pa.descricao        AS Papel,
    pa.gramatura        AS Gramatura,
    p.quant_pedida      AS QuantPedida,
    p.quant_prog        AS QuantProg,
    p.quant_prod        AS QuantProd,
    pr.data_inicio      AS DataInicio,
    pr.data_fim         AS DataFim,
    pr.sequencia        AS Sequencia
FROM programacao pr
JOIN pedidos p  ON p.cod_pedido = pr.cod_pedido
JOIN clientes c ON c.cod_cliente = p.cod_cliente
JOIN papeis pa  ON pa.cod_papel = p.cod_papel;

CREATE VIEW vw_BobinasFilaBalanca AS
SELECT
    b.cod_bobina    AS CodBobina,
    pa.cod_papel    AS CodPapel,
    pa.descricao    AS Papel,
    pa.gramatura    AS Gramatura,
    p.cod_pedido    AS CodPedido,
    c.cod_cliente   AS CodCliente,
    c.nome          AS Cliente,
    b.data_producao AS DataProducao,
    b.turma         AS Turma,
    b.tipo_maquina  AS TipoMaquina_Origem,
    b.maquina       AS Maquina_Origem
FROM bobinas b
JOIN pedidos p  ON p.cod_pedido = b.cod_pedido
JOIN clientes c ON c.cod_cliente = p.cod_cliente
JOIN papeis pa  ON pa.cod_papel = p.cod_papel
WHERE b.na_fila_balanca = 1;
