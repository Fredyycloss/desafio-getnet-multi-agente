"""V8 anti-overfitting rule: dev/test splits are disjoint, and the new held-out v2 sets
(quality_test_v2, retrieval_test_v2) were never used to tune a prompt, rule or example."""
import json
import re
import unicodedata
from pathlib import Path

EVAL_DIR = Path(__file__).parents[1] / "app" / "evaluation"
AGENTS_DIR = Path(__file__).parents[1] / "app" / "agents"

PROMPT_MODULES = ["knowledge_agent.py", "specialist.py", "critic_agent.py", "context_intelligence.py"]


def _jsonl(name: str) -> list[dict]:
    return [json.loads(line) for line in (EVAL_DIR / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def _questions(name: str) -> list[dict]:
    return json.loads((EVAL_DIR / name).read_text(encoding="utf-8"))["questions"]


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _fourgrams(text: str) -> set[str]:
    words = _norm(text).split()
    return {" ".join(words[i:i + 4]) for i in range(len(words) - 3)}


def test_quality_dev_test_split_is_disjoint_and_covers_the_original_set():
    original = _jsonl("answer_quality.jsonl")
    dev, test = _jsonl("answer_quality_dev.jsonl"), _jsonl("answer_quality_test.jsonl")
    assert len(dev) + len(test) == len(original) == 63
    assert {d["id"] for d in dev} & {t["id"] for t in test} == set()
    assert {d["id"] for d in dev} | {t["id"] for t in test} == {o["id"] for o in original}


def test_retrieval_dev_test_split_is_disjoint_and_covers_the_original_set():
    original = _questions("retrieval_questions.json")
    dev, test = _questions("retrieval_questions_dev.json"), _questions("retrieval_questions_test.json")
    assert len(dev) + len(test) == len(original) == 70
    assert {d["id"] for d in dev} & {t["id"] for t in test} == set()
    assert {d["id"] for d in dev} | {t["id"] for t in test} == {o["id"] for o in original}


def test_quality_test_v2_is_new_and_large_enough():
    v2 = _jsonl("quality_test_v2.jsonl")
    original_questions = {_norm(o["question"]) for o in _jsonl("answer_quality.jsonl")}
    assert len(v2) >= 60
    assert len({v["id"] for v in v2}) == len(v2)
    assert not original_questions & {_norm(v["question"]) for v in v2}
    assert all(v.get("source_url") for v in v2)


def test_retrieval_test_v2_is_new_and_large_enough():
    v2 = _questions("retrieval_test_v2.json")
    original_questions = {_norm(o["question"]) for o in _questions("retrieval_questions.json")}
    assert len(v2) >= 60
    assert len({v["id"] for v in v2}) == len(v2)
    assert not original_questions & {_norm(v["question"]) for v in v2}
    assert all(v.get("source_url") for v in v2)


def test_v2_sets_share_no_dataset_phrase_with_specialist_prompts():
    """The v2 sets were written from snapshot pages after reading them, but the prompts
    that write and check answers must never have been tuned against their wording."""
    leaked = []
    v2_questions = _jsonl("quality_test_v2.jsonl") + _questions("retrieval_test_v2.json")
    for module in PROMPT_MODULES:
        source = _norm((AGENTS_DIR / module).read_text(encoding="utf-8"))
        for item in v2_questions:
            for gram in _fourgrams(item["question"]):
                if gram and gram in source:
                    leaked.append((module, item["id"], gram))
    assert not leaked, leaked
