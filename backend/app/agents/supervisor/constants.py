"""Supervisor tool schemas, fast-path agents, aliases and markers."""
from __future__ import annotations

# Home-screen suggestions (frontend) -> specialist. A click is an explicit topic choice, like a menu
# option: no clarification, direct dispatch. settlement_timing needs the customer's records, so an
# anonymous session is answered from the knowledge base with a login hint.
HOME_TOPICS = {
    "products_compare": "knowledge_specialist",
    "settlement_timing": "payments_specialist",
    "terminal_connection": "customer_support_specialist",
    "payment_link": "knowledge_specialist",
}

SUPERVISOR_TOOLS = [
    {"type": "function", "function": {"name": "knowledge_specialist", "description": "Delegate Getnet product, service, fee, payment-method or procedure questions AND public information (weather, exchange rates, general web questions) to the Knowledge agent. It chooses its own tools (official-site RAG, live official pages, web search, weather, exchange rates) and drafts a grounded answer with sources.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Standalone question retaining product, issue and user context. If the customer's message covers more than one topic (e.g. a product question AND a settlement/account question for another specialist), extract ONLY the part this agent should answer here -- passing the whole multi-topic message dilutes its search and can make it find no evidence for a part it would otherwise answer fine."}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "customer_support_specialist", "description": "Delegate account profile and card-terminal/connection problems to the support specialist. It inspects synthetic SQLite data through typed tools.", "parameters": {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]}}},
    {"type": "function", "function": {"name": "payments_specialist", "description": "Delegate sales, settlement/deposit dates and declined transactions to the payments specialist. It inspects synthetic SQLite data through typed tools.", "parameters": {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]}}},
    {"type": "function", "function": {"name": "risk_assessment_specialist", "description": "Assess ambiguous device/physical safety reports. If risk is elevated, stop routine troubleshooting and escalate.", "parameters": {"type": "object", "properties": {"issue": {"type": "string"}}, "required": ["issue"]}}},
    {"type": "function", "function": {"name": "human_escalation_specialist", "description": "Create a persistent simulated human-support ticket and return a protocol. Use for explicit human requests, unresolved problems, low confidence, or elevated safety incidents. Do not claim a real operator is connected.", "parameters": {"type": "object", "properties": {"reason": {"type": "string"}, "summary": {"type": "string"}, "severity": {"type": "string", "enum": ["normal", "high", "critical"]}}, "required": ["reason", "summary", "severity"]}}},
]
# Specialists that may be dispatched directly when Context Intelligence is confident.
FAST_PATH_AGENTS = {"knowledge_specialist", "customer_support_specialist", "payments_specialist"}
# Web research is a set of Knowledge-agent tools (challenge: "Knowledge Agent ... RAG plus a web
# search tool"). The old specialist name is still accepted from models/classifiers as an alias.
AGENT_ALIASES = {"web_research_specialist": "knowledge_specialist"}


def canonical_agent(name: str) -> str:
    return AGENT_ALIASES.get(name, name)
# Keys of the context assessment the planner needs; the rest only inflates the prompt.
PLANNER_CONTEXT_KEYS = ("intent", "risk_level", "recommended_agents", "confidence", "figurative_language")
FINAL_MARKER = "FINAL"


