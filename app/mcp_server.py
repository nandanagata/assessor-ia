"""Servidor MCP local: publica as tools existentes sem duplicar o SQL."""

import sys
from pathlib import Path
from typing import Annotated, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from app.tools.agenda import add_event as _add_event, query_events as _query_events
from app.tools.financeiro import (
    add_transaction as _add_transaction,
    search_transactions as _search_transactions,
    saldo_diario as _saldo_diario,
    saldo_total as _saldo_total,
    update_transaction as _update_transaction,
)

mcp = MCPServer(
    name="assessor-financeiro",
    version="1.0.0",
    instructions="Ferramentas financeiras e de agenda do Assessor Lumi.",
)

LEITURA = ToolAnnotations(readOnlyHint=True)
ESCRITA = ToolAnnotations(readOnlyHint=False, destructiveHint=False)


@mcp.tool(name="total_balance", title="Saldo total", description="Receitas menos despesas em todo o histórico.", annotations=LEITURA)
def total_balance() -> dict[str, Any]:
    return _saldo_total.invoke({})


@mcp.tool(name="daily_balance", title="Saldo diário", description="Saldo de um dia em America/Sao_Paulo.", annotations=LEITURA)
def daily_balance(date_local: Annotated[str, Field(description="Data YYYY-MM-DD.")]) -> dict[str, Any]:
    return _saldo_diario.invoke({"date_local": date_local})


@mcp.tool(name="query_transactions", title="Consultar transações", description="Busca transações financeiras por filtros opcionais.", annotations=LEITURA)
def query_transactions(
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    type_name: Optional[str] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
    min_date: Optional[str] = None,
    max_date: Optional[str] = None,
    source_text: Optional[str] = None,
    limit: Annotated[int, Field(ge=1, le=200, description="Máximo de transações retornadas.")] = 20,
) -> dict[str, Any]:
    resultado = _search_transactions.invoke({
        "min_amount": min_amount,
        "max_amount": max_amount,
        "type_name": type_name,
        "category_name": category_name,
        "description": description,
        "payment_method": payment_method,
        "min_date": min_date,
        "max_date": max_date,
        "source_text": source_text,
    })
    if resultado.get("status") == "ok":
        transacoes = resultado.get("transactions", [])
        crescente = min_date is not None or max_date is not None
        resultado["transactions"] = sorted(
            transacoes,
            key=lambda item: item.get("occurred_date") or "",
            reverse=not crescente,
        )[:limit]
    return resultado


@mcp.tool(name="add_transaction", title="Registrar transação", description="Registra uma transação financeira no Postgres.", annotations=ESCRITA)
def add_transaction(
    amount: Annotated[float, Field(description="Valor positivo.")],
    source_text: Annotated[str, Field(description="Texto original do usuário.")],
    occurred_at: Optional[str] = None,
    type_name: Optional[str] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
) -> dict[str, Any]:
    return _add_transaction.invoke({
        "amount": amount,
        "source_text": source_text,
        "occurred_at": occurred_at,
        "type_name": type_name,
        "category_name": category_name,
        "description": description,
        "payment_method": payment_method,
    })


@mcp.tool(name="update_transaction", title="Atualizar transação", description="Atualiza uma transação por ID ou texto e data.", annotations=ESCRITA)
def update_transaction(
    id: Optional[int] = None,
    match_text: Optional[str] = None,
    date_local: Optional[str] = None,
    amount: Optional[float] = None,
    type_name: Optional[str] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
    occurred_at: Optional[str] = None,
) -> dict[str, Any]:
    return _update_transaction.invoke({
        "id": id,
        "match_text": match_text,
        "date_local": date_local,
        "amount": amount,
        "type_name": type_name,
        "category_name": category_name,
        "description": description,
        "payment_method": payment_method,
        "occurred_at": occurred_at,
    })


@mcp.tool(name="query_events", title="Consultar agenda", description="Consulta compromissos no Postgres por texto ou data local.", annotations=LEITURA)
def query_events(
    text: Optional[str] = None,
    date_local: Optional[str] = None,
    date_from_local: Optional[str] = None,
    date_to_local: Optional[str] = None,
    limit: int = 20,
) -> dict[str, Any]:
    return _query_events.invoke({
        "text": text,
        "date_local": date_local,
        "date_from_local": date_from_local,
        "date_to_local": date_to_local,
        "limit": limit,
    })


@mcp.tool(name="add_event", title="Registrar compromisso", description="Registra um compromisso na tabela events do Postgres.", annotations=ESCRITA)
def add_event(
    title: Annotated[str, Field(description="Título do compromisso.")],
    source_text: Annotated[str, Field(description="Texto original do usuário.")],
    start_time: Annotated[str, Field(description="Início ISO 8601 com fuso.")],
    end_time: Optional[str] = None,
    location: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    return _add_event.invoke({
        "title": title,
        "source_text": source_text,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "notes": notes,
    })


if __name__ == "__main__":
    from app.config.config import SQL_URL

    if not SQL_URL:
        print("[assessor-financeiro] SQL_URL ausente no .env", file=sys.stderr)
    mcp.run(transport="stdio")
