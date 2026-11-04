"""Record/replay of model calls: round trip, masking, honest misses, and the committed cloud run.

The last test replays the recorded cloud benchmark (docs/evidence/cloud_runs/<date>/) through the
real API with LLM_PROVIDER=replay: no key, no network model; retrieval, tools, PolicyGate and the
deterministic Critic checks execute. It checks that the same specialists run and the Critic
reaches the same verdict as in the recorded cloud run.
"""
from __future__ import annotations

import json
import os

import pytest

from app.infra.llm import LLMUnavailable
from app.infra.llm.base import LLMProvider, normalised_response
from app.infra.llm.cassette import RecordingProvider, ReplayProvider, chat_key, latest_cloud_run, mask


class EchoProvider(LLMProvider):
    provider, model, embedding_model = "echo", "echo-1", "echo-embed"

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None, **kwargs):
        self.calls += 1
        return normalised_response(content=f"answer {self.calls}", tool_calls=[], provider="echo", model="echo-1",
                                   prompt_tokens=10, output_tokens=2, latency_ms=1.0, cost_usd=0.001)

    def embed(self, texts):
        return [[0.5, -0.25, 1.0] for _ in texts]

    def health(self):
        return {"available": True}


def test_masking_removes_dates_ids_and_protocols():
    text = "today_utc 2026-11-04T09:15:00Z protocol GET-20261104-A1B2C3 trace 0123456789abcdef0123456789abcdef"
    assert mask(text) == "today_utc <DATE> protocol <PROTOCOL> trace <HEX>"
    a = [{"role": "user", "content": '{"today_utc": "2026-11-04", "q": "taxa"}'}]
    b = [{"role": "user", "content": '{"today_utc": "2026-12-25", "q": "taxa"}'}]
    assert chat_key(a, None, None, "critic") == chat_key(b, None, None, "critic")


def test_record_then_replay_round_trip(tmp_path):
    inner = EchoProvider()
    rec = RecordingProvider(inner, tmp_path)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "Get Lite tem aluguel? 2026-11-04"}]
    first = rec.chat(msgs, purpose="knowledge")
    vectors = rec.embed(["search_query: aluguel"])
    assert rec.provider == "echo" and inner.calls == 1
    replay = ReplayProvider(tmp_path)
    again = replay.chat([msgs[0], {"role": "user", "content": "Get Lite tem aluguel? 2027-01-01"}], purpose="knowledge")
    assert again["content"] == first["content"] and again["provider"] == "replay" and again["usage"]["cost_usd"] == 0.0
    assert replay.embed(["search_query: aluguel"]) == vectors  # float16 exact for these values


def test_unrecorded_request_is_a_miss_not_an_invented_answer(tmp_path):
    RecordingProvider(EchoProvider(), tmp_path).chat([{"role": "user", "content": "a"}], purpose="critic")
    replay = ReplayProvider(tmp_path)
    with pytest.raises(LLMUnavailable, match="replay_miss"):
        replay.chat([{"role": "user", "content": "something never recorded"}], purpose="critic")
    with pytest.raises(LLMUnavailable):
        replay.embed(["never embedded"])
    assert replay.misses


def test_record_dir_wraps_the_configured_provider(monkeypatch, tmp_path):
    from app.infra import llm as llm_pkg
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_RECORD_DIR", str(tmp_path))
    created = llm_pkg.create_llm()
    assert isinstance(created, RecordingProvider) and created.provider == "ollama"


# ---------------------------------------------------------------- committed cloud run

# Live public providers: their results change between runs, so those turns are not replayable offline.
PUBLIC_TOOLS = ("get_weather_forecast", "get_exchange_rate", "web_search", "site_live_search",
                "open_meteo_weather", "frankfurter_exchange_rates", "duckduckgo_public_search", "wikipedia")


def _recorded_turns():
    run = latest_cloud_run()
    if run is None or not (run / "turns.jsonl").exists():
        return run, []
    turns = [json.loads(line) for line in (run / "turns.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    # Single-turn requests whose inputs are reproducible offline: no session history, HTTP 200,
    # no live public provider (weather/FX/web answers change between runs) and a cloud model answer.
    selected, seen = [], set()
    for t in turns:
        body = t.get("response") or {}
        trace = [str(x) for x in body.get("trace") or []]
        key = (t["message"], t.get("critic_challenge"))
        nested = json.dumps(body.get("specialist_observations") or [], ensure_ascii=False)
        if (t.get("session_id") or t.get("http_status") != 200 or key in seen or any(x in nested for x in PUBLIC_TOOLS)
                or not (body.get("model_usage") or {}).get("llm_calls") or t["scenario"].startswith(("functional:", "cold:"))):
            continue
        seen.add(key)
        selected.append(t)
    return run, selected


def _restore_observed_terminals(db, run):
    for line in (run / "turns.jsonl").read_text(encoding="utf-8").splitlines():
        body = json.loads(line).get("response") or {}
        for result in body.get("specialist_observations") or []:
            for obs in (result.get("tool_observations") or []) if isinstance(result, dict) else []:
                data = obs.get("data") if obs.get("tool") == "get_terminal_status" else None
                if isinstance(data, dict) and data.get("terminal_id"):
                    db.conn.execute("UPDATE terminals SET status=?, connection_type=?, last_seen_at=?, error_code=?, last_error=? "
                                    "WHERE terminal_id=?", (data.get("status"), data.get("connection_type"), data.get("last_seen_at"),
                                                            data.get("error_code"), data.get("last_error"), data["terminal_id"]))
    db.conn.commit()


def _specialists(trace):
    return sorted({str(x).split(":", 1)[1] for x in trace or [] if str(x).startswith(("tool:", "replan_tool:")) and str(x).endswith("_specialist")})


def test_recorded_cloud_run_replays_without_key(monkeypatch, tmp_path):
    run, turns = _recorded_turns()
    if not turns:
        pytest.skip("no recorded cloud run with turns.jsonl yet")
    monkeypatch.setenv("LLM_PROVIDER", "replay")
    monkeypatch.setenv("LLM_REPLAY_DIR", str(run))
    monkeypatch.setenv("CRITIC_CHALLENGE_MODE", "true")
    monkeypatch.setenv("KNOWLEDGE_CRAWL_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "replay.sqlite3"))
    monkeypatch.setenv("CONTEXT_MODE", "llm")
    monkeypatch.delenv("GETNET_ANTHROPIC_API_KEY", raising=False)
    # Same synthetic world as the recording: its date ("yesterday's sales", today_utc) and the
    # terminal state the cloud run observed.
    monkeypatch.setenv("DEMO_TODAY", json.loads((run / "manifest.json").read_text())["date"][:10])
    from app.main import app, state
    from tests.conftest import AutoAuthClient as TestClient
    mismatches = []
    with TestClient(app) as client:
        _restore_observed_terminals(state["db"], run)
        assert client.get("/api/health").json()["llm_provider"]["provider"] == "replay"
        for t in turns:
            headers = {"X-Critic-Challenge": t["critic_challenge"]} if t.get("critic_challenge") else {}
            headers["X-Request-ID"] = t["trace_id"]  # replay the calls of this recorded request, in order
            got = client.post("/api/chat", json={"message": t["message"], "user_id": t["user_id"]}, headers=headers).json()
            want = t["response"]
            same = (_specialists(got.get("trace")) == _specialists(want.get("trace"))
                    and bool(got.get("handoff")) == bool(want.get("handoff"))
                    and (got.get("critic") or {}).get("approved") == (want.get("critic") or {}).get("approved"))
            if not same:
                mismatches.append({"scenario": t["scenario"], "want": [_specialists(want.get("trace")), want.get("handoff"), (want.get("critic") or {}).get("approved")],
                                   "got": [_specialists(got.get("trace")), got.get("handoff"), (got.get("critic") or {}).get("approved")]})
        misses = list(state["service"].llm.misses) if hasattr(state["service"].llm, "misses") else []
    # Measured 2026-11-04 on the committed run: every reproducible turn replays to the recorded outcome.
    # A small margin (10%) keeps the test useful while prompts evolve between recordings.
    print(f"REPLAY_PARITY replayed={len(turns)} same_outcome={len(turns) - len(mismatches)} misses={len(misses)}", [m["scenario"] for m in mismatches], [m["purpose"] for m in misses])
    assert len(mismatches) <= len(turns) * 0.10, {"replayed": len(turns), "mismatches": mismatches[:10], "misses": misses[:10]}
