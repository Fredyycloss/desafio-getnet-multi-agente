from __future__ import annotations

from typing import Callable

from ..language import normalize
from . import support_tools
from .clarification import selected_topic_result
from .specialist import ToolSpecialist

SUPPORT_TOOLS = [
    {"type": "function", "function": {"name": "get_customer_profile", "description": "Read the synthetic demo merchant profile (name, account status, segment) of the current customer.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_terminal_status", "description": "Read the synthetic terminal model, online/offline status, connection type and last error of the current customer.", "parameters": {"type": "object", "properties": {}, "required": []}}},
]


class CustomerSupportAgent(ToolSpecialist):
    """Account profile and terminal/connection support over synthetic SQLite data."""
    name = "customer_support_agent"
    tool_schemas = SUPPORT_TOOLS
    selection_prompt = (
        "You are the Getnet Customer Support specialist for account profile and card-terminal problems. "
        "Select the tools needed: get_terminal_status for terminal, connection, Wi-Fi, chip, screen or device problems; "
        "get_customer_profile for account or registration questions. Call every relevant tool now. Do not answer in text."
    )
    writer_role = "You are the Getnet Customer Support specialist for account profile and card-terminal problems."
    action_kinds = ("technical_visit", "supply_request", "terminal_block")
    action_prompt = ("When the customer explicitly asks you to open a technical ticket or visit, send paper rolls or a replacement "
                     "terminal, or block a lost or stolen terminal, call the matching propose_* tool: it only prepares the request, "
                     "and the customer confirms before anything happens. Do not propose actions the customer did not ask for.")

    def request_selected_topic_details(self, topic_id: str, language: str) -> dict:
        """Ask only for the missing support details after a customer selects a topic."""
        result = selected_topic_result(language, topic_id)
        result.update({
            "agent": self.name,
            "trace": [self.name, "targeted_intake_clarification"],
            "agent_mode": "curated_intake_template",
        })
        return result

    def bind_tools(self, user_id: str) -> dict[str, Callable[[dict], dict]]:
        return {
            "get_customer_profile": lambda args: support_tools.get_customer_profile(self.db, user_id),
            "get_terminal_status": lambda args: support_tools.get_terminal_status(self.db, user_id),
        }

    def keyword_selection(self, task: str) -> list[tuple[str, dict]]:
        # Fallback only (model disabled/unavailable or no tool chosen); always marked degraded.
        text = normalize(task)
        if any(token in text for token in ("terminal", "maquina", "maquininha", "connection", "internet", "wifi", "conect", "offline", "device")):
            return [("get_terminal_status", {})]
        return [("get_customer_profile", {})]

    def compose_template(self, observations: list[dict], language: str) -> str:
        good = [item for item in observations if item.get("ok")]
        if not good:
            return ("Não encontrei um cadastro demonstrativo para este identificador. Esta API usa dados sintéticos e não consulta contas reais da Getnet."
                    if language == "pt" else
                    "No demo customer record was found for this identifier. This API uses synthetic data and does not access real Getnet accounts.")
        sections: list[str] = []
        for item in good:
            d = item.get("data") or {}
            if item.get("tool") == "get_terminal_status":
                sections.append(f"Demo terminal {d['terminal_id']} ({d['model']}) is {d['status']} via {d['connection_type']}. Error: {d.get('error_code') or 'none'}."
                                if language == "en" else
                                f"A maquininha demonstrativa {d['terminal_id']} ({d['model']}) está {d['status']} via {d['connection_type']}. Erro: {d.get('error_code') or 'nenhum'}.")
            elif item.get("tool") == "get_customer_profile":
                sections.append(f"Demo merchant: {d['merchant_name']} (status: {d['account_status']}, segment: {d['segment']})."
                                if language == "en" else
                                f"Estabelecimento demonstrativo: {d['merchant_name']} (status: {d['account_status']}, segmento: {d['segment']}).")
        return "\n\n".join(sections) + synthetic_disclaimer(language)


def synthetic_disclaimer(language: str) -> str:
    return ("\n\nThese results come from synthetic demo records, not real Getnet systems." if language == "en"
            else "\n\nEstes resultados vêm de registros demonstrativos sintéticos, não dos sistemas reais da Getnet.")
