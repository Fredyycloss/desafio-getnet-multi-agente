"""Knowledge Agent with tools chosen by the LLM: RAG, live official pages, web, weather, FX."""
import json

from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.web_research_agent import WebResearchAgent

DOCS = [
    {"title": "Link de Pagamento", "section": "Como funciona", "url": "https://site.getnet.com.br/link-de-pagamento/",
     "content": "O Link de Pagamento permite vender pelo WhatsApp e redes sociais com crédito, débito e Pix.",
     "language": "pt", "content_hash": "h1"},
    {"title": "Get Smart", "section": "Recursos", "url": "https://site.getnet.com.br/get-smart/",
     "content": "A Get Smart aceita aproximação, Pix e tem impressora integrada.", "language": "pt", "content_hash": "h2"},
]


class ToolModel:
    model, embedding_model = "fake", "fake-embed"

    def __init__(self, calls):
        self.calls = calls
        self.purposes = []

    def embed(self, texts):
        from app.infra.llm import LLMUnavailable
        raise LLMUnavailable("no embeddings")

    def chat(self, messages, tools=None, *, purpose="chat", **kwargs):
        self.purposes.append(purpose)
        if purpose == "knowledge:tool_selection":
            return {"message": {"tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in self.calls]}}
        payload = messages[-1]["content"]
        return {"message": {"content": "RESPOSTA baseada em: " + payload[-300:]}}


class FakeWeb(WebResearchAgent):
    def __init__(self):
        super().__init__()
        self.seen = []

    def exchange_rate(self, question, language, *, base=None, quote=None):
        self.seen.append(("fx", base, quote))
        return {"answer": "template", "sources": [{"title": "Frankfurter", "url": "https://www.frankfurter.dev/"}],
                "tool_result": {"tool": "frankfurter_exchange_rates", "date": "2026-11-03", "base": base, "quote": quote or "BRL", "rate": 6.1234}}

    def weather(self, question, language, *, location=None, day=""):
        return self._unavailable("weather", language, "provider_unavailable")


def test_llm_picks_exchange_rate_tool_and_answer_is_written_from_the_tool_result():
    web = FakeWeb()
    model = ToolModel([("get_exchange_rate", {"base": "eur", "quote": "brl"})])
    result = KnowledgeAgent(DOCS, llm=model, web=web).run("Quanto está o euro hoje?", "pt")
    assert web.seen == [("fx", "EUR", "BRL")]
    assert "tool:get_exchange_rate" in result["trace"] and "llm_tool_selection" in result["trace"]
    assert result["tool_result"]["rate"] == 6.1234 and not result["degraded"]
    assert "6.1234" in result["answer"] and model.purposes == ["knowledge:tool_selection", "knowledge"]
    assert result["sources"][0]["url"] == "https://www.frankfurter.dev/"


def test_llm_picks_rag_and_cites_official_page():
    model = ToolModel([("search_getnet_knowledge", {"query": "vender pelo WhatsApp link de pagamento"})])
    result = KnowledgeAgent(DOCS, llm=model, web=FakeWeb()).run("Posso vender pelo WhatsApp?", "pt")
    assert "tool:search_getnet_knowledge" in result["trace"]
    assert result["sources"][0]["url"] == "https://site.getnet.com.br/link-de-pagamento/"
    assert result["sources"][0]["section"] == "Como funciona"


def test_no_tool_call_on_currency_question_is_a_marked_fallback_not_a_silent_success():
    model = ToolModel([])
    result = KnowledgeAgent(DOCS, llm=model, web=FakeWeb()).run("What's the euro exchange rate today?", "en")
    assert "no_tool_call_keyword_fallback" in result["trace"] and "tool:get_exchange_rate" in result["trace"]
    assert result["degraded"] is True and result["degraded_reason"] == "model_selected_no_tool"


def test_provider_down_reports_unavailable_and_invents_nothing():
    model = ToolModel([("get_weather_forecast", {"city": "Porto Alegre", "day": "tomorrow"})])
    result = KnowledgeAgent(DOCS, llm=model, web=FakeWeb()).run("Vai chover amanhã em Porto Alegre?", "pt")
    assert result["degraded_reason"] == "provider_unavailable" and "Não vou inventar" in result["answer"]
    assert model.purposes == ["knowledge:tool_selection"]  # no generation without data


def test_low_relevance_rag_reads_official_pages_live(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_LIVE_READ", "true")
    seen = {}

    def fake_live(query, documents, language, **kwargs):
        seen["query"] = query
        return [{"title": "Get Ajuda", "url": "https://site.getnet.com.br/get-ajuda/", "section": "live",
                 "content": "Conteúdo lido ao vivo da página oficial.", "score": 0.5}]
    monkeypatch.setattr("app.agents.knowledge_tools.site_live_search", fake_live)
    model = ToolModel([("search_getnet_knowledge", {"query": "assunto inexistente zzzz"})])
    result = KnowledgeAgent(DOCS, llm=model, web=FakeWeb()).run("assunto inexistente zzzz", "pt")
    assert "rag_low_relevance_site_live" in result["trace"] and seen["query"] == "assunto inexistente zzzz"
    assert result["sources"][0]["url"] == "https://site.getnet.com.br/get-ajuda/"


def test_without_model_keyword_fallback_still_uses_the_tools_and_is_degraded():
    result = KnowledgeAgent(DOCS, llm=None, web=FakeWeb()).run("Qual a cotação do euro?", "pt")
    assert "keyword_tool_selection_fallback" in result["trace"] and "tool:get_exchange_rate" in result["trace"]
    assert result["degraded"] is True
