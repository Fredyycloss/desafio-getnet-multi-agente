# Retrieval mechanics on the legacy curated corpus (exact phrases of those summaries).
# The runtime snapshot is covered by test_knowledge_snapshot.py.
from app.agents.knowledge_agent import KnowledgeAgent
from app.knowledge.ingest import allowed_url, canonicalize_url, load_documents


def test_legacy_curated_corpus_still_loads_as_baseline(legacy_documents):
    assert len(legacy_documents) >= 20
    assert any("Get Lite" in d["title"] for d in legacy_documents)


def test_get_lite_retrieval_portuguese(legacy_documents):
    agent = KnowledgeAgent(legacy_documents)
    results = agent.retrieve("A Get Lite tem aluguel mensal ou só taxa de adesão?", language="pt")
    assert results
    assert "get-lite" in results[0]["url"]
    assert "sem aluguel" in results[0]["content"].lower()


def test_get_lite_retrieval_english(legacy_documents):
    agent = KnowledgeAgent(legacy_documents)
    results = agent.retrieve("Does Get Lite have a monthly rental fee?", language="en")
    assert results
    assert "get-lite" in results[0]["url"]
    assert "no monthly rental" in results[0]["content"].lower()


def test_crediario_retrieval_includes_48_installments(legacy_documents):
    result = KnowledgeAgent(legacy_documents).retrieve("How many installments can Crediário have?", language="en")
    assert result
    assert any("48 installments" in item["content"] for item in result[:3])


def test_payment_link_retrieval_covers_whatsapp(legacy_documents):
    result = KnowledgeAgent(legacy_documents).retrieve("Posso vender pelo WhatsApp usando link de pagamento?", language="pt")
    assert result
    assert any("WhatsApp" in item["content"] for item in result[:3])


def test_get_classica_vs_smart_has_comparison_evidence(legacy_documents):
    result = KnowledgeAgent(legacy_documents).retrieve("Compare Get Clássica and Get Smart connectivity and business apps", language="en")
    assert result
    assert any("Get Clássica vs Get Smart" in item["title"] for item in result[:3])


def test_retrieval_filters_language(legacy_documents):
    result = KnowledgeAgent(legacy_documents).retrieve("Get Lite monthly rental", language="en")
    assert result
    assert all(item["language"] == "en" for item in result)


def test_url_allowlist_blocks_external_domains():
    assert allowed_url("https://site.getnet.com.br/get-lite/")
    assert not allowed_url("https://evil.example/get-lite/")
    assert not allowed_url("http://site.getnet.com.br/")


def test_canonical_url_removes_ad_tracking_parameters():
    actual = canonicalize_url("https://site.getnet.com.br/get-lite/?gclid=abc&utm_source=ads&x=1#section")
    assert actual == "https://site.getnet.com.br/get-lite/?x=1"


def test_pix_retrieval_explains_linked_financial_institution(legacy_documents):
    result = KnowledgeAgent(legacy_documents).retrieve(
        "Do I need a bank account to receive my sales via Pix?", language="en"
    )
    assert result
    assert any("select/link the financial institution" in item["content"] for item in result[:3])
    assert any(item["url"] == "https://site.getnet.com.br/pix/" for item in result[:3])


def test_whatsapp_business_native_payments_vs_payment_link(legacy_documents):
    result = KnowledgeAgent(legacy_documents).retrieve(
        "Can I still sell through WhatsApp after WhatsApp Business payments were discontinued?", language="en"
    )
    assert result
    assert any("discontinued on 15 January 2026" in item["content"] for item in result[:3])
    assert any("share the link through WhatsApp" in item["content"] for item in result[:3])


def test_whatsapp_discontinuation_source_is_official(legacy_documents):
    result = KnowledgeAgent(legacy_documents).retrieve(
        "O pagamento nativo do WhatsApp Business foi descontinuado?", language="pt"
    )
    assert result
    assert result[0]["url"].startswith("https://site.getnet.com.br/")
    assert "descontinuados em 15/01/2026" in result[0]["content"]
