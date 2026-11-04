from __future__ import annotations

from typing import Callable

from ..language import normalize
from . import support_tools
from .specialist import ToolSpecialist
from .support_agent import synthetic_disclaimer

PAYMENT_TOOLS = [
    {"type": "function", "function": {"name": "lookup_payment_status", "description": "Approved synthetic sales and their scheduled settlement (deposit) dates for the current customer.", "parameters": {"type": "object", "properties": {"period": {"type": "string", "enum": ["yesterday", "today"]}}, "required": []}}},
    {"type": "function", "function": {"name": "find_declined_transactions", "description": "Declined synthetic transactions and their error codes for the current customer.", "parameters": {"type": "object", "properties": {"period": {"type": "string", "enum": ["yesterday", "today"]}}, "required": []}}},
]


def _period(args: dict) -> str:
    value = str(args.get("period", "yesterday"))
    return value if value in {"yesterday", "today"} else "yesterday"


class PaymentsAgent(ToolSpecialist):
    """Sales, settlement (deposit) dates and declined transactions over synthetic SQLite data."""
    name = "payments_agent"
    tool_schemas = PAYMENT_TOOLS
    selection_prompt = (
        "You are the Getnet Payments specialist. Select the tools needed: lookup_payment_status for sales and when money "
        "will be deposited/settled; find_declined_transactions for declined or refused card transactions and error codes. "
        "Use period=yesterday or today as the request implies (default yesterday). Call every relevant tool now. Do not answer in text."
    )
    writer_role = "You are the Getnet Payments specialist (sales, settlements, declines)."
    action_kinds = ("transaction_dispute",)
    action_prompt = ("When the customer explicitly asks to dispute or contest a specific transaction and its transaction_id is "
                     "known from the conversation, call propose_transaction_dispute: it only prepares the request, and the customer "
                     "confirms before anything happens. If the id is unknown, look the transactions up instead.")

    def bind_tools(self, user_id: str) -> dict[str, Callable[[dict], dict]]:
        return {
            "lookup_payment_status": lambda args: support_tools.lookup_payment_status(self.db, user_id, _period(args)),
            "find_declined_transactions": lambda args: support_tools.find_declined_transactions(self.db, user_id, _period(args)),
        }

    @staticmethod
    def handles(task: str) -> bool:
        """Keyword hint used only by the deterministic fallback router."""
        text = normalize(task)
        return any(token in text for token in ("deposit", "payout", "settlement", "receiv", "receb", "quando cai", "dinheiro",
                                                "sales", "vendas", "declin", "recus", "transa", "pagamento", "payment"))

    def keyword_selection(self, task: str) -> list[tuple[str, dict]]:
        # Fallback only (model disabled/unavailable or no tool chosen); always marked degraded.
        text = normalize(task)
        period = "today" if ("today" in text or "hoje" in text) else "yesterday"
        selected: list[tuple[str, dict]] = []
        if any(token in text for token in ("declin", "recus", "error code", "erro", "transa")):
            selected.append(("find_declined_transactions", {"period": "yesterday"}))
        if not selected or any(token in text for token in ("deposit", "payout", "settlement", "receb", "quando cai", "dinheiro", "vendas", "sales")):
            selected.insert(0, ("lookup_payment_status", {"period": period}))
        return selected

    def compose_template(self, observations: list[dict], language: str) -> str:
        good = [item for item in observations if item.get("ok")]
        if not good:
            return ("Não encontrei um cadastro demonstrativo para este identificador. Esta API usa dados sintéticos e não consulta contas reais da Getnet."
                    if language == "pt" else
                    "No demo customer record was found for this identifier. This API uses synthetic data and does not access real Getnet accounts.")
        sections: list[str] = []
        for item in good:
            tx = item.get("transactions", [])
            if item.get("tool") == "lookup_payment_status":
                if language == "en":
                    sections.append(("Approved demo sales for {d}: {rows}. Net total: BRL {t:.2f}.".format(
                        d=item["transaction_date"], t=item["net_total_brl"],
                        rows="; ".join(f"{x['transaction_id']}: BRL {x['net_amount']:.2f}, scheduled {x['settlement_date']} ({x['settlement_status']})" for x in tx)))
                                    if tx else f"No approved demo sales were found for {item.get('transaction_date')}.")
                else:
                    sections.append(("Vendas demonstrativas aprovadas em {d}: {rows}. Total líquido: R$ {t:.2f}.".format(
                        d=item["transaction_date"], t=item["net_total_brl"],
                        rows="; ".join(f"{x['transaction_id']}: R$ {x['net_amount']:.2f}, previsão {x['settlement_date']} ({x['settlement_status']})" for x in tx)))
                                    if tx else f"Não encontrei vendas demonstrativas aprovadas em {item.get('transaction_date')}.")
            elif item.get("tool") == "find_declined_transactions":
                rows = ", ".join(f"{x['transaction_id']} ({'code' if language == 'en' else 'código'} {x.get('error_code')})" for x in tx)
                sections.append(("Declined demo transactions: " + (rows or "none found."))
                                if language == "en" else ("Transações demonstrativas recusadas: " + (rows or "nenhuma encontrada.")))
        return "\n\n".join(sections) + synthetic_disclaimer(language)
