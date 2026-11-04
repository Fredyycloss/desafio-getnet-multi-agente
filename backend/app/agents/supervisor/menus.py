"""Clarification-menu option parsing and routing message for a selected topic."""
from __future__ import annotations

import logging



logger = logging.getLogger("app.agents.supervisor_agent")

class MenuMixin:
    @staticmethod
    def _last_clarification_options(history: list[dict]) -> list[dict]:
        for item in reversed(history):
            if item.get("role") == "assistant":
                options = item.get("clarification_options")
                return options if isinstance(options, list) else []
        return []

    @classmethod
    def _selection_is_contextual(cls, history: list[dict]) -> bool:
        return any(
            isinstance(option, dict) and option.get("id") == "literal_hazard"
            for option in cls._last_clarification_options(history)
        )

    @classmethod
    def _selected_clarification_option(cls, message: str, history: list[dict]) -> str | None:
        import re
        import unicodedata

        def normalise(value: str) -> str:
            value = unicodedata.normalize("NFKD", value.casefold())
            value = "".join(char for char in value if not unicodedata.combining(char))
            return re.sub(r"[^a-z0-9]+", " ", value).strip()

        options = cls._last_clarification_options(history)
        selection = re.sub(r"^(opcao|option)\s+", "", normalise(message)).strip()
        # A long free-text message during a menu is a new request (subject change),
        # not an option: only short replies are matched against labels/aliases.
        short_reply = len(selection.split()) <= 6
        aliases = {
            "terminal_connection": {"conexao", "internet", "wifi", "connection", "network"},
            "terminal_sales": {"realizar vendas", "accept sales", "unable to sell"},
            "terminal_defect": {"defeito", "funcionamento", "terminal defect"},
            "sales_payments": {"pagamentos", "recebimentos", "payments", "settlement"},
            "human_support": {"atendente", "atendimento humano", "pessoa", "humano", "human", "agent"},
            "figurative_expression": {"figurada", "desabafo", "figurative", "frustration"},
            "literal_hazard": {"risco fisico", "perigo real", "physical hazard", "real danger"},
        }
        for index, option in enumerate(options, start=1):
            if not isinstance(option, dict):
                continue
            option_id = str(option.get("id", ""))
            label = normalise(str(option.get("label", "")))
            candidates = {str(index), option_id.replace("_", " "), label, *aliases.get(option_id, set())}
            if selection in candidates or (short_reply and any(
                len(candidate) >= 4 and (selection in candidate or candidate in selection)
                for candidate in candidates if candidate
            )):
                return option_id or None
        return None

    @classmethod
    def _routing_message(cls, message: str, history: list[dict], selected_option: str | None, language: str) -> str:
        if not selected_option:
            return message
        options = cls._last_clarification_options(history)
        label = next((str(item.get("label")) for item in options
                      if isinstance(item, dict) and item.get("id") == selected_option), selected_option)
        original = next((str(item.get("content", "")) for item in reversed(history)
                         if item.get("role") == "user"), message)
        return (
            f"The customer selected the topic option '{label}' after this original request: {original!r}. "
            f"The customer's selection message is {message!r}. Preserve the conversation context, do not ask the same menu again, "
            "and route to the relevant specialist."
        )

