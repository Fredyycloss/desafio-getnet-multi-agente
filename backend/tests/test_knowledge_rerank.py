"""V8 Block 2: the LLM reranker (hybrid_rerank) defaults on for the cloud provider only, and
redistributes the pool's own relevance scores onto the new order so a promoted-but-weak-scored
document cannot flip a correct answer into a wrong abstention."""
import json

from app.agents.knowledge_agent import KnowledgeAgent

DOCS = [
    {"url": "https://site.getnet.com.br/a/", "title": "A", "section": "A", "content": "conteudo a", "language": "pt"},
    {"url": "https://site.getnet.com.br/b/", "title": "B", "section": "B", "content": "conteudo b", "language": "pt"},
    {"url": "https://site.getnet.com.br/c/", "title": "C", "section": "C", "content": "conteudo c", "language": "pt"},
]


class FakeLLM:
    provider = "anthropic"

    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages, tools=None, **kwargs):
        return {"content": self.reply}


def test_default_mode_is_hybrid_rerank_for_anthropic():
    agent = KnowledgeAgent(DOCS, llm=FakeLLM("[0,1,2]"))
    assert agent._default_retrieval_mode() == "hybrid_rerank"


def test_default_mode_is_hybrid_for_non_anthropic_provider():
    class OllamaLike(FakeLLM):
        provider = "ollama"
    agent = KnowledgeAgent(DOCS, llm=OllamaLike("[0,1,2]"))
    assert agent._default_retrieval_mode() == "hybrid"


def test_default_mode_is_hybrid_when_llm_is_none():
    agent = KnowledgeAgent(DOCS, llm=None)
    assert agent._default_retrieval_mode() == "hybrid"


def test_knowledge_rerank_env_override(monkeypatch):
    agent = KnowledgeAgent(DOCS, llm=None)
    monkeypatch.setenv("KNOWLEDGE_RERANK", "true")
    assert agent._default_retrieval_mode() == "hybrid_rerank"
    monkeypatch.setenv("KNOWLEDGE_RERANK", "false")
    agent2 = KnowledgeAgent(DOCS, llm=FakeLLM("[0,1,2]"))
    assert agent2._default_retrieval_mode() == "hybrid"


def test_rerank_llm_reorders_and_redistributes_relevance():
    agent = KnowledgeAgent(DOCS, llm=FakeLLM("[2, 0, 1]"))
    candidates = [{"url": "a", "relevance": 0.9}, {"url": "b", "relevance": 0.6}, {"url": "c", "relevance": 0.3}]
    result = agent._rerank_llm("query", candidates)
    assert [r["url"] for r in result] == ["c", "a", "b"]
    # the pool's own score envelope (0.9, 0.6, 0.3) is kept, just reassigned to the new order,
    # so the promoted "c" reads as confidently relevant as "a" originally did.
    assert [r["relevance"] for r in result] == [0.9, 0.6, 0.3]


def test_rerank_llm_falls_back_to_original_order_on_bad_response():
    agent = KnowledgeAgent(DOCS, llm=FakeLLM("not json"))
    candidates = [{"url": "a", "relevance": 0.9}, {"url": "b", "relevance": 0.6}]
    assert agent._rerank_llm("query", candidates) == candidates


def test_rerank_llm_accepts_a_partial_or_padded_order():
    agent = KnowledgeAgent(DOCS, llm=FakeLLM("[1]"))
    candidates = [{"url": "a", "relevance": 0.9}, {"url": "b", "relevance": 0.6}, {"url": "c", "relevance": 0.3}]
    result = agent._rerank_llm("query", candidates)
    assert [r["url"] for r in result] == ["b", "a", "c"]
