from __future__ import annotations

import sqlite3

from .human_handoff_agent import HumanHandoffAgent


class HandoffUnavailable(RuntimeError):
    """The persistent human-support queue could not register an escalation."""


class EscalationAgent:
    name = "human_escalation_agent"

    def __init__(self, handoff_agent: HumanHandoffAgent, notifier=None):
        self.handoff_agent = handoff_agent
        self.notifier = notifier  # HITLService: operator card (Telegram) + LLM summary; best effort

    def run(self, *, reason: str, language: str, user_id: str, message: str, severity: str = "normal", session_id: str | None = None, safety_message: str | None = None, history: list[dict] | None = None) -> dict:
        try:
            ticket = self.handoff_agent.create_ticket(user_id=user_id, message=message, reason=reason, language=language, severity=severity, session_id=session_id, history=history)
        except sqlite3.Error as exc:
            raise HandoffUnavailable("Could not persist the human-support request") from exc
        protocol = ticket["protocol"]
        channel = {"telegram": "not_configured"}
        connected = False
        if self.notifier is not None:
            try:
                channel = self.notifier.notify_new_ticket(ticket)
                connected = self.notifier.human_available()
            except Exception:  # noqa: BLE001 - notification never loses the ticket
                channel = {"telegram": "failed"}
        if safety_message:
            # Availability comes from the live operator channels (console heartbeat, Telegram worker).
            availability = (("Um atendente está online e foi notificado; a resposta aparecerá aqui." if connected else
                             "Nenhum atendente está online agora; o protocolo segue na fila prioritária e a resposta aparecerá aqui.")
                            if language != "en" else
                            ("An attendant is online and was notified; the reply will appear here." if connected else
                             "No attendant is online right now; the protocol stays in the priority queue and the reply will appear here."))
            answer = safety_message.format(protocol=protocol, availability=availability)
        elif language == "en":
            answer = (f"Your request is registered and waiting for an attendant. Protocol: {protocol}.\n\n"
                      + ("An attendant is online and will reply here." if connected else
                         "No attendant is online right now; the request stays in the queue and you will see the reply here.")
                      + " This is a demonstration environment with synthetic data, not an official Getnet case.")
        else:
            answer = (f"Sua solicitação foi registrada e aguarda um atendente. Protocolo: {protocol}.\n\n"
                      + ("Há atendente online e a resposta aparecerá aqui." if connected else
                         "Nenhum atendente está online agora; a solicitação segue na fila e a resposta aparecerá aqui.")
                      + " Este é um ambiente de demonstração com dados sintéticos, não um chamado oficial da Getnet.")
        source = {"title": "Getnet — contato oficial" if language == "pt" else "Getnet — official contact", "url": "https://site.getnet.com.br/get-ajuda/" if language == "pt" else "https://www.getnet.net/en/contact"}
        return {"answer": answer, "confidence": 0.99 if severity in {"high", "critical"} else 0.9,
                "sources": [source], "handoff": True, "handoff_reason": reason, "handoff_protocol": protocol,
                "handoff_status": ticket["status"], "handoff_severity": severity,
                "real_agent_connected": connected, "operator_channel": channel,
                "trace": ["human_escalation_agent", "human_handoff_agent", "persistent_ticket_created",
                          f"operator_notified:{channel.get('telegram', 'n/a')}"]}
