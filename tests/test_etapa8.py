"""Testes da regra da Etapa 8, com modelos e SQL simulados."""

import copy
import json
import re
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch

import test_revisao as base
from langchain_core.messages import AIMessage

db = base.db
graph = base.graph
juiz = base.juiz


class ConexaoMemoria:
    """Simula somente o estado transacional; não substitui o teste Postgres."""
    def __init__(self):
        self.salvo = {"transactions": {}, "events": {}}
        self.salvo["transactions"][1] = {
            "id": 1, "amount": 10, "type": 2, "category_id": 13,
            "description": "original", "payment_method": "debito",
            "occurred_at": datetime.now(timezone.utc), "source_text": "original",
        }
        self.rascunho = copy.deepcopy(self.salvo)
        self.commits = 0
        self.rollbacks = 0
        self.fechada = False
        self.erro_commit = False
        self.erro_sql = False
        self.sqls = []

    def cursor(self):
        return CursorMemoria(self)

    def commit(self):
        if self.erro_commit:
            raise RuntimeError("Commit simulado indisponível")
        self.commits += 1
        self.salvo = copy.deepcopy(self.rascunho)

    def rollback(self):
        self.rollbacks += 1
        self.rascunho = copy.deepcopy(self.salvo)

    def close(self):
        self.fechada = True


class CursorMemoria:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.conn.sqls.append((sql, params))
        texto = " ".join(sql.split())
        agora = datetime.now(timezone.utc)
        if self.conn.erro_sql:
            raise RuntimeError("Erro SQL simulado")
        if texto.startswith("INSERT INTO transactions"):
            novo = max(self.conn.rascunho["transactions"], default=0) + 1
            amount, tipo, categoria, descricao, pagamento, data, fonte = params
            self.conn.rascunho["transactions"][novo] = {
                "id": novo, "amount": amount, "type": tipo, "category_id": categoria,
                "description": descricao, "payment_method": pagamento,
                "occurred_at": data or agora, "source_text": fonte,
            }
            self.rows = [(novo, data or agora)]
        elif texto.startswith("UPDATE transactions"):
            campos = re.findall(r"(\w+) = %s", texto.split("WHERE")[0])
            row = self.conn.rascunho["transactions"].get(params[-1])
            if row:
                row.update(dict(zip(campos, params[:-1])))
            self.rowcount = int(row is not None)
        elif texto.startswith("INSERT INTO events"):
            novo = max(self.conn.rascunho["events"], default=0) + 1
            titulo, inicio, fim, local, notas, fonte = params
            self.conn.rascunho["events"][novo] = {
                "id": novo, "title": titulo, "start_time": inicio,
                "end_time": fim, "location": local, "notes": notas, "source_text": fonte,
            }
            self.rows = [(novo, inicio, fim)]
        elif texto.startswith("WITH base_amount"):
            valores = self.conn.rascunho["transactions"].values()
            gastos = sum(r["amount"] for r in valores if r["type"] == 2)
            receitas = sum(r["amount"] for r in valores if r["type"] == 1)
            self.rows = [(gastos, receitas, receitas - gastos)]
        elif "FROM transactions t" in texto and "WHERE t.id = %s" in texto:
            r = self.conn.rascunho["transactions"].get(params[0])
            self.rows = [] if not r else [(r["id"], r["occurred_at"], r["amount"], "EXPENSES", "OUTROS", r["description"], r["payment_method"], r["source_text"])]
        else:
            raise AssertionError("SQL não previsto no teste simulado: " + texto)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def close(self):
        pass


def programar_turno(chamadas, dominio="financeiro", texto="Operação registrada."):
    base.rapido.respostas.extend([
        AIMessage(content="CATEGORIA: APROVADO"),
        AIMessage(content="ROUTE=" + dominio),
        AIMessage(content=texto),
        AIMessage(content="STATUS: APROVADO\nRESPOSTA:\n" + texto),
    ])
    base.especialista.respostas.extend([
        AIMessage(content="", tool_calls=[{"name": nome, "args": args, "id": "tool-" + str(i)} for i, (nome, args) in enumerate(chamadas)]),
        AIMessage(content=json.dumps({"dominio": dominio, "resposta": texto})),
    ])


class Etapa8(unittest.TestCase):
    def setUp(self):
        self.assertFalse(db._transacoes)
        base.rapido.respostas.clear()
        base.especialista.respostas.clear()
        self.conn = ConexaoMemoria()
        self.antes = copy.deepcopy(self.conn.salvo)
        self.session = str(uuid.uuid4())
        self.user = "etapa8-" + uuid.uuid4().hex[:8]
        self.conectar_patch = patch.object(db.psycopg2, "connect", return_value=self.conn)
        self.conectar = self.conectar_patch.start()
        self.addCleanup(self.conectar_patch.stop)
        self.chave = patch.object(juiz, "TYPESAFE_API_KEY", "teste-local")
        self.chave.start()
        self.addCleanup(self.chave.stop)
        self.http = patch.object(juiz.urllib.request, "urlopen", return_value=base.resposta_jev())
        self.jev = self.http.start()
        self.addCleanup(self.http.stop)

    def rodar(self, chamadas, aprovado=True, dominio="financeiro"):
        programar_turno(chamadas, dominio)

        def julgar(*args, **kwargs):
            self.evidencia_juiz = json.loads(args[0].data)["state"]["evidencia"]
            self.assertEqual(self.conn.commits, 0)
            self.assertFalse(self.conn.fechada)
            self.assertEqual(self.conn.salvo, self.antes)
            return base.resposta_jev("apoiada" if aprovado else "sem_apoio", .95 if aprovado else .1)

        self.jev.side_effect = julgar
        return graph.executar_fluxo_assessor("Pedido de teste " + self.user, self.session, self.user)

    def tearDown(self):
        self.assertFalse(db._transacoes, "A conexão do turno não foi removida")

    def test_tres_tools_aprovam_uma_vez_ou_desfazem(self):
        casos = [
            ("add_transaction", {"amount": 30, "source_text": "TESTE-CRIAR"}, "financeiro"),
            ("update_transaction", {"id": 1, "amount": 30}, "financeiro"),
            ("add_event", {"title": "TESTE-EVENTO", "source_text": "TESTE-EVENTO", "start_time": "2026-10-28T15:00:00-03:00"}, "agenda"),
        ]
        for nome, args, dominio in casos:
            for aprovado in (False, True):
                with self.subTest(tool=nome, aprovado=aprovado):
                    self.conn = ConexaoMemoria()
                    self.antes = copy.deepcopy(self.conn.salvo)
                    self.conectar.return_value = self.conn
                    self.session = str(uuid.uuid4())
                    texto = self.rodar([(nome, args)], aprovado, dominio)
                    self.assertTrue(self.conn.fechada)
                    if aprovado:
                        self.assertEqual(self.conn.commits, 1)
                        self.assertNotEqual(self.conn.salvo, self.antes)
                        self.assertEqual(texto, "Operação registrada.")
                    else:
                        self.assertEqual(self.conn.commits, 0)
                        self.assertEqual(self.conn.salvo, self.antes)
                        self.assertIn("Nenhuma alteração", texto)

    def test_leitura_no_turno_enxerga_escrita_ainda_pendente(self):
        self.rodar([("add_transaction", {"amount": 20, "source_text": "TESTE-LEITURA"}), ("saldo_total", {})])
        self.assertEqual(self.conectar.call_count, 1)
        self.assertEqual(self.conn.commits, 1)
        self.assertIn('"total_expenses": 30', self.evidencia_juiz)

    def test_duas_escritas_recusadas_sao_desfeitas_juntas(self):
        self.rodar([("add_transaction", {"amount": 20, "source_text": "TESTE-A"}), ("update_transaction", {"id": 1, "amount": 40})], False)
        self.assertEqual(self.conn.salvo, self.antes)
        self.assertEqual(self.conn.commits, 0)

    def test_chave_ausente_desfaz_e_monitor_marca_erro(self):
        juiz.TYPESAFE_API_KEY = None
        programar_turno([("add_transaction", {"amount": 30, "source_text": "TESTE-SEM-CHAVE"})])
        graph.executar_fluxo_assessor("Registrar teste", self.session, self.user)
        self.assertEqual(self.conn.salvo, self.antes)
        self.jev.assert_not_called()
        self.assertEqual(base.observabilidade.listar_turnos()[-1]["status"], "erro")

    def test_timeout_do_juiz_desfaz(self):
        programar_turno([("update_transaction", {"id": 1, "amount": 50})])
        self.jev.side_effect = TimeoutError("Timeout simulado")
        graph.executar_fluxo_assessor("Atualizar teste", self.session, self.user)
        self.assertEqual(self.conn.salvo, self.antes)

    def test_resposta_invalida_do_juiz_nao_confirma(self):
        casos = [("apoiada", float("inf")), ("apoiada", float("nan")),
                 ("apoiada", 1.1), ("apoiada", -.1), ("apoiada", True),
                 ("rotulo_desconhecido", .95)]
        for choice, noul in casos:
            with self.subTest(choice=choice, noul=noul):
                self.conn = ConexaoMemoria()
                self.antes = copy.deepcopy(self.conn.salvo)
                self.conectar.return_value = self.conn
                self.session = uuid.uuid4().hex
                self.jev.return_value = base.resposta_jev(choice, noul)
                programar_turno([("add_transaction", {"amount": 20, "source_text": "TESTE-JUIZ-INVALIDO"})])
                texto = graph.executar_fluxo_assessor("Registrar teste", self.session, self.user)
                self.assertEqual(self.conn.commits, 0)
                self.assertEqual(self.conn.salvo, self.antes)
                self.assertIn(juiz.FRASE_SEGURA, texto)
                self.assertEqual(base.observabilidade.listar_turnos()[-1]["status"], "erro")

    def test_resposta_final_vazia_desfaz_sem_julgar_json_interno(self):
        programar_turno([("update_transaction", {"id": 1, "amount": 50})], texto="")
        texto = graph.executar_fluxo_assessor("Atualizar teste", self.session, self.user)
        self.jev.assert_not_called()
        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.salvo, self.antes)
        self.assertIn(juiz.FRASE_SEGURA, texto)

    def test_juiz_nao_reaproveita_resposta_de_outro_turno(self):
        estado = {"messages": [base.HumanMessage(content="Pedido anterior"),
                               AIMessage(content="Resposta anterior aprovada."),
                               base.HumanMessage(content="Pedido atual sem resposta")]}
        resultado = juiz.no_juiz(estado)
        self.jev.assert_not_called()
        self.assertEqual(resultado["veredito_juiz"], "erro")
        self.assertEqual(resultado["messages"][-1]["content"], juiz.FRASE_SEGURA)

    def test_falha_antes_do_juiz_desfaz_no_finally(self):
        programar_turno([("add_transaction", {"amount": 20, "source_text": "TESTE-EXCECAO"})])
        base.rapido.respostas[2] = RuntimeError("Orquestrador indisponível")
        with self.assertRaises(RuntimeError):
            graph.executar_fluxo_assessor("Registrar teste", self.session, self.user)
        self.assertEqual(self.conn.salvo, self.antes)
        self.assertTrue(self.conn.fechada)

    def test_falha_no_commit_nao_informa_sucesso(self):
        self.conn.erro_commit = True
        texto = self.rodar([("add_transaction", {"amount": 20, "source_text": "TESTE-COMMIT"})])
        self.assertIn("Não consegui confirmar", texto)
        self.assertEqual(self.conn.salvo, self.antes)
        self.assertEqual(base.observabilidade.listar_turnos()[-1]["status"], "erro")

    def test_google_so_executa_depois_do_commit(self):
        args_evento = {"title": "TESTE-GOOGLE", "start_time": "2026-10-28T15:00:00-03:00"}
        def enviar(*args, **kwargs):
            self.assertEqual(self.conn.commits, 1)
            self.assertEqual(self.jev.call_count, 1)
            return {"status": "ok", "id": "google-teste"}
        with patch.object(base.calendario_google, "chamar_google_calendar", side_effect=enviar) as google:
            texto = self.rodar([("add_event", {**args_evento, "source_text": "TESTE-GOOGLE"}), ("add_google_event", args_evento)], dominio="agenda")
            google.assert_called_once()
            self.assertIn("envio confirmado", texto)

    def test_recusa_nao_cria_evento_no_google(self):
        args_evento = {"title": "TESTE-GOOGLE", "start_time": "2026-10-28T15:00:00-03:00"}
        with patch.object(base.calendario_google, "chamar_google_calendar") as google:
            self.rodar([("add_event", {**args_evento, "source_text": "TESTE-GOOGLE"}), ("add_google_event", args_evento)], False, "agenda")
            google.assert_not_called()
        self.assertEqual(self.conn.salvo, self.antes)

    def test_falha_google_mantem_evento_local_e_informa(self):
        args_evento = {"title": "TESTE-GOOGLE", "start_time": "2026-10-28T15:00:00-03:00"}
        with patch.object(base.calendario_google, "chamar_google_calendar", return_value={"status": "error", "message": "Sem token"}):
            texto = self.rodar([("add_event", {**args_evento, "source_text": "TESTE-GOOGLE"}), ("add_google_event", args_evento)], dominio="agenda")
        self.assertEqual(len(self.conn.salvo["events"]), 1)
        self.assertIn("registro local foi salvo", texto)

    def test_mongo_guarda_so_a_resposta_final_recusada(self):
        texto = self.rodar([("add_transaction", {"amount": 20, "source_text": "TESTE-MONGO"})], False)
        doc = base.memory.col_sessoes.find_one({"session_id": self.session})
        self.assertEqual(doc["mensagens"][-1]["content"], texto)
        self.assertEqual(self.conn.salvo, self.antes)
        self.assertEqual(base.observabilidade.listar_turnos()[-1]["status"], "bloqueado")

    def test_aprovacao_anterior_nao_autoriza_turno_seguinte(self):
        self.rodar([("add_transaction", {"amount": 20, "source_text": "TESTE-PRIMEIRO"})])
        self.antes = copy.deepcopy(self.conn.salvo)
        nova_conn = ConexaoMemoria()
        nova_conn.salvo = copy.deepcopy(self.antes)
        nova_conn.rascunho = copy.deepcopy(self.antes)
        self.conn = nova_conn
        self.conectar.return_value = nova_conn
        self.rodar([("update_transaction", {"id": 1, "amount": 40})], False)
        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.salvo, self.antes)

    def test_erro_de_negocio_em_uma_tool_aborta_as_demais(self):
        texto = self.rodar([("add_transaction", {"amount": 20, "source_text": "TESTE-VALIDO"}), ("update_transaction", {"id": 1})])
        self.assertEqual(self.conn.salvo, self.antes)
        self.assertIn("Não consegui confirmar", texto)

    def test_update_id_inexistente_aborta_as_demais_escritas(self):
        texto = self.rodar([("add_transaction", {"amount": 20, "source_text": "TESTE-VALIDO"}), ("update_transaction", {"id": 999, "amount": 40})])
        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.salvo, self.antes)
        self.assertIn("Não consegui confirmar", texto)

    def test_google_sem_escrita_local_nao_e_enviado(self):
        with patch.object(base.calendario_google, "chamar_google_calendar") as google:
            programar_turno([("add_google_event", {"title": "TESTE-SEM-LOCAL", "start_time": "2026-10-28T15:00:00-03:00"})], "agenda")
            texto = graph.executar_fluxo_assessor("Agendar teste", self.session, self.user)
            google.assert_not_called()
        self.assertIn("Não consegui confirmar", texto)

    def test_argumento_invalido_aborta_as_outras_escritas(self):
        texto = self.rodar([("add_transaction", {"amount": 20, "source_text": "TESTE-VALIDO"}), ("add_transaction", {"amount": -1, "source_text": "TESTE-INVALIDO"})])
        self.assertEqual(self.conn.salvo, self.antes)
        self.assertEqual(self.conn.commits, 0)
        self.assertIn("Não consegui confirmar", texto)

    def test_conexoes_de_turnos_simultaneos_sao_separadas(self):
        barreira = threading.Barrier(2)
        def executar(aprovado):
            turno = uuid.uuid4().hex
            config = {"metadata": {"assessor_turno_id": turno}}
            db.iniciar_transacao(turno)
            conn = db.get_conn(config)
            barreira.wait(timeout=3)
            db.confirmar_operacao(conn, config)
            db.fechar_conexao(conn, config)
            return conn, db.concluir_transacao(turno, aprovado)
        with patch.object(db.psycopg2, "connect", side_effect=lambda *a, **kw: ConexaoMemoria()):
            with ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(executar, True)
                b = pool.submit(executar, False)
                conn_a, resultado_a = a.result(timeout=5)
                conn_b, resultado_b = b.result(timeout=5)
        self.assertIsNot(conn_a, conn_b)
        self.assertTrue(resultado_a["confirmado"])
        self.assertFalse(resultado_b["confirmado"])


if __name__ == "__main__":
    unittest.main()
