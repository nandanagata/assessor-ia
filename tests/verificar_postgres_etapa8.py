r"""Compara a linha de base com a Etapa 8 em tabelas TEMP do Postgres.

Usa o SQL_URL local; não altera tabelas reais e não chama modelos/JEV/Google.
Execute da raiz: .venv\Scripts\python.exe tests/verificar_postgres_etapa8.py
"""

import hashlib
import io
import json
import socket
import sys
import types
import uuid
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import psycopg2
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
# Guarde apenas a conexão e o resolvedor reais, antes das proteções da suíte.
conectar_real = psycopg2.connect
resolver_real = socket.getaddrinfo
sql_url = dotenv_values(ROOT / ".env").get("SQL_URL")

import test_etapa8 as teste

base = teste.base


class ConexaoContada:
    """Conta commits; mantém a sessão TEMP aberta para conferir o resultado."""
    def __init__(self, conn):
        self.conn = conn
        self.commits = 0
        self.rollbacks = 0
        self.fechamentos = 0

    def cursor(self):
        return self.conn.cursor()

    def commit(self):
        self.conn.commit()
        self.commits += 1

    def rollback(self):
        self.conn.rollback()
        self.rollbacks += 1

    def close(self):
        self.fechamentos += 1


def carregar_original(zip_base, caminho):
    modulo = types.ModuleType("linha_base_" + Path(caminho).stem)
    exec(compile(zip_base.read("Assessor/" + caminho), caminho, "exec"), modulo.__dict__)
    return modulo


def estado(conn, tabela, marcador):
    with conn.cursor() as cur:
        if tabela == "transactions":
            cur.execute("SELECT id, amount, description, source_text FROM transactions WHERE source_text = %s ORDER BY id", (marcador,))
        else:
            cur.execute("SELECT id, title, start_time, source_text FROM events WHERE source_text = %s ORDER BY id", (marcador,))
        return [[str(valor) for valor in row] for row in cur.fetchall()]


def verificar():
    if not sql_url:
        raise RuntimeError("SQL_URL não encontrado no .env local")
    zip_path = Path.home() / "Downloads" / "Assessor.zip"
    if not zip_path.is_file():
        raise RuntimeError("A cópia de referência Downloads/Assessor.zip não foi encontrada")
    # Única conexão de rede permitida nesta verificação: o Postgres configurado.
    with patch("socket.getaddrinfo", resolver_real):
        conn = conectar_real(sql_url, connect_timeout=5)
    evidencias = []
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE transaction_types (id integer PRIMARY KEY, type text)")
            cur.execute("CREATE TEMP TABLE categories (id integer PRIMARY KEY, name text)")
            cur.execute("CREATE TEMP TABLE transactions (id bigserial PRIMARY KEY, amount numeric(14,2), type integer, category_id integer, description text, payment_method varchar(32), occurred_at timestamptz DEFAULT now(), source_text text)")
            cur.execute("CREATE TEMP TABLE events (id bigserial PRIMARY KEY, title text, start_time timestamptz, end_time timestamptz, location text, notes text, source_text text, recorded_at timestamptz DEFAULT now())")
            cur.execute("INSERT INTO transaction_types VALUES (1,'INCOME'),(2,'EXPENSES'),(3,'TRANSFER')")
            cur.execute("INSERT INTO categories VALUES (13,'OUTROS')")
        conn.commit()
        with zipfile.ZipFile(zip_path) as zip_base:
            financeiro_base = carregar_original(zip_base, "app/tools/financeiro.py")
            agenda_base = carregar_original(zip_base, "app/tools/agenda.py")
            juiz_base = carregar_original(zip_base, "app/juiz.py")
        for nome in ("add_transaction", "update_transaction", "add_event"):
            for modo in ("antes_recusado", "depois_recusado", "depois_aprovado"):
                marcador = "E8-" + nome + "-" + uuid.uuid4().hex[:10]
                tabela = "events" if nome == "add_event" else "transactions"
                if nome == "update_transaction":
                    with conn.cursor() as cur:
                        cur.execute("INSERT INTO transactions (amount,type,category_id,description,source_text) VALUES (10,2,13,'original',%s) RETURNING id", (marcador,))
                        registro_id = cur.fetchone()[0]
                    conn.commit()
                    args = {"id": registro_id, "amount": 99, "description": marcador}
                elif nome == "add_transaction":
                    args = {"amount": 30, "description": marcador, "source_text": marcador}
                else:
                    args = {"title": marcador, "source_text": marcador, "start_time": "2026-10-28T15:00:00-03:00"}
                antes = estado(conn, tabela, marcador)
                conn.rollback()  # encerra somente o SELECT anterior
                contada = ConexaoContada(conn)
                aprovado = modo == "depois_aprovado"
                resposta = base.resposta_jev("apoiada" if aprovado else "sem_apoio", .95 if aprovado else .1)
                saida = io.StringIO()
                with redirect_stdout(saida), patch.object(base.juiz, "TYPESAFE_API_KEY", "teste-local"), patch("urllib.request.urlopen", return_value=resposta):
                    if modo == "antes_recusado":
                        modulo = agenda_base if tabela == "events" else financeiro_base
                        with patch.object(modulo, "get_conn", return_value=contada):
                            retorno = getattr(modulo, nome).invoke(args)
                        assert retorno.get("status") == "ok", nome
                        assert contada.commits == 1
                        juiz_base.no_juiz({"messages": [
                            base.HumanMessage(content=marcador),
                            base.AIMessage(content="", tool_calls=[{"name": nome, "args": args, "id": "prova"}]),
                            base.ToolMessage(content=json.dumps(retorno, default=str), name=nome, tool_call_id="prova"),
                            base.AIMessage(content="Resposta candidata de teste."),
                        ]})
                    else:
                        base.rapido.respostas.clear()
                        base.especialista.respostas.clear()
                        teste.programar_turno([(nome, args)], "agenda" if tabela == "events" else "financeiro")
                        with patch.object(base.db.psycopg2, "connect", return_value=contada):
                            base.graph.executar_fluxo_assessor(marcador, uuid.uuid4().hex, "prova-etapa8")
                depois = estado(conn, tabela, marcador)
                conn.rollback()
                mudou = depois != antes
                esperado = modo != "depois_recusado"
                assert mudou == esperado, (nome, modo, antes, depois)
                assert contada.commits == (1 if esperado else 0), (nome, modo)
                if nome != "update_transaction":
                    assert len(depois) == (1 if esperado else 0)
                elif esperado:
                    assert depois[0][1] == "99.00"
                rotulo = next(linha for linha in saida.getvalue().splitlines() if linha.startswith("[juiz]"))
                evidencias.append({"tool": nome, "modo": modo, "marcador": marcador, "antes": antes, "juiz": rotulo, "depois": depois, "commits": contada.commits, "rollbacks": contada.rollbacks})
                print(nome, modo, rotulo, "commits=" + str(contada.commits), "OK")
        relatorio = {
            "ambiente": "Postgres real, tabelas TEMP; modelos e JEV simulados; nenhum evento real no Google",
            "linha_base_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
            "casos": evidencias,
        }
        (ROOT / "tests" / "evidencias_etapa8.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
        print("9 comparações OK. Tabelas temporárias serão descartadas ao fechar a conexão.")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        verificar()
    except Exception as erro:
        # Erros de conexão podem conter hostname e usuário. Não exponha o URL.
        print("Verificação não concluída:", type(erro).__name__)
        sys.exit(1)
