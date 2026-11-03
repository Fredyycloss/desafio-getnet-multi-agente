from __future__ import annotations

from .agents.context_intelligence import ContextIntelligence
from .agents.critic_agent import CriticAgent
from .agents.escalation_agent import EscalationAgent
from .agents.human_handoff_agent import HumanHandoffAgent
from .agents.knowledge_agent import KnowledgeAgent
from .agents.payments_agent import PaymentsAgent
from .agents.risk_assessment_agent import RiskAssessmentAgent
from .agents.supervisor_agent import SupervisorAgent
from .agents.support_agent import CustomerSupportAgent
from .agents.web_research_agent import WebResearchAgent
from .infra.database import Database
from .infra.llm import LLMProvider
from .observability import current_timeline, finish_timeline, start_timeline


class ChatService:
    def __init__(self, documents: list[dict], db: Database, llm: LLMProvider | None = None,
                 *, llm_required: bool = False):
        self.db = db
        self.llm = llm
        self.context_intelligence = ContextIntelligence(llm, classifier=self._intent_classifier(llm, db))
        self.knowledge = KnowledgeAgent(documents, db=db, llm=llm)
        self.support = CustomerSupportAgent(db, llm)
        self.payments = PaymentsAgent(db, llm)
        self.risk = RiskAssessmentAgent()
        self.handoff = HumanHandoffAgent(db)
        self.escalation = EscalationAgent(self.handoff)
        self.web = WebResearchAgent(llm=llm)
        self.critic = CriticAgent(llm, required=llm_required)
        self.supervisor = SupervisorAgent(llm=llm, db=db, knowledge=self.knowledge, support=self.support,
                                          web=self.web, risk=self.risk, escalation=self.escalation, critic=self.critic,
                                          context_intelligence=self.context_intelligence, llm_required=llm_required,
                                          payments=self.payments)

    @staticmethod
    def _intent_classifier(llm, db):
        """kNN intent classifier for CONTEXT_MODE=embedding|hybrid (local nomic embeddings)."""
        import os
        if llm is None or os.getenv("CONTEXT_MODE", "llm").strip().lower() not in {"embedding", "hybrid"}:
            return None
        from .agents.intent_classifier import EmbeddingIntentClassifier
        return EmbeddingIntentClassifier(llm, db)

    def answer(self, message: str, user_id: str, session_id: str, history: list[dict] | None = None, trace_id: str | None = None) -> dict:
        from uuid import uuid4
        request_trace_id = trace_id or uuid4().hex
        # API calls already own a timeline so persistence before and after this
        # method is visible too. Command-line evaluations get an equivalent local
        # timeline here.
        existing = current_timeline()
        token = None if existing else start_timeline(request_trace_id)
        try:
            result = self.supervisor.run(message=message, user_id=user_id, session_id=session_id,
                                         language=self._language(message, history or []), history=history or [],
                                         trace_id=request_trace_id)
            if token is not None:
                timeline = current_timeline()
                result["stage_timings"] = timeline.snapshot() if timeline else []
                result["model_usage"] = timeline.model_usage() if timeline else {"llm_calls": 0, "calls": []}
            return result
        except Exception as exc:
            # The HTTP boundary persists this telemetry even for a 503. Keeping it
            # on the exception avoids logging request content to diagnose a timeout.
            timeline = current_timeline()
            setattr(exc, "stage_timings", timeline.snapshot() if timeline else [])
            raise
        finally:
            if token is not None:
                finish_timeline(token)

    @staticmethod
    def _language(message: str, history: list[dict]) -> str:
        from .language import detect_language
        return detect_language(message, history)
