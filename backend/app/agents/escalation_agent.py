from __future__ import annotations

import sqlite3

from .human_handoff_agent import HumanHandoffAgent


class HandoffUnavailable(RuntimeError):
    """The persistent human-support queue could not register an escalation."""


class EscalationAgent:
    name = "human_escalation_agent"

    def __init__(self, handoff_agent: HumanHandoffAgent):
        self.handoff_agent = handoff_agent

    def run(self, *, reason: str, language: str, user_id: str, message: str, severity: str = "normal", session_id: str | None = None, safety_message: str | None = None, history: list[dict] | None = None) -> dict:
        try:
            ticket = self.handoff_agent.create_ticket(user_id=user_id, message=message, reason=reason, language=language, severity=severity, session_id=session_id, history=history)
        except sqlite3.Error as exc:
            raise HandoffUnavailable("Could not persist the human-support request") from exc
        protocol = ticket["protocol"]
        if safety_message:
            answer = safety_message.format(protocol=protocol)
        elif language == "en":
            answer = (f"Your request is registered in the simulated human-support queue and is waiting for an attendant. Protocol: {protocol}.\n\n"
                      "This is a demonstration only: no live human attendant is connected and this is not an official Getnet case. "
                      "For actual assistance, use the official Getnet contact channel for your country.")
        else:
            answer = (f"Sua solicitação foi registrada na fila simulada de atendimento humano e está aguardando atendimento. Protocolo: {protocol}.\n\n"
                      "Esta é apenas uma demonstração: não há atendente real conectado e este não é um chamado oficial da Getnet. "
                      "Para obter atendimento efetivo, utilize os canais oficiais da Getnet do seu país.")
        source = {"title": "Getnet — contato oficial" if language == "pt" else "Getnet — official contact", "url": "https://site.getnet.com.br/get-ajuda/" if language == "pt" else "https://www.getnet.net/en/contact"}
        return {"answer": answer, "confidence": 0.99 if severity in {"high", "critical"} else 0.9,
                "sources": [source], "handoff": True, "handoff_reason": reason, "handoff_protocol": protocol,
                "handoff_status": ticket["status"], "handoff_severity": severity,
                "real_agent_connected": False, "trace": ["human_escalation_agent", "human_handoff_agent", "persistent_ticket_created"]}
