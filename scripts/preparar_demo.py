import argparse
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA_DADOS = RAIZ / "data"
FONTE = PASTA_DADOS / "fonte.db"
ARMAZEM = PASTA_DADOS / "armazem.db"

MAQUINAS = [("MAQ-01", "Maquina de papel"), ("MAQ-02", "Maquina de papel"), ("REB-01", "Rebobinadeira")]
TURMAS = ["A", "B", "C", "D"]
TIPOS = [("KRAFT", 80, 140), ("OFFSET", 63, 120), ("CARTAO", 180, 300), ("ENVELOPE", 70, 90)]
STATUS_ABERTOS = ["Aberto", "Programado", "Em producao"]


def criar_base(caminho, ddl):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if caminho.exists():
        caminho.unlink()
    conexao = sqlite3.connect(caminho)
    conexao.executescript((RAIZ / "sql" / ddl).read_text(encoding="utf-8"))
    return conexao


def texto(momento):
    return momento.strftime("%Y-%m-%d %H:%M:%S")


def gerar_cadastros(conexao, sorteio):
    clientes = [(f"CLI-{i:04d}", f"Cliente {i:04d}") for i in range(1, 121)]
    papeis = []
    for tipo, minima, maxima in TIPOS:
        for gramatura in sorteio.sample(range(minima, maxima + 1), 5):
            papeis.append((f"{tipo[:3]}{gramatura:03d}", f"Papel {tipo.title()} {gramatura} g/m2", gramatura, tipo))
    conexao.executemany("INSERT INTO clientes VALUES (?, ?)", clientes)
    conexao.executemany("INSERT INTO papeis VALUES (?, ?, ?, ?)", papeis)
    return clientes, papeis


def novo_pedido(numero, criacao, agora, clientes, papeis, sorteio):
    cliente = sorteio.choice(clientes)[0]
    papel = sorteio.choice(papeis)[0]
    pedida = round(sorteio.uniform(2, 60), 3)
    entrega = criacao + timedelta(days=sorteio.randint(10, 45))
    idade = (agora - criacao).days
    if idade > 40:
        status, prog, prod = "Faturado", pedida, round(pedida * sorteio.uniform(0.97, 1.03), 3)
    elif idade > 15:
        status = sorteio.choice(["Produzido", "Em producao"])
        prog, prod = pedida, round(pedida * sorteio.uniform(0.3, 1.0), 3)
    else:
        status = sorteio.choice(STATUS_ABERTOS)
        prog = pedida if status != "Aberto" else None
        prod = round(pedida * sorteio.uniform(0, 0.4), 3) if status == "Em producao" else None
    apont = texto(criacao + timedelta(days=sorteio.randint(1, 10))) if prod else None
    return (
        f"PED-{numero:06d}", texto(criacao), texto(entrega), cliente, papel,
        pedida, prog, prod, apont, status,
    )


def gerar_pedidos(conexao, agora, clientes, papeis, sorteio, dias=200, por_dia=(18, 32), inicio_numero=1):
    pedidos = []
    numero = inicio_numero
    for dia in range(dias, -1, -1):
        base = (agora - timedelta(days=dia)).replace(hour=0, minute=0, second=0, microsecond=0)
        for _ in range(sorteio.randint(*por_dia)):
            criacao = base + timedelta(minutes=sorteio.randint(6 * 60, 22 * 60))
            if criacao > agora:
                continue
            pedidos.append(novo_pedido(numero, criacao, agora, clientes, papeis, sorteio))
            numero += 1
    conexao.executemany("INSERT INTO pedidos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", pedidos)
    return pedidos


def gerar_programacao_e_bobinas(conexao, pedidos, sorteio):
    programados = [p for p in pedidos if p[9] in ("Programado", "Em producao", "Produzido")]
    sequencias = {maquina: 0 for maquina, _ in MAQUINAS}
    programacao, bobinas = [], []
    for pedido in sorted(programados, key=lambda p: p[1]):
        maquina, tipo_maquina = sorteio.choice(MAQUINAS[:2])
        sequencias[maquina] += 1
        inicio = datetime.strptime(pedido[1], "%Y-%m-%d %H:%M:%S") + timedelta(days=sorteio.randint(1, 6))
        fim = inicio + timedelta(hours=sorteio.randint(2, 14))
        programacao.append((maquina, pedido[0], texto(inicio), texto(fim), sequencias[maquina]))
        if pedido[7]:
            for indice in range(sorteio.randint(1, 4)):
                producao = fim + timedelta(minutes=30 * indice)
                bobinas.append((
                    f"BOB-{pedido[0][4:]}-{indice + 1}", pedido[0], texto(producao),
                    sorteio.choice(TURMAS), tipo_maquina, maquina,
                    1 if pedido[9] == "Em producao" and sorteio.random() < 0.6 else 0,
                ))
    conexao.executemany("INSERT INTO programacao VALUES (?, ?, ?, ?, ?)", programacao)
    conexao.executemany("INSERT INTO bobinas VALUES (?, ?, ?, ?, ?, ?, ?)", bobinas)


def preparar(semente):
    sorteio = random.Random(semente)
    agora = datetime.now().replace(microsecond=0)

    fonte = criar_base(FONTE, "fonte.sql")
    with fonte:
        clientes, papeis = gerar_cadastros(fonte, sorteio)
        pedidos = gerar_pedidos(fonte, agora, clientes, papeis, sorteio)
        gerar_programacao_e_bobinas(fonte, pedidos, sorteio)
    fonte.close()

    armazem = criar_base(ARMAZEM, "armazem.sql")
    armazem.close()

    print(f"Origem sintetica: {FONTE} ({len(pedidos)} pedidos)")
    print(f"Armazem vazio:    {ARMAZEM}")


def simular_atualizacao(semente):
    sorteio = random.Random(semente + 1)
    agora = datetime.now().replace(microsecond=0)
    conexao = sqlite3.connect(FONTE)
    with conexao:
        clientes = conexao.execute("SELECT cod_cliente, nome FROM clientes").fetchall()
        papeis = conexao.execute("SELECT cod_papel FROM papeis").fetchall()
        (ultimo,) = conexao.execute("SELECT MAX(CAST(SUBSTR(cod_pedido, 5) AS INTEGER)) FROM pedidos").fetchone()
        novos = [
            novo_pedido(ultimo + i, agora - timedelta(minutes=5 * i), agora, clientes, papeis, sorteio)
            for i in range(1, 41)
        ]
        conexao.executemany("INSERT INTO pedidos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", novos)
        alterados = conexao.execute(
            "UPDATE pedidos SET status = 'Produzido', quant_prod = quant_pedida, data_apont = ? "
            "WHERE status = 'Em producao'",
            (texto(agora),),
        ).rowcount
    conexao.close()
    print(f"Origem atualizada: +{len(novos)} pedidos novos, {alterados} pedidos mudaram de status")


def simular_perda():
    conexao = sqlite3.connect(FONTE)
    with conexao:
        corte = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d %H:%M:%S")
        removidos = conexao.execute(
            "DELETE FROM pedidos WHERE data_criacao >= ? "
            "AND CAST(SUBSTR(cod_pedido, 5) AS INTEGER) % 10 < 8",
            (corte,),
        ).rowcount
    conexao.close()
    print(f"Simulacao de origem incompleta: {removidos} pedidos recentes sumiram da view")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Gera a origem sintetica e o armazem local da demo")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--atualizar", action="store_true", help="simula um dia de movimento na origem")
    grupo.add_argument("--simular-perda", action="store_true", help="apaga parte dos pedidos recentes (dispara a trava de volume)")
    parser.add_argument("--semente", type=int, default=42)
    opcoes = parser.parse_args(argv)

    if (opcoes.atualizar or opcoes.simular_perda) and not FONTE.exists():
        sys.exit("Rode primeiro sem opcoes para criar a origem.")
    if opcoes.atualizar:
        simular_atualizacao(opcoes.semente)
    elif opcoes.simular_perda:
        simular_perda()
    else:
        preparar(opcoes.semente)


if __name__ == "__main__":
    main()
