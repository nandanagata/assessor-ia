import psycopg2
from threading import Lock
from pymongo import MongoClient
from app.config.config import MONGODB_URI, SQL_URL

# Conexão do MongoDB
_mongo = MongoClient(MONGODB_URI)
db = _mongo["assessor"]
col_sessoes = db["sessoes"]

col_sessoes.create_index("session_id")
col_sessoes.create_index("iniciada_em")

# Cada turno tem sua própria conexão. O identificador já é usado pelo monitor.
# A conexão fica só aqui: não vai para o prompt nem para o MemorySaver.
_transacoes = {}


def iniciar_transacao(turno_id):
    _transacoes[turno_id] = {
        "conexao": None, "lock": Lock(), "escritas": 0,
        "falhou": False, "google": [],
    }


def transacao_atual(config):
    turno_id = (config or {}).get("metadata", {}).get("assessor_turno_id")
    return _transacoes.get(turno_id)


def get_conn(config=None):
    transacao = transacao_atual(config)
    if transacao is None:
        # Chamada direta ou MCP: preserva o funcionamento anterior.
        return psycopg2.connect(SQL_URL)

    # Uma ferramenta de cada vez nesta conexão; outros turnos têm outro lock.
    transacao["lock"].acquire()
    try:
        if transacao["falhou"]:
            raise RuntimeError("Uma operação deste turno falhou; as alterações serão desfeitas.")
        if transacao["conexao"] is None:
            transacao["conexao"] = psycopg2.connect(SQL_URL)
        return transacao["conexao"]
    except Exception:
        transacao["falhou"] = True
        transacao["lock"].release()
        raise


def confirmar_operacao(conn, config=None):
    transacao = transacao_atual(config)
    if transacao is None:
        conn.commit()
    else:
        # O SQL foi executado. Quem dá o commit é concluir_transacao.
        transacao["escritas"] += 1


def desfazer_operacao(conn, config=None):
    transacao = transacao_atual(config)
    if transacao is None:
        if conn is not None:
            conn.rollback()
    else:
        # Uma falha impede confirmar as outras escritas do mesmo turno.
        transacao["falhou"] = True


def fechar_conexao(conn, config=None):
    if conn is None:
        return
    transacao = transacao_atual(config)
    if transacao is None:
        conn.close()
    else:
        transacao["lock"].release()


def adiar_google(argumentos, config):
    transacao = transacao_atual(config)
    if transacao is None:
        return False
    with transacao["lock"]:
        transacao["google"].append(argumentos)
    return True


def concluir_transacao(turno_id, aprovado):
    transacao = _transacoes.pop(turno_id, None)
    resultado = {"escritas": 0, "confirmado": False, "falhou": False, "google": []}
    if transacao is None:
        return resultado

    resultado["escritas"] = transacao["escritas"]
    resultado["falhou"] = transacao["falhou"]
    if transacao["google"] and not transacao["escritas"]:
        # O envio externo precisa acompanhar um registro local confirmado.
        resultado["falhou"] = True
    conn = transacao["conexao"]
    if conn is None:
        return resultado

    try:
        if aprovado and not transacao["falhou"] and transacao["escritas"]:
            conn.commit()
            resultado["confirmado"] = True
            resultado["google"] = transacao["google"]
            print(f"[transacao] {turno_id} commit escritas={transacao['escritas']}")
        else:
            conn.rollback()
            print(f"[transacao] {turno_id} rollback escritas={transacao['escritas']}")
    except Exception as erro:
        resultado["falhou"] = True
        print(f"[transacao] {turno_id} erro {type(erro).__name__}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return resultado
