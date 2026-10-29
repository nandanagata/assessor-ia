from typing import Optional, List
from langchain.tools import tool
from pydantic import BaseModel, Field
from langchain_core.runnables import RunnableConfig
from app.tools.db import get_conn, confirmar_operacao, desfazer_operacao, fechar_conexao

class AddTransactionArgs(BaseModel):
    amount: float = Field(..., gt=0, allow_inf_nan=False, description="Valor da transação (use positivo).")
    source_text: str = Field(..., description="Texto original do usuário.")
    occurred_at: Optional[str] = Field(
        default=None,
        description="Timestamp ISO 8601; se ausente, usa NOW() no banco."
    )
    type_id: Optional[int] = Field(default=2, description="ID em transaction_types (1=INCOME, 2=EXPENSES, 3=TRANSFER).")
    type_name: Optional[str] = Field(default=None, description="""
                                     Nome do tipo: INCOME | EXPENSES | TRANSFER. Caso o usuário não informe o produto ou a situação em que ele realizou um gasto, entra como TRANSFER. Exemplo: 'Fiz um PIX para minha mãe de 8 reais', ele apenas realizou uma transferência para a mãe, não se sabe se foi um gasto ou não.
                                     """)
    category_id: Optional[int] = Field(default=13, description="FK de categories (opcional).")
    category_name: Optional[str] = Field(default=None, description="""
                                         Nome da categoria que irá ser adicionada como categoria da transação (categoria não é tipo nesse caso).

                                        ## Possíveis categorias
                                        - comida → alimentação essencial (refeições básicas do dia a dia, mercado, marmita, etc.)
                                        - besteira → alimentação não essencial (doces, fast food, salgados, bebidas não necessárias, etc.)
                                        - estudo → gastos com educação (cursos, mensalidades, livros, materiais escolares/acadêmicos)
                                        - transporte → locomoção (uber, táxi, ônibus, metrô, combustível, passagens, manutenção básica de transporte)
                                        - saúde → despesas médicas (consultas, exames, remédios, tratamentos, emergências)
                                        - lazer → gastos não essenciais pessoais (roupas, rolês, viagens, entretenimento, hobbies)
                                        - contas → despesas fixas/essenciais (aluguel, luz, água, internet, condomínio, etc.)
                                        - investimento → aplicação de dinheiro ou aquisição de bens com objetivo de valorização (renda fixa/variável, imóveis, reformas, etc.)
                                        - presente → transações sem finalidade financeira direta para outra pessoa (dar ou receber presentes)
                                        - venda → entrada de dinheiro por venda de bens ou serviços
                                        - eletronicos → compra de eletrônicos (celular, fone, computador, videogame, etc.)
                                        - outros → qualquer transação que não se encaixa nas categorias acima
                                         """)
    description: Optional[str] = Field(default=None, description="Descrição (opcional).")
    payment_method: Optional[str] = Field(default=None, description="Forma de pagamento (opcional).")

class QueryTransactionArgs(BaseModel):
    """
    Define os filtros opcionais para busca de transações no banco de dados.
    Todos os campos são opcionais e utilizados para construir a cláusula WHERE da query SQL.
    """

    min_amount: Optional[float] = Field(
        default=None,
        description=(
            "Valor mínimo utilizado no filtro de transação, ou seja, filtra pelos valores que são maiores ou iguais ao valor desse campo."
            "Caso o usuário pergunte por um valor específico, e não um intervalo de busca, esse campo recebe o mesmo valor que o max_amount"
        )
    )
    max_amount: Optional[float] = Field(
        default=None,
        description=(
            "Valor máximo utilizado no filtro de transação, ou seja, filtra pelos valores que são menores ou iguais ao valor desse campo."
            "Caso o usuário pergunte por um valor específico, e não um intervalo de busca, esse campo recebe o mesmo valor que o min_amount"
        )
    )
    type_name: Optional[str] = Field(
        default=None,
        description=(
            "Filtra pelo tipo da transação (INCOME, EXPENSES ou TRANSFER)."
            "O usuário pode inserir nomes em PT-BR, nesses casos serão aplicados os seguintes aliases: "
            "INCOME: entrada, receita, ganho, lucro"
            "EXPENSES: despesa, gasto, paguei, compra, boleto"
            "TRANSFER: transferência, pix, ted, doc, entre contas"
        )
    )
    category_name: Optional[str] = Field(
        default=None,
        description=(
            "Filtra pela categoria da transação. Deve ser uma das seguintes opções: "
            "comida, besteira, estudo, transporte, saude, lazer, contas, investimento, presente, venda, outros."
        )
    )
    description: Optional[str] = Field(
        default=None,
        description="Filtra transações cuja descrição contenha o texto informado (busca parcial, usando LIKE)."
    )
    payment_method: Optional[str] = Field(
        default=None,
        description="Filtra pela forma de pagamento (ex: credito, debito, pix, dinheiro, boleto)."
    )
    min_date: Optional[str] = Field(
        default=None,
        description="Define o início do intervalo pelo qual as transações serão filtradas (formato YYYY-MM-DD). Caso o usuário pergunte por uma data específica, e não intervalo, esse campo recebe o mesmo valor que o max_date."
    )
    max_date: Optional[str] = Field(
        default=None,
        description="Define o fim do intervalo pelo qual as transações serão filtradas (formato YYYY-MM-DD). Caso o usuário pergunte por uma data específica, e não intervalo, esse campo recebe o mesmo valor que o min_date."
    )
    source_text: Optional[str] = Field(
        default=None,
        description="Filtra transações cujo texto original contenha o valor informado (busca parcial)."
    )


class UpdateTransactionArgs(BaseModel):
    id: Optional[int] = Field(
        default=None,
        description="ID da transação a atualizar. Se ausente, será feita uma busca por (match_text + date_local)."
    )
    match_text: Optional[str] = Field(
        default=None,
        description="Texto para localizar transação quando id não for informado (busca em source_text/description)."
    )
    date_local: Optional[str] = Field(
        default=None,
        description="Data local (YYYY-MM-DD) em America/Sao_Paulo; usado em conjunto com match_text quando id ausente."
    )
    amount: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False, description="Novo valor; zero permite remoção lógica.")
    type_id: Optional[int] = Field(default=None, description="Novo type_id (1/2/3).")
    type_name: Optional[str] = Field(default=None, description="Novo type_name: INCOME | EXPENSES | TRANSFER.")
    category_id: Optional[int] = Field(default=None, description="Nova categoria (id).")
    category_name: Optional[str] = Field(default=None, description="Nova categoria (nome).")
    description: Optional[str] = Field(default=None, description="Nova descrição.")
    payment_method: Optional[str] = Field(default=None, description="Novo meio de pagamento.")
    occurred_at: Optional[str] = Field(default=None, description="Novo timestamp ISO 8601.")

TYPE_ALIASES = {
    # ================= INCOME =================
    "INCOME": "INCOME",
    "ENTRADA": "INCOME",
    "RECEITA": "INCOME",
    "GANHO": "INCOME",
    "GANHEI": "INCOME",
    "RECEBI": "INCOME",
    "RECEBIMENTO": "INCOME",
    "SALARIO": "INCOME",
    "SALÁRIO": "INCOME",
    "PAGAMENTO_RECEBIDO": "INCOME",
    "PAGOU": "INCOME",
    "ME PAGOU": "INCOME",
    "DEPÓSITO": "INCOME",
    "DEPOSITO": "INCOME",
    "CREDITO": "INCOME",
    "CRÉDITO": "INCOME",
    "CAIU": "INCOME",
    "ENTROU": "INCOME",
    "VENDA": "INCOME",
    "VENDI": "INCOME",
    "FATUREI": "INCOME",
    "LUCRO": "INCOME",
    "RENDIMENTO": "INCOME",
    "BONUS": "INCOME",
    "BÔNUS": "INCOME",
    "COMISSÃO": "INCOME",
    "COMISSAO": "INCOME",
    "PINGOU": "INCOME",
    # ================= EXPENSE =================
    "EXPENSE": "EXPENSES",
    "EXPENSES": "EXPENSES",
    "DESPESA": "EXPENSES",
    "GASTO": "EXPENSES",
    "GASTEI": "EXPENSES",
    "PAGUEI": "EXPENSES",
    "PAGAMENTO": "EXPENSES",
    "PAGANDO": "EXPENSES",
    "SAIDA": "EXPENSES",
    "SAÍDA": "EXPENSES",
    "DEBITO": "EXPENSES",
    "DÉBITO": "EXPENSES",
    "DESCONTO": "EXPENSES",
    "COBROU": "EXPENSES",
    "ME COBROU": "EXPENSES",
    "TAXA": "EXPENSES",
    "TARIFA": "EXPENSES",
    "COMPRA": "EXPENSES",
    "COMPREI": "EXPENSES",
    "ASSINATURA": "EXPENSES",
    "CONTA": "EXPENSES",
    "BOLETO": "EXPENSES",
    "ALUGUEL": "EXPENSES",
    "MERCADO": "EXPENSES",
    "IFOOD": "EXPENSES",
    "UBER": "EXPENSES",
    # ================= TRANSFER =================
    "TRANSFER": "TRANSFER",
    "TRANSFERÊNCIA": "TRANSFER",
    "TRANSFERENCIA": "TRANSFER",
    "TRANSFERI": "TRANSFER",
    "MOVI": "TRANSFER",
    "MOVIMENTAÇÃO": "TRANSFER",
    "PIX": "TRANSFER",
    "TED": "TRANSFER",
    "DOC": "TRANSFER",
    "ENVIEI": "TRANSFER",
    "MANDEI": "TRANSFER",
    "ENVIO": "TRANSFER",
    "REMESSA": "TRANSFER",
    "ENTRE CONTAS": "TRANSFER",
    "INTERNA": "TRANSFER",
    "SAQUE": "TRANSFER",
    "SAQUEI": "TRANSFER"
}

CATEGORY_ALIASES = {
    # ================= COMIDA =================
    "COMIDA": "COMIDA",
    "ALMOCO": "COMIDA",
    "ALMOÇO": "COMIDA",
    "JANTA": "COMIDA",
    "JANTAR": "COMIDA",
    "CAFE": "COMIDA",
    "CAFÉ": "COMIDA",
    "REFEICAO": "COMIDA",
    "REFEIÇÃO": "COMIDA",
    "RESTAURANTE": "COMIDA",
    "PRATO": "COMIDA",
    "MARMITA": "COMIDA",
    # ================= BESTEIRA =================
    "BESTEIRA": "BESTEIRA",
    "LANCHINHO": "BESTEIRA",
    "LANCHE": "BESTEIRA",
    "DOCES": "BESTEIRA",
    "DOCE": "BESTEIRA",
    "SALGADO": "BESTEIRA",
    "PIZZA": "BESTEIRA",
    "HAMBURGUER": "BESTEIRA",
    "HAMBÚRGUER": "BESTEIRA",
    "MC": "BESTEIRA",
    "MCDONALDS": "BESTEIRA",
    "BURGER": "BESTEIRA",
    "IFOOD": "BESTEIRA",
    "RAPPI": "BESTEIRA",
    "ENERGÉTICO": "BESTEIRA",
    "ENERGETICO": "BESTEIRA",
    "REFRIGERANTE": "BESTEIRA",
    # ================= ESTUDO =================
    "ESTUDO": "ESTUDO",
    "CURSO": "ESTUDO",
    "FACULDADE": "ESTUDO",
    "ESCOLA": "ESTUDO",
    "LIVRO": "ESTUDO",
    "LIVROS": "ESTUDO",
    "MATERIAL": "ESTUDO",
    "CADERNO": "ESTUDO",
    "CANETA": "ESTUDO",
    "EDUCACAO": "ESTUDO",
    "EDUCAÇÃO": "ESTUDO",
    # ================= TRANSPORTE =================
    "TRANSPORTE": "TRANSPORTE",
    "UBER": "TRANSPORTE",
    "99": "TRANSPORTE",
    "TAXI": "TRANSPORTE",
    "ÔNIBUS": "TRANSPORTE",
    "ONIBUS": "TRANSPORTE",
    "METRO": "TRANSPORTE",
    "METRÔ": "TRANSPORTE",
    "TREM": "TRANSPORTE",
    "PASSAGEM": "TRANSPORTE",
    "GASOLINA": "TRANSPORTE",
    "COMBUSTIVEL": "TRANSPORTE",
    "COMBUSTÍVEL": "TRANSPORTE",
    "ESTACIONAMENTO": "TRANSPORTE",
    # ================= SAÚDE =================
    "SAUDE": "SAÚDE",
    "SAÚDE": "SAÚDE",
    "MEDICO": "SAÚDE",
    "MÉDICO": "SAÚDE",
    "CONSULTA": "SAÚDE",
    "EXAME": "SAÚDE",
    "HOSPITAL": "SAÚDE",
    "REMEDIO": "SAÚDE",
    "REMÉDIO": "SAÚDE",
    "FARMACIA": "SAÚDE",
    "FARMÁCIA": "SAÚDE",
    # ================= LAZER =================
    "LAZER": "LAZER",
    "ROUPA": "LAZER",
    "ROUPAS": "LAZER",
    "TENIS": "LAZER",
    "TÊNIS": "LAZER",
    "SHOPPING": "LAZER",
    "VIAGEM": "LAZER",
    "HOTEL": "LAZER",
    "FESTA": "LAZER",
    "BALADA": "LAZER",
    "CINEMA": "LAZER",
    "NETFLIX": "LAZER",
    "SPOTIFY": "LAZER",
    # ================= CONTAS =================
    "CONTAS": "CONTAS",
    "CONTA": "CONTAS",
    "LUZ": "CONTAS",
    "AGUA": "CONTAS",
    "ÁGUA": "CONTAS",
    "ENERGIA": "CONTAS",
    "ALUGUEL": "CONTAS",
    "CONDOMINIO": "CONTAS",
    "CONDOMÍNIO": "CONTAS",
    "INTERNET": "CONTAS",
    "BOLETO": "CONTAS",
    # ================= INVESTIMENTO =================
    "INVESTIMENTO": "INVESTIMENTO",
    "INVESTI": "INVESTIMENTO",
    "INVESTIR": "INVESTIMENTO",
    "APLICACAO": "INVESTIMENTO",
    "APLICAÇÃO": "INVESTIMENTO",
    "ACOES": "INVESTIMENTO",
    "AÇÕES": "INVESTIMENTO",
    "CRIPTO": "INVESTIMENTO",
    "BITCOIN": "INVESTIMENTO",
    "POUPANCA": "INVESTIMENTO",
    "POUPANÇA": "INVESTIMENTO",
    "IMOVEL": "INVESTIMENTO",
    "IMÓVEL": "INVESTIMENTO",
    # ================= PRESENTE =================
    "PRESENTE": "PRESENTE",
    "PRESENTEI": "PRESENTE",
    "GANHEI": "PRESENTE",
    "GANHOU": "PRESENTE",
    # ================= VENDA =================
    "VENDA": "VENDA",
    "VENDI": "VENDA",
    "VENDEU": "VENDA",
    # ================= ELETRONICOS =================
    "ELETRÔNICO": "ELETRONICOS",
    "ELETRONICO": "ELETRONICOS",
    "ELETRONICOS": "ELETRONICOS",
    "FONE": "ELETRONICOS",
    "CELULAR": "ELETRONICOS",
    "ELETRODOMESTICO": "ELETRONICOS",
    "VIDEOGAME": "ELETRONICOS",
    "TV": "ELETRONICOS",
    "NOTEBOOK": "ELETRONICOS",
    "TABLET": "ELETRONICOS",
    "HEADPHONE": "ELETRONICOS",
    "HEADPHONES": "ELETRONICOS",
    "PC": "ELETRONICOS",
    "MONITOR": "ELETRONICOS",
    "MOUSE": "ELETRONICOS",
    "TECLADO": "ELETRONICOS",
    # ================= OUTROS =================
    "OUTROS": "OUTROS",
    "DIVERSOS": "OUTROS",
    "VARIOS": "OUTROS",
    "VÁRIOS": "OUTROS",
    "OUTRA": "OUTROS",
}

def _local_date_filter_sql(field: str = "occurred_at") -> str:
    """
    Retorna um trecho SQL para filtragem por dia local em America/Sao_Paulo.
    Ex.: (occurred_at AT TIME ZONE 'America/Sao_Paulo')::date = %s::date
    """
    return f"(({field} AT TIME ZONE 'America/Sao_Paulo')::date = %s::date)"


def _resolve_type_id(cur, type_id: Optional[int], type_name: Optional[str]) -> Optional[int]:
    if type_name:
        t = type_name.strip().upper()
        if t in TYPE_ALIASES:
            t = TYPE_ALIASES[t]
        cur.execute("SELECT id FROM transaction_types WHERE UPPER(type)=%s LIMIT 1;", (t,))
        row = cur.fetchone()
        return row[0] if row else None
    if type_id:
        return int(type_id)
    return 2

def _resolve_category_id(cur, category_id: Optional[int], category_name: Optional[str]) -> Optional[int]:
    if category_name:
        t = category_name.strip().upper()
        if t in CATEGORY_ALIASES:
            t = CATEGORY_ALIASES[t]
        cur.execute(
            "SELECT id FROM categories WHERE UPPER(name)=%s LIMIT 1;",
            (t,)
        )
        row = cur.fetchone()
        return row[0] if row else 13
    if category_id:
        return int(category_id)
    return 13

@tool("add_transaction", args_schema=AddTransactionArgs)
def add_transaction(
    amount: float,
    source_text: str,
    occurred_at: Optional[str] = None,
    type_id: Optional[int] = None,
    type_name: Optional[str] = None,
    category_id: Optional[int] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
    config: RunnableConfig = None,
) -> dict:
    """Insere uma transação financeira no banco de dados Postgres."""
    conn = None
    cur = None
    try:
        conn = get_conn(config)
        cur = conn.cursor()
        resolved_type_id = _resolve_type_id(cur, type_id, type_name)
        resolve_category_id = _resolve_category_id(cur, category_id, category_name)
        
        if not resolved_type_id:
            desfazer_operacao(conn, config)
            return {"status": "error", "message": "Tipo inválido (use type_id ou type_name: INCOME/EXPENSES/TRANSFER)."}

        cur.execute(
            """
            INSERT INTO transactions
                (amount, type, category_id, description, payment_method, occurred_at, source_text)
            VALUES
                (%s, %s, %s, %s, %s, COALESCE(%s::timestamptz, NOW()), %s)
            RETURNING id, occurred_at;
            """,
            (amount, resolved_type_id, resolve_category_id, description, payment_method, occurred_at, source_text),
        )

        new_id, occurred = cur.fetchone()
        confirmar_operacao(conn, config)
        return {"status": "ok", "id": new_id, "occurred_at": str(occurred)}

    except Exception as e:
        desfazer_operacao(conn, config)
        return {"status": "error", "message": str(e)}
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        fechar_conexao(conn, config)

@tool("search_transactions", args_schema=QueryTransactionArgs)
def search_transactions(
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    type_name: Optional[str] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
    min_date: Optional[str] = None,
    max_date: Optional[str] = None,
    source_text: Optional[str] = None,
    config: RunnableConfig = None,
) -> dict:
    """
    Use quando o usuário quiser consultar, listar ou analisar transações passadas.
    Não use para obter o saldo total — prefira saldo_total para isso.

    As informações devem vir na seguinte ordem:
    - Intervalo (min_date/max_date): ASC (cronológico)
    - Caso contrário: DESC (mais recentes primeiro)
    """
    conn = None
    cur = None
    try:
        conn = get_conn(config)
        cur = conn.cursor()
        query = """
            SELECT
                t.amount,
                ty.type as type_name,
                c.name as category_name,
                t.description,
                CASE WHEN t.payment_method IS NULL
                    THEN 'Método de pagamento não informado'
                ELSE t.payment_method
                END AS payment_method,
                (t.occurred_at AT TIME ZONE 'America/Sao_Paulo')::date as occurred_date,
                t.source_text,
                t.id
            FROM
                transactions t
            LEFT JOIN
                transaction_types ty ON ty.id = t.type
            LEFT JOIN
                categories c ON c.id = t.category_id
            WHERE
                1=1
            """
        params = []

        if min_amount is not None and max_amount is not None:
            query += " AND t.amount BETWEEN %s AND %s"
            params.extend([min_amount, max_amount])
        elif min_amount is not None:
            query += " AND t.amount >= %s"
            params.append(min_amount)
        elif max_amount is not None:
            query += " AND t.amount <= %s"
            params.append(max_amount)

        if min_date is not None and max_date is not None:
            query += " AND (t.occurred_at AT TIME ZONE 'America/Sao_Paulo')::date BETWEEN %s::date AND %s::date"
            params.extend([min_date, max_date])
        elif min_date is not None:
            query += " AND (t.occurred_at AT TIME ZONE 'America/Sao_Paulo')::date >= %s::date"
            params.append(min_date)
        elif max_date is not None:
            query += " AND (t.occurred_at AT TIME ZONE 'America/Sao_Paulo')::date <= %s::date"
            params.append(max_date)

        if type_name:
            tipo = type_name.strip().upper()
            tipo = TYPE_ALIASES.get(tipo, tipo)
            query += " AND UPPER(ty.type) = %s"
            params.append(tipo)
        if category_name:
            categoria = category_name.strip().upper()
            categoria = CATEGORY_ALIASES.get(categoria, categoria)
            query += " AND UPPER(c.name) = %s"
            params.append(categoria)
        if description:
            query += " AND t.description ILIKE %s"
            params.append(f"%{description}%")
        if payment_method:
            query += " AND t.payment_method ILIKE %s"
            params.append(f"%{payment_method}%")
        if source_text:
            query += " AND t.source_text ILIKE %s"
            params.append(f"%{source_text}%")

        ordem = "ASC" if min_date is not None or max_date is not None else "DESC"
        query += f" ORDER BY t.occurred_at {ordem}, t.id {ordem}"
        cur.execute(query, params)
        rows = cur.fetchall()

        results = [
            {
                "amount": row[0],
                "type": row[1],
                "category": row[2],
                "description": row[3],
                "payment_method": row[4],
                "occurred_date": str(row[5]),
                "source_text": row[6],
                "id": row[7],
            } for row in rows
        ]

        return {"transactions": results, "status": "ok"}

    except Exception as e:
        desfazer_operacao(conn, config)
        return {"status": "error", "message": str(e)}
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        fechar_conexao(conn, config)

@tool("saldo_total")
def saldo_total(
    config: RunnableConfig = None,
) -> dict:
    """
    Retorna o saldo total do usuário (INCOME - EXPENSES) em todo o histórico de transações.
    **OBS: Transações do tipo TRANSFER não são consideradas no cálculo do saldo, pois não se sabe se são entradas ou saídas de dinheiro**.
    """
    conn = None
    cur = None
    try:
        conn = get_conn(config)
        cur = conn.cursor()
        query = """
            WITH base_amount AS (
                SELECT
                    COALESCE(SUM(CASE WHEN type = 2 THEN amount ELSE 0 END), 0) AS total_expenses,
                    COALESCE(SUM(CASE WHEN type = 1 THEN amount ELSE 0 END), 0) AS total_income
                FROM transactions
            )
            SELECT total_expenses, total_income, total_income - total_expenses AS total_balance
            FROM base_amount;
        """
        cur.execute(query)
        rows = cur.fetchall()

        results = [
            {
                "total_expenses": row[0],
                "total_income": row[1],
                "total_balance": row[2]
            } for row in rows
        ]

        return {"amounts": results, "status": "ok"}

    except Exception as e:
        desfazer_operacao(conn, config)
        return {"status": "error", "message": str(e)}
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        fechar_conexao(conn, config)

@tool("saldo_diario")
def saldo_diario(date_local: str, config: RunnableConfig = None) -> dict:
    """
    Retorna o saldo total do usuário (INCOME - EXPENSES) do dia informado (YYYY-MM-DD) em America/Sao_Paulo.
    A variável recebe o dia informado pelo usuário, por exemplo: "Qual foi meu saldo de hoje?", nesse caso 'date_local' receberá a data de hoje no formato YYYY-MM-DD.
    **OBS: Transações do tipo TRANSFER não são consideradas no cálculo do saldo, pois não se sabe se são entradas ou saídas de dinheiro**.
    """
    conn = None
    cur = None
    try:
        conn = get_conn(config)
        cur = conn.cursor()
        query = """
            WITH base_amount AS (
                SELECT
                    COALESCE(SUM(CASE WHEN type = 2 THEN amount ELSE 0 END), 0) AS total_expenses,
                    COALESCE(SUM(CASE WHEN type = 1 THEN amount ELSE 0 END), 0) AS total_income
                FROM transactions
                WHERE (occurred_at AT TIME ZONE 'America/Sao_Paulo')::date = %s::date
            )
            SELECT total_expenses, total_income, total_income - total_expenses AS total_balance
            FROM base_amount;
        """
        cur.execute(query, (date_local,))
        rows = cur.fetchall()

        results = [
            {
                "total_expenses": row[0],
                "total_income": row[1],
                "total_balance": row[2]
            } for row in rows
        ]

        return {"amounts": results, "status": "ok"}

    except Exception as e:
        desfazer_operacao(conn, config)
        return {"status": "error", "message": str(e)}
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        fechar_conexao(conn, config)


@tool("update_transaction", args_schema=UpdateTransactionArgs)
def update_transaction(
    id: Optional[int] = None,
    match_text: Optional[str] = None,
    date_local: Optional[str] = None,
    amount: Optional[float] = None,
    type_id: Optional[int] = None,
    type_name: Optional[str] = None,
    category_id: Optional[int] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
    occurred_at: Optional[str] = None,
    config: RunnableConfig = None,
) -> dict:
    """
    Atualiza uma transação existente.
    Estratégias:
      - Se 'id' for informado: atualiza diretamente por ID.
      - Caso contrário: localiza a transação mais recente que combine (match_text em source_text/description)
        E (date_local em America/Sao_Paulo), então atualiza.
    Retorna: status, rows_affected, id, e o registro atualizado.
    """
    campos_atualizacao = [
        amount, type_id, type_name, category_id, category_name,
        description, payment_method, occurred_at,
    ]
    if all(valor is None for valor in campos_atualizacao):
        desfazer_operacao(None, config)
        return {"status": "error", "message": "Nada para atualizar: forneça pelo menos um campo (amount, type, category, description, payment_method, occurred_at)."}

    conn = None
    cur = None
    try:
        conn = get_conn(config)
        cur = conn.cursor()
        # Resolve target_id
        target_id = id
        if target_id is None:
            if not match_text or not date_local:
                desfazer_operacao(conn, config)
                return {"status": "error", "message": "Sem 'id': informe match_text E date_local para localizar o registro."}

            # Buscar o mais recente no dia local informado que combine o texto
            cur.execute(
                f"""
                SELECT t.id
                FROM transactions t
                WHERE (t.source_text ILIKE %s OR t.description ILIKE %s)
                  AND {_local_date_filter_sql("t.occurred_at")}
                ORDER BY t.occurred_at DESC
                LIMIT 1;
                """,
                (f"%{match_text}%", f"%{match_text}%", date_local)
            )
            row = cur.fetchone()
            if not row:
                desfazer_operacao(conn, config)
                return {"status": "error", "message": "Nenhuma transação encontrada para os filtros fornecidos."}
            target_id = row[0]

        # Resolver type_id / category_id a partir de nomes, se fornecidos
        resolved_type_id = _resolve_type_id(cur, type_id, type_name) if (type_id or type_name) else None
        if type_name and resolved_type_id is None:
            desfazer_operacao(conn, config)
            return {"status": "error", "message": "Tipo de transação inválido; nenhuma alteração foi feita."}
        resolved_category_id = category_id
        if category_name and not category_id:
            resolved_category_id = _resolve_category_id(cur, None, category_name)

        # Montar SET dinâmico
        sets = []
        params: List[object] = []
        if amount is not None:
            sets.append("amount = %s")
            params.append(amount)
        if resolved_type_id is not None:
            sets.append("type = %s")
            params.append(resolved_type_id)
        if resolved_category_id is not None:
            sets.append("category_id = %s")
            params.append(resolved_category_id)
        if description is not None:
            sets.append("description = %s")
            params.append(description)
        if payment_method is not None:
            sets.append("payment_method = %s")
            params.append(payment_method)
        if occurred_at is not None:
            sets.append("occurred_at = %s::timestamptz")
            params.append(occurred_at)

        if not sets:
            desfazer_operacao(conn, config)
            return {"status": "error", "message": "Nenhum campo válido para atualizar."}

        params.append(target_id)

        cur.execute(
            f"UPDATE transactions SET {', '.join(sets)} WHERE id = %s;",
            params
        )
        rows_affected = cur.rowcount
        if rows_affected == 0:
            desfazer_operacao(conn, config)
            return {"status": "error", "rows_affected": 0, "message": "Nenhuma transação encontrada para o ID informado."}
        confirmar_operacao(conn, config)

        # Retornar o registro atualizado
        cur.execute(
            """
            SELECT
              t.id, t.occurred_at, t.amount, tt.type AS type_name,
              c.name AS category_name, t.description, t.payment_method, t.source_text
            FROM transactions t
            JOIN transaction_types tt ON tt.id = t.type
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.id = %s;
            """,
            
            (target_id,)
        )
        r = cur.fetchone()
        updated = None
        if r:
            updated = {
                "id": r[0],
                "occurred_at": str(r[1]),
                "amount": float(r[2]),
                "type": r[3],
                "category": r[4],
                "description": r[5],
                "payment_method": r[6],
                "source_text": r[7],
            }

        return {
            "status": "ok",
            "rows_affected": rows_affected,
            "id": target_id,
            "updated": updated
        }

    except Exception as e:
        desfazer_operacao(conn, config)
        return {"status": "error", "message": str(e)}
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        fechar_conexao(conn, config)


# Exporta a lista de tools
TOOLS = [add_transaction, search_transactions, saldo_total, saldo_diario, update_transaction]
