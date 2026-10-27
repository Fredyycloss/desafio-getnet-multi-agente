from .agents.router_agent import RouterAgent
from .agents.knowledge_agent import KnowledgeAgent
from .agents.support_agent import CustomerSupportAgent
from .agents.escalation_agent import EscalationAgent
from .agents.guardrails import inspect_message

class ChatService:
    def __init__(self, documents: list[dict]):
        self.router = RouterAgent()
        self.knowledge = KnowledgeAgent(documents)
        self.support = CustomerSupportAgent()
        self.escalation = EscalationAgent()

    def answer(self, message: str, user_id: str) -> dict:
        guard = inspect_message(message)
        if guard.get("blocked"):
            return {"answer": guard["message"], "intent": "safety", "agent": "guardrails", "confidence": 0.99, "sources": [], "handoff": False, "trace": ["guardrails", "request_blocked"]}
        if guard.get("handoff"):
            result = self.escalation.run(guard.get("reason", "human_requested"))
            return {**result, "intent": "human_handoff", "agent": "escalation_agent", "trace": ["guardrails", "router_agent", *result["trace"]]}
        route = self.router.route(message)
        if route == "customer_support":
            result = self.support.run(message, user_id)
            intent = "customer_support"
            agent = self.support.name
        elif route == "general_question":
            result = self.escalation.run("external_live_data_unavailable")
            result["answer"] = "Esta pergunta depende de informação externa atualizada. Este protótipo não consulta dados ao vivo de clima ou câmbio. Verifique uma fonte atualizada e confiável; se a dúvida for sobre produtos Getnet, posso ajudar com a base de conhecimento."
            result["handoff"] = False
            result["trace"] = ["router_agent", "live_data_unavailable"]
            intent = "general_information"
            agent = "router_agent"
        else:
            result = self.knowledge.run(message)
            intent = "product_information"
            agent = self.knowledge.name
            if result["confidence"] < 0.18:
                result = self.escalation.run("low_confidence")
                intent = "human_handoff"
                agent = self.escalation.name
        return {"answer": result["answer"], "intent": intent, "agent": agent, "confidence": result["confidence"], "sources": result.get("sources", []), "handoff": result.get("handoff", False), "trace": ["guardrails", "router_agent", *result.get("trace", [])], **({"tool_result": result["tool_result"]} if "tool_result" in result else {}), **({"handoff_reason": result["handoff_reason"]} if "handoff_reason" in result else {})}
