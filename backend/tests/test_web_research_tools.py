from __future__ import annotations
import json

from app.agents.web_research_agent import WebResearchAgent


class FakeResponse:
    def __init__(self, payload, text=""):
        self.payload = payload; self.text = text
    def raise_for_status(self): return None
    def json(self): return self.payload


def test_weather_agent_calls_geocoding_and_open_meteo(monkeypatch):
    calls = []
    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if "geocoding" in url:
            return FakeResponse({"results": [{"name": "Porto Alegre", "admin1": "Rio Grande do Sul", "country": "Brazil", "latitude": -30.03, "longitude": -51.23}]})
        return FakeResponse({"daily": {"time": ["2026-11-01"], "temperature_2m_min": [18], "temperature_2m_max": [27], "precipitation_probability_max": [20], "weather_code": [2]}})
    monkeypatch.setattr("app.agents.web_research_agent.requests.get", fake_get)
    result = WebResearchAgent().weather("What's the weather in Porto Alegre?", "en")
    assert result["tool_result"]["tool"] == "open_meteo_weather"
    assert "27°C" in result["answer"]
    assert len(calls) == 2


def test_currency_agent_returns_provider_date_and_rate(monkeypatch):
    def fake_get(url, **kwargs):
        return FakeResponse({"date": "2026-10-30", "rates": {"BRL": 6.15}})
    monkeypatch.setattr("app.agents.web_research_agent.requests.get", fake_get)
    result = WebResearchAgent().exchange_rate("What's the euro rate in Brazil today?", "en")
    assert "6.1500 BRL" in result["answer"]
    assert result["tool_result"]["date"] == "2026-10-30"


def test_general_search_returns_linked_results(monkeypatch):
    html = '''<div class="result"><div class="result__title"><a href="https://example.org/article">Example result</a></div><a class="result__snippet">A useful public snippet.</a></div>'''
    def fake_get(url, **kwargs): return FakeResponse({}, html)
    monkeypatch.setattr("app.agents.web_research_agent.requests.get", fake_get)
    result = WebResearchAgent().search("Explain a public topic", "en")
    assert result["sources"][0]["url"] == "https://example.org/article"
    assert "A useful public snippet" in result["answer"]


def test_weather_location_extraction_removes_relative_date():
    assert WebResearchAgent._extract_location("What's the weather forecast in Porto Alegre tomorrow?") == "Porto Alegre"
    assert WebResearchAgent._extract_location("Qual a previsão do tempo em Novo Hamburgo amanhã?") == "Novo Hamburgo"


class WebModel:
    model = "scripted-test-model"

    def __init__(self, tool_calls, answer):
        self.tool_calls, self.answer, self.calls = tool_calls, answer, []

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None, temperature=0.0, max_tokens=None, purpose="chat"):
        self.calls.append((purpose, messages[-1]["content"]))
        if purpose == "web_parameter_extraction":
            return {"message": {"tool_calls": self.tool_calls}}
        return {"message": {"content": self.answer}}


def test_web_agent_uses_model_parameters_and_writes_answer_from_provider_result(monkeypatch):
    requested = {}

    def fake_get(url, **kwargs):
        requested.update(kwargs["params"])
        return FakeResponse({"date": "2026-10-30", "rates": {"BRL": 5.42}})

    monkeypatch.setattr("app.agents.web_research_agent.requests.get", fake_get)
    model = WebModel([{"function": {"name": "get_exchange_rate", "arguments": {"base": "usd", "quote": "BRL"}}}],
                     "Segundo a Frankfurter, em 2026-10-30, 1 USD = 5.42 BRL (taxa de referência, não é cotação Getnet).")
    result = WebResearchAgent(llm=model).run("Quanto está o dólar?", "pt")

    assert requested == {"base": "USD", "symbols": "BRL"}
    assert [purpose for purpose, _ in model.calls] == ["web_parameter_extraction", "web_answer"]
    assert json.loads(model.calls[1][1])["provider_result"]["rate"] == 5.42
    assert "llm_parameter_extraction" in result["trace"] and "llm_answer_from_tool_result" in result["trace"]
    assert result["answer"] == model.answer


def test_web_agent_falls_back_to_keyword_routing_when_model_picks_no_tool(monkeypatch):
    monkeypatch.setattr("app.agents.web_research_agent.requests.get",
                        lambda url, **kwargs: FakeResponse({"date": "2026-10-30", "rates": {"BRL": 6.15}}))
    model = WebModel([], "1 EUR = 6.15 BRL em 2026-10-30 (Frankfurter).")
    result = WebResearchAgent(llm=model).run("What's the euro exchange rate today?", "en")

    assert "web_regex_fallback" in result["trace"]
    assert result["tool_result"]["base"] == "EUR"


def test_web_agent_reports_provider_outage_without_generating(monkeypatch):
    import requests as _requests

    def down(url, **kwargs):
        raise _requests.ConnectionError("down")

    monkeypatch.setattr("app.agents.web_research_agent.requests.get", down)
    model = WebModel([{"function": {"name": "get_exchange_rate", "arguments": {"base": "EUR", "quote": "BRL"}}}], "invented 9.99")
    result = WebResearchAgent(llm=model).run("Euro hoje?", "pt")

    assert result["tool_result"]["available"] is False
    assert [purpose for purpose, _ in model.calls] == ["web_parameter_extraction"]
    assert "9.99" not in result["answer"]
