"""The versioned official-site snapshot: offline load, metadata, manifest, precomputed embeddings, retrieval."""
import json

import pytest

from app.agents.knowledge_agent import KnowledgeAgent
from app.knowledge.ingest import latest_snapshot, load_documents, load_snapshot_vectors

pytestmark = pytest.mark.skipif(latest_snapshot() is None, reason="no knowledge snapshot committed")


@pytest.fixture(scope="module")
def snapshot_docs():
    return load_documents()


def test_snapshot_loads_offline_with_rich_metadata(snapshot_docs):
    assert len(snapshot_docs) >= 300
    assert {d["source_type"] for d in snapshot_docs} == {"official_web_snapshot"}
    required = {"url", "title", "section", "breadcrumb", "language", "fetched_at", "content_hash", "chunk_id", "corpus_version"}
    assert all(required <= set(d) for d in snapshot_docs)
    assert {d["language"] for d in snapshot_docs} == {"pt", "en"}
    assert any(d["url"].startswith("https://www.getnet.net/en") for d in snapshot_docs)  # URL named in the challenge
    assert len({d["url"] for d in snapshot_docs}) >= 150


def test_manifest_matches_the_snapshot(snapshot_docs):
    manifest = json.loads((latest_snapshot() / "manifest.json").read_text())
    assert manifest["chunks"] == len(snapshot_docs)
    assert manifest["downloaded_pages"] >= 150 and manifest["pages_by_section"]
    assert "failed" in manifest and "skipped" in manifest and manifest["timings"]["crawl_s"] > 0


def test_every_chunk_has_a_precomputed_embedding(snapshot_docs):
    model, prefix, vectors = load_snapshot_vectors()
    assert model == "nomic-embed-text" and prefix == "search_document: "
    assert all(d["content_hash"] in vectors for d in snapshot_docs)
    assert len(next(iter(vectors.values()))) == 768


@pytest.mark.parametrize("question,language,fragment", [
    ("A Get Lite tem aluguel mensal?", "pt", "get-lite"),
    ("Em quantas vezes posso parcelar no crediário?", "pt", "crediario"),
    ("Posso vender pelo WhatsApp com link de pagamento?", "pt", "link-de-pagamento"),
    ("Como habilitar o recebimento por Pix no aplicativo?", "pt", "pix"),
])
def test_bm25_finds_the_official_page_without_network(snapshot_docs, question, language, fragment):
    hits = KnowledgeAgent(snapshot_docs).retrieve(question, k=5, language=language, mode="bm25")
    assert any(fragment in h["url"] for h in hits), [h["url"] for h in hits]
