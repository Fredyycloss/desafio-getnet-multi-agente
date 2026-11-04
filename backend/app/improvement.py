"""Continuous improvement with human review (V6 block 6). The model never learns by itself.

* Feedback: 👍/👎 per answer (POST /api/feedback with the trace_id). Stored as ids + rating +
  a reason code: no message text.
* Validated answers: a Knowledge answer (no customer-data tool, Critic-approved, with sources)
  that the customer rated 👍 is kept with its sources, evidence and the corpus version. A
  semantically equal question (cosine of nomic query embeddings, or the same normalised text)
  reuses it (trace validated_answer_hit) while the corpus version is unchanged. Never used for
  customer data.
* Knowledge gaps: abstention, clarification menus, Critic rejections and 👎 go to a review
  queue (/api/operator/knowledge-gaps, operator token). Only an operator promotes a gap: to the
  knowledge base (an answer with an official source URL) or to the classifier examples (an
  intent). Nothing enters by itself, and text that overlaps the evaluation datasets is refused.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from .memory import _redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT NOT NULL, user_id TEXT NOT NULL, rating INTEGER NOT NULL,
  reason TEXT, created_at TEXT NOT NULL, UNIQUE(trace_id, user_id)
);
CREATE TABLE IF NOT EXISTS validated_answers (
  id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, question_norm TEXT NOT NULL, language TEXT NOT NULL,
  embedding_json TEXT, answer TEXT NOT NULL, sources_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
  corpus_version TEXT NOT NULL, trace_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS knowledge_gaps (
  id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT NOT NULL, kind TEXT NOT NULL, question TEXT NOT NULL,
  language TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', reviewer TEXT, note TEXT, created_at TEXT NOT NULL,
  decided_at TEXT, UNIQUE(trace_id, kind)
);
CREATE TABLE IF NOT EXISTS curated_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT, gap_id INTEGER, question TEXT NOT NULL, answer TEXT NOT NULL, source_url TEXT NOT NULL,
  language TEXT NOT NULL, reviewer TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS classifier_extra_examples (
  id INTEGER PRIMARY KEY AUTOINCREMENT, gap_id INTEGER, text TEXT NOT NULL, intent TEXT NOT NULL, reviewer TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""
FEEDBACK_REASONS = {"wrong", "incomplete", "not_helpful", "unsafe", "other"}
OFFICIAL_HOSTS = ("getnet.com.br", "getnet.net", "santander.com.br")
VALIDATED_MIN_SIMILARITY = 0.93
EVAL_DIR = Path(__file__).resolve().parent / "evaluation"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _grams(text: str, n: int = 4) -> set[str]:
    words = normalise(text).split()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


@lru_cache(maxsize=1)
def evaluation_grams() -> frozenset[str]:
    """4-grams of every evaluation message (context splits, answer quality, retrieval, orchestration)."""
    texts: list[str] = []
    for path in EVAL_DIR.glob("context_scenarios_*.json"):
        texts += [c.get("message", "") for c in json.loads(path.read_text(encoding="utf-8"))]
    for path in EVAL_DIR.glob("*.jsonl"):
        texts += [json.loads(line).get("question", "") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for name in ("retrieval_questions.json", "retrieval_calibration.json"):
        path = EVAL_DIR / name
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            texts += [q.get("question", "") for q in (data if isinstance(data, list) else data.get("questions", []))]
    orchestration = EVAL_DIR / "orchestration_scenarios.json"
    if orchestration.exists():
        data = json.loads(orchestration.read_text(encoding="utf-8"))
        texts += [c["message"] for key in ("multi_intent", "replan") for c in data.get(key, [])]
    return frozenset(g for t in texts for g in _grams(t))


def overlaps_evaluation(text: str) -> bool:
    return bool(_grams(text) & evaluation_grams())


def corpus_version(documents: list[dict], curated_count: int = 0) -> str:
    snapshot = sorted({str(d.get("corpus_version") or d.get("fetched_at", "")[:10]) for d in documents if d})[-1:] or ["legacy"]
    digest = hashlib.sha256("|".join(sorted(d.get("content_hash") or d.get("url", "") for d in documents)).encode()).hexdigest()[:10]
    return f"{snapshot[0]}:{digest}:curated{curated_count}"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class ImprovementLoop:
    def __init__(self, db):
        self.db = db
        self.corpus_version = "unknown"
        with db.lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    # ------------------------------------------------------------- lookup of a turn
    def _turn(self, trace_id: str, user_id: str) -> tuple[dict, str] | None:
        """(assistant result metadata, preceding user question) of a turn the caller owns."""
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT m.id, m.session_id, m.metadata_json FROM messages m JOIN sessions s ON s.session_id=m.session_id "
                "WHERE m.role='assistant' AND s.user_id=? AND json_extract(m.metadata_json,'$.trace_id')=? ORDER BY m.id DESC LIMIT 1",
                (user_id, trace_id)).fetchone()
            if row is None:
                return None
            question = self.db.conn.execute("SELECT content FROM messages WHERE session_id=? AND role='user' AND id<? ORDER BY id DESC LIMIT 1",
                                            (row["session_id"], row["id"])).fetchone()
        return json.loads(row["metadata_json"] or "{}"), (question["content"] if question else "")

    @staticmethod
    def validatable(result: dict) -> bool:
        """Knowledge-only, Critic-approved by the model, grounded, no customer data, no hand-off."""
        trace = [str(x) for x in result.get("trace") or []]
        specialists = {x.split(":", 1)[1] for x in trace if x.startswith(("tool:", "replan_tool:")) and x.endswith("_specialist")}
        observations = json.dumps(result.get("specialist_observations") or [], ensure_ascii=False)
        return (specialists == {"knowledge_specialist"} and (result.get("critic") or {}).get("approved") is True
                and (result.get("critic") or {}).get("mode") == "llm_critic" and bool(result.get("sources"))
                and not result.get("degraded") and not result.get("handoff") and not result.get("pending_action")
                and "validated_answer_hit" not in trace
                and not any(t in observations for t in ("lookup_payment_status", "find_declined_transactions",
                                                        "get_terminal_status", "get_customer_profile")))

    # ------------------------------------------------------------- feedback
    def feedback(self, trace_id: str, user_id: str, rating: str, reason: str | None, embed=None) -> dict:
        turn = self._turn(trace_id, user_id)
        if turn is None:
            return {"ok": False, "error": "not_found"}
        result, question = turn
        value = 1 if rating == "up" else -1
        reason = reason if reason in FEEDBACK_REASONS else None
        with self.db.lock:
            self.db.conn.execute("INSERT INTO feedback(trace_id,user_id,rating,reason,created_at) VALUES(?,?,?,?,?) "
                                 "ON CONFLICT(trace_id,user_id) DO UPDATE SET rating=excluded.rating, reason=excluded.reason",
                                 (trace_id, user_id, value, reason, _now()))
            self.db.conn.commit()
        out = {"ok": True, "rating": rating, "validated": False}
        if value < 0:
            self.record_gap(trace_id, "thumbs_down", question, result.get("language", "pt"))
            with self.db.lock:  # a 👎 withdraws a validated answer built from this turn
                self.db.conn.execute("UPDATE validated_answers SET active=0 WHERE trace_id=?", (trace_id,))
                self.db.conn.commit()
        elif self.validatable(result) and question:
            vector = None
            if embed is not None:
                try:
                    vector = embed(question)
                except Exception:  # noqa: BLE001 - text match still works
                    vector = None
            evidence = [o for s in result.get("specialist_observations") or [] for o in (s.get("evidence") or [])][:4]
            with self.db.lock:
                self.db.conn.execute(
                    "INSERT OR IGNORE INTO validated_answers(question,question_norm,language,embedding_json,answer,sources_json,"
                    "evidence_json,corpus_version,trace_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (_redact(question)[:600], normalise(question), result.get("language", "pt"), json.dumps(vector) if vector else None,
                     result["answer"], json.dumps(result.get("sources") or [], ensure_ascii=False),
                     json.dumps([{"title": e.get("title"), "url": e.get("url"), "section": e.get("section"),
                                  "content": str(e.get("content") or "")[:900]} for e in evidence], ensure_ascii=False),
                     self.corpus_version, trace_id, _now()))
                self.db.conn.commit()
            out["validated"] = True
        return out

    def lookup(self, question: str, language: str, vector_fn=None) -> dict | None:
        """vector_fn(question) -> query embedding; called only when candidate answers exist."""
        norm = normalise(question)
        with self.db.lock:
            rows = self.db.conn.execute("SELECT * FROM validated_answers WHERE active=1 AND language=? AND corpus_version=?",
                                        (language, self.corpus_version)).fetchall()
        if not rows:
            return None
        vector = None
        if vector_fn is not None and any(r["embedding_json"] for r in rows):
            try:
                vector = vector_fn(question)
            except Exception:  # noqa: BLE001 - text match still works
                vector = None
        best, best_score = None, 0.0
        for row in rows:
            score = 1.0 if row["question_norm"] == norm else 0.0
            if vector and row["embedding_json"]:
                score = max(score, _cosine(vector, json.loads(row["embedding_json"])))
            if score > best_score:
                best, best_score = row, score
        if best is None or best_score < VALIDATED_MIN_SIMILARITY:
            return None
        return {"answer": best["answer"], "sources": json.loads(best["sources_json"]), "evidence": json.loads(best["evidence_json"]),
                "similarity": round(best_score, 4), "validated_id": best["id"], "corpus_version": best["corpus_version"]}

    # ------------------------------------------------------------- gaps
    def record_gap(self, trace_id: str, kind: str, question: str, language: str) -> None:
        if not question:
            return
        with self.db.lock:
            self.db.conn.execute("INSERT OR IGNORE INTO knowledge_gaps(trace_id,kind,question,language,created_at) VALUES(?,?,?,?,?)",
                                 (trace_id, kind, _redact(question)[:600], language, _now()))
            self.db.conn.commit()

    @staticmethod
    def gap_kind(result: dict) -> str | None:
        mode, intent = result.get("orchestration_mode"), result.get("intent")
        if mode == "grounded_knowledge_abstention" or "abstention" in (result.get("trace") or []):
            return "abstention"
        if mode == "context_policy_clarification":
            return "clarification"
        if intent == "quality_escalation":
            return "critic_rejection"
        return None

    def list_gaps(self, status: str | None = "open", limit: int = 100) -> list[dict]:
        with self.db.lock:
            rows = self.db.conn.execute("SELECT * FROM knowledge_gaps WHERE (? IS NULL OR status=?) ORDER BY id DESC LIMIT ?",
                                        (status, status, limit)).fetchall()
        return [dict(r) for r in rows]

    def decide_gap(self, gap_id: int, reviewer: str, action: str, *, answer: str | None = None, source_url: str | None = None,
                   intent: str | None = None, note: str | None = None, known_intents: set[str] | None = None) -> dict:
        with self.db.lock:
            gap = self.db.conn.execute("SELECT * FROM knowledge_gaps WHERE id=?", (gap_id,)).fetchone()
        if gap is None:
            return {"ok": False, "error": "not_found"}
        if gap["status"] != "open":
            return {"ok": False, "error": "already_decided"}
        if action == "dismiss":
            status = "dismissed"
        elif action in ("promote_kb", "promote_classifier"):
            text = (answer or "") + " " + gap["question"]
            if overlaps_evaluation(text):
                return {"ok": False, "error": "overlaps_evaluation_dataset"}
            if action == "promote_kb":
                host = urlparse(source_url or "").hostname or ""
                if not answer or len(answer.strip()) < 20 or not any(host == h or host.endswith("." + h) for h in OFFICIAL_HOSTS):
                    return {"ok": False, "error": "answer_and_official_source_required"}
                with self.db.lock:
                    self.db.conn.execute("INSERT INTO curated_entries(gap_id,question,answer,source_url,language,reviewer,created_at) "
                                         "VALUES(?,?,?,?,?,?,?)", (gap_id, gap["question"], answer.strip()[:2000], source_url,
                                                                    gap["language"], reviewer, _now()))
                status = "promoted_kb"
            else:
                if not intent or (known_intents is not None and intent not in known_intents):
                    return {"ok": False, "error": "known_intent_required"}
                with self.db.lock:
                    self.db.conn.execute("INSERT INTO classifier_extra_examples(gap_id,text,intent,reviewer,created_at) VALUES(?,?,?,?,?)",
                                         (gap_id, gap["question"], intent, reviewer, _now()))
                status = "promoted_classifier"
        else:
            return {"ok": False, "error": "invalid_action"}
        with self.db.lock:
            self.db.conn.execute("UPDATE knowledge_gaps SET status=?, reviewer=?, note=?, decided_at=? WHERE id=?",
                                 (status, reviewer, (note or "")[:300], _now(), gap_id))
            self.db.conn.commit()
        return {"ok": True, "status": status}

    def curated_documents(self) -> list[dict]:
        """Operator-promoted entries, loaded into the knowledge index at startup."""
        with self.db.lock:
            rows = self.db.conn.execute("SELECT * FROM curated_entries ORDER BY id").fetchall()
        return [{"id": f"curated-{r['id']}", "title": f"Curadoria: {r['question'][:80]}", "url": r["source_url"],
                 "section": "operator_curated", "content": f"{r['question']}\n\n{r['answer']}", "language": r["language"],
                 "source_type": "operator_curated", "content_hash": hashlib.sha256(r["answer"].encode()).hexdigest()}
                for r in rows]

    def extra_examples(self) -> list[tuple[str, str]]:
        with self.db.lock:
            rows = self.db.conn.execute("SELECT intent, text FROM classifier_extra_examples ORDER BY id").fetchall()
        return [(r["intent"], r["text"]) for r in rows]
