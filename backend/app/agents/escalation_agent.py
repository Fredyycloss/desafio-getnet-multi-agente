class EscalationAgent:
    name = "escalation_agent"
    def run(self, reason: str = "low_confidence") -> dict:
        return {"answer": "Posso ajudar com orientações gerais, mas esta solicitação precisa de análise do atendimento oficial para uma resposta confiável. Entre em contato pelos canais oficiais da Getnet e não compartilhe senhas ou códigos de autenticação neste chat.", "confidence": 0.9, "sources": [{"title": "Site oficial Getnet", "url": "https://www.getnet.net/"}], "handoff": True, "handoff_reason": reason, "trace": ["escalation_agent", "human_handoff_recommended"]}
