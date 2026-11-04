from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta
from urllib.parse import parse_qs, unquote, urlparse

import json
import time

import requests
from bs4 import BeautifulSoup

from ..infra.llm import LLMProvider, LLMUnavailable
from ..language import normalize
from .specialist import degraded_reason_for, specialist_result

logger = logging.getLogger(__name__)

CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
WEB_TOOLS = [
    {"type": "function", "function": {"name": "get_weather_forecast", "description": "Daily weather forecast from Open-Meteo for a city.", "parameters": {"type": "object", "properties": {
        "city": {"type": "string", "description": "City name, e.g. Porto Alegre"},
        "day": {"type": "string", "description": "today, tomorrow, or an ISO date within the next 6 days"}}, "required": ["city"]}}},
    {"type": "function", "function": {"name": "get_exchange_rate", "description": "Latest reference exchange rate from Frankfurter (ECB data).", "parameters": {"type": "object", "properties": {
        "base": {"type": "string", "description": "ISO 4217 code of the currency being priced, e.g. EUR or USD"},
        "quote": {"type": "string", "description": "ISO 4217 code to express the price in; BRL unless the user asks otherwise"}}, "required": ["base", "quote"]}}},
    {"type": "function", "function": {"name": "web_search", "description": "Public web search for general questions.", "parameters": {"type": "object", "properties": {
        "query": {"type": "string"}}, "required": ["query"]}}},
]


class WebResearchAgent:
    """Public web search plus no-key weather and FX APIs for general questions.

    With a model: the LLM extracts tool parameters by function calling, code calls
    the real provider, and the LLM writes the answer from the provider result.
    Keyword/regex routing and sentence templates remain only as labelled fallbacks.
    """
    name = "web_research_agent"

    def __init__(self, timeout: float | None = None, llm: LLMProvider | None = None):
        self.timeout = timeout or min(float(os.getenv("REQUEST_TIMEOUT_SECONDS", "8")), 12.0)
        self.llm = llm

    def run(self, question: str, language: str = "pt") -> dict:
        started = time.monotonic()
        failure: BaseException | None = None
        if self.llm:
            try:
                result = self._run_with_model(question, language)
            except LLMUnavailable as exc:
                logger.warning("web_research_llm_unavailable error=%s", type(exc).__name__)
                failure = exc
                result = self._run_keyword(question, language)
                result["trace"] = [*result["trace"], "web_template_fallback"]
        else:
            result = self._run_keyword(question, language)
            result["trace"] = [*result["trace"], "web_template_fallback"]
        return self._finish(result, question, started, failure)

    def _finish(self, result: dict, question: str, started: float, failure: BaseException | None) -> dict:
        """Apply the common specialist contract and mark every non-model path as degraded."""
        trace = result.get("trace", [])
        tool = result.get("tool_result") or {}
        if tool.get("available") is False:
            reason = "provider_unavailable"
        elif "web_template_fallback" in trace:
            reason = degraded_reason_for(failure, self.llm is not None) if (failure or not self.llm) else "llm_empty_answer"
        elif "web_regex_fallback" in trace:
            reason = "model_selected_no_tool"
        else:
            reason = None
        return specialist_result(
            agent=self.name, task=question, answer=result["answer"], confidence=result.get("confidence", 0.0), started=started,
            evidence=[tool] if tool else [], sources=result.get("sources", []),
            tool_calls=[{"tool": tool.get("tool"), "args": {k: v for k, v in tool.items() if k in ("location", "base", "quote", "query")},
                         "ok": tool.get("available", True), "duration_ms": None}] if tool else [],
            missing_info=[tool.get("reason")] if tool.get("available") is False else [],
            degraded=reason is not None, degraded_reason=reason, trace=trace, tool_result=tool,
        )

    def _run_with_model(self, question: str, language: str) -> dict:
        response = self.llm.chat(
            [{"role": "system", "content": "Select exactly one tool and fill its parameters from the user's question. Do not answer in text."},
             {"role": "user", "content": question[:600]}],
            WEB_TOOLS, max_tokens=int(os.getenv("OLLAMA_WEB_TOOL_MAX_OUTPUT_TOKENS", "60")), purpose="web_parameter_extraction",
        )
        calls = (response.get("message") or {}).get("tool_calls") or []
        result: dict | None = None
        if calls:
            function = calls[0].get("function", {})
            name = function.get("name")
            args = function.get("arguments") or {}
            if isinstance(args, str):
                try: args = json.loads(args)
                except json.JSONDecodeError: args = {}
            args = args if isinstance(args, dict) else {}
            if name == "get_weather_forecast" and str(args.get("city", "")).strip():
                result = self.weather(question, language, location=str(args["city"]).strip()[:80], day=str(args.get("day") or ""))
            elif name == "get_exchange_rate":
                base, quote = str(args.get("base", "")).upper().strip(), str(args.get("quote", "") or "BRL").upper().strip()
                if CURRENCY_RE.match(base) and CURRENCY_RE.match(quote) and base != quote:
                    result = self.exchange_rate(question, language, base=base, quote=quote)
            elif name == "web_search" and str(args.get("query", "")).strip():
                result = self.search(str(args["query"])[:350], language)
            if result is not None:
                result["trace"] = [result["trace"][0], "llm_parameter_extraction", *result["trace"][1:]]
        if result is None:
            result = self._run_keyword(question, language)
            result["trace"] = [*result["trace"], "web_regex_fallback"]
        if not (result.get("tool_result") or {}).get("available", True):
            return result  # provider unavailable: say so, never invent a value
        try:
            answer = self._write_answer(question, language, result)
        except LLMUnavailable:
            answer = None
        if answer:
            result["answer"] = answer
            result["trace"] = [*result["trace"], "llm_answer_from_tool_result"]
        else:
            result["trace"] = [*result["trace"], "web_template_fallback"]
        return result

    def _write_answer(self, question: str, language: str, result: dict) -> str | None:
        system = (
            "Answer the user's question using ONLY the provider result JSON. Copy numbers, dates and place names exactly; "
            "do not invent or convert values. Name the provider as the source. For exchange rates, say it is a reference market rate, "
            "not a Getnet quote. For search results, summarise briefly and cite the URLs. At most 4 sentences. "
            + ("Respond only in English." if language == "en" else "Responda somente em português brasileiro.")
        )
        payload = {"question": question[:600], "provider_result": result.get("tool_result"),
                   "sources": result.get("sources", [])[:5]}
        response = self.llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            think=False, temperature=0.0, max_tokens=int(os.getenv("OLLAMA_WEB_ANSWER_MAX_OUTPUT_TOKENS", "150")),
            purpose="web_answer",
        )
        content = str((response.get("message") or {}).get("content", "")).strip()
        return content or None

    def _run_keyword(self, question: str, language: str) -> dict:
        normalized = normalize(question)
        if any(word in normalized for word in ("weather", "forecast", "clima", "previsao do tempo", "temperatura")):
            return self.weather(question, language)
        if any(word in normalized for word in ("exchange rate", "euro rate", "currency", "cambio", "cotacao", "taxa de cambio", "dolar", "euro")):
            return self.exchange_rate(question, language)
        return self.search(question, language)

    def weather(self, question: str, language: str, *, location: str | None = None, day: str = "") -> dict:
        location = location or self._extract_location(question) or "Porto Alegre"
        try:
            geo = requests.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": location, "count": 1, "language": "pt" if language == "pt" else "en", "format": "json"}, timeout=self.timeout)
            geo.raise_for_status()
            results = geo.json().get("results", [])
            if not results:
                return self._unavailable("weather", language, "location_not_found")
            place = results[0]
            forecast = requests.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": place["latitude"], "longitude": place["longitude"],
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "forecast_days": 7, "timezone": "auto",
            }, timeout=self.timeout)
            forecast.raise_for_status()
            daily = forecast.json().get("daily", {})
            target = self._target_day(day, question)
            dates = daily.get("time", [])
            if target.isoformat() not in dates:
                target = date.fromisoformat(dates[0]) if dates else target
            idx = dates.index(target.isoformat()) if target.isoformat() in dates else 0
            name = ", ".join(x for x in [place.get("name"), place.get("admin1"), place.get("country")] if x)
            record = {
                "date": dates[idx] if dates else target.isoformat(),
                "min_c": daily.get("temperature_2m_min", [None])[idx],
                "max_c": daily.get("temperature_2m_max", [None])[idx],
                "precipitation_probability_max": daily.get("precipitation_probability_max", [None])[idx],
                "weather_code": daily.get("weather_code", [None])[idx],
            }
            if language == "en":
                answer = f"Forecast for {name} on {record['date']}: low {record['min_c']}°C, high {record['max_c']}°C, maximum precipitation probability {record['precipitation_probability_max']}%. Weather conditions can change; check the provider for updates."
            else:
                answer = f"Previsão para {name} em {record['date']}: mínima de {record['min_c']}°C, máxima de {record['max_c']}°C e probabilidade máxima de precipitação de {record['precipitation_probability_max']}%. A previsão pode mudar; consulte o provedor para atualizações."
            return {"answer": answer, "confidence": 0.95, "sources": [{"title": "Open-Meteo — previsão do tempo", "url": "https://open-meteo.com/"}], "tool_result": {"tool": "open_meteo_weather", "location": name, **record}, "trace": ["web_research_agent", "geocoding_api", "open_meteo_forecast"]}
        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
            logger.warning("weather_api_unavailable error=%s", type(exc).__name__)
            return self._unavailable("weather", language, "provider_unavailable")

    def exchange_rate(self, question: str, language: str, *, base: str | None = None, quote: str | None = None) -> dict:
        normalized = normalize(question)
        base = base or ("USD" if "dolar" in normalized or "usd" in normalized or "dollar" in normalized else "EUR")
        quote = quote or "BRL"
        try:
            response = requests.get("https://api.frankfurter.dev/v1/latest", params={"base": base, "symbols": quote}, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json(); rate = payload["rates"][quote]; rate_date = payload["date"]
            answer = (f"Latest available reference rate ({rate_date}): 1 {base} = {rate:.4f} {quote}. This is a reference market rate, not a Getnet conversion quote; bank spreads, fees and settlement conditions may differ." if language == "en" else f"Última cotação de referência disponível ({rate_date}): 1 {base} = {rate:.4f} {quote}. Esta é uma taxa de referência de mercado, não uma cotação da Getnet; spreads, tarifas e condições de liquidação podem ser diferentes.")
            return {"answer": answer, "confidence": 0.97, "sources": [{"title": "Frankfurter — referência cambial", "url": "https://www.frankfurter.dev/"}], "tool_result": {"tool": "frankfurter_exchange_rates", "date": rate_date, "base": base, "quote": quote, "rate": rate}, "trace": ["web_research_agent", "frankfurter_exchange_rate_api"]}
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.warning("fx_api_unavailable error=%s", type(exc).__name__)
            return self._unavailable("exchange_rate", language, "provider_unavailable")

    def search(self, question: str, language: str) -> dict:
        """General public search through stable providers (see web_search_tool)."""
        from .web_search_tool import search_web
        found = search_web(question, language, max_results=3)
        if not found["ok"]:
            return self._unavailable("web_search", language, "provider_unavailable" if found["errors"] else "no_search_results")
        results = found["results"]
        bullets = "\n".join(f"- {item['title']}: {item['snippet']} ({item['url']})" for item in results)
        answer = ("Public sources found (verify important facts with the publisher):\n" if language == "en"
                  else "Fontes públicas encontradas (confirme informações importantes com o publicador):\n") + bullets
        return {"answer": answer, "confidence": 0.72, "sources": [{"title": x["title"], "url": x["url"]} for x in results],
                "tool_result": {"tool": "web_search", "provider": found["provider"], "query": question, "results": results},
                "trace": ["web_research_agent", f"web_search:{found['provider']}"]}

    @staticmethod
    def _target_day(day: str, question: str) -> date:
        value = normalize(day or "")
        if value in {"tomorrow", "amanha"}:
            return date.today() + timedelta(days=1)
        if value in {"today", "hoje"}:
            return date.today()
        try:
            parsed = date.fromisoformat(day.strip())
            if 0 <= (parsed - date.today()).days <= 6:
                return parsed
        except ValueError:
            pass
        return date.today() + timedelta(days=1) if any(w in normalize(question) for w in ("tomorrow", "amanha")) else date.today()

    @staticmethod
    def _extract_location(question: str) -> str | None:
        text = question.strip().rstrip("?!. ")
        text = re.sub(r"\b(?:today|tomorrow|tonight|hoje|amanh[ãa]|esta noite)\b", "", text, flags=re.IGNORECASE).strip()
        patterns = [
            r"\b(?:in|for)\s+(.+)$",
            r"\b(?:em|para|no|na)\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip(" ,.")
                if len(value) > 2:
                    return value
        return None

    @staticmethod
    def _unavailable(kind: str, language: str, reason: str) -> dict:
        answer = (f"I could not retrieve {kind.replace('_', ' ')} data because the provider is currently unavailable. I will not invent a value. Please retry or consult the provider directly." if language == "en" else f"Não consegui consultar os dados de {kind.replace('_', ' ')} porque o provedor está indisponível. Não vou inventar um valor. Tente novamente ou consulte diretamente o provedor.")
        return {"answer": answer, "confidence": 0.0, "sources": [], "tool_result": {"tool": kind, "available": False, "reason": reason}, "trace": ["web_research_agent", "provider_unavailable"]}
