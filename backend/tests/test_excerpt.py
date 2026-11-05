from app.agents.critic_agent import MAX_EVIDENCE_CHARS, _compact_evidence
from app.agents.excerpt import focused_excerpt

FILLER = "Texto institucional sem relação com a pergunta. " * 20
FACT = "As cobranças recorrentes podem ser semanais, mensais ou anuais."


def test_short_text_is_returned_whole():
    assert focused_excerpt("curto.", "qualquer coisa", 100) == "curto."


def test_window_moves_to_the_sentence_that_matches_the_focus():
    text = FILLER + FACT + " " + FILLER
    excerpt = focused_excerpt(text, "Com que frequência posso fazer cobranças recorrentes?", 200)
    assert FACT in excerpt
    assert excerpt.startswith("… ") and len(excerpt) <= 202


def test_without_matching_terms_the_start_is_kept():
    text = FILLER + FACT
    assert focused_excerpt(text, "zzz", 120) == text[:120]


def test_critic_sees_the_part_of_the_evidence_the_answer_talks_about():
    evidence = [{"title": "Pagamentos Recorrentes", "content": FILLER + FACT}]
    compact = _compact_evidence(evidence, "Você pode cobrar de forma semanal, mensais ou anuais [1].")
    assert "anuais" in compact[0]["content"]
    assert len(compact[0]["content"]) <= MAX_EVIDENCE_CHARS + 2
    # other string fields keep the plain cut
    assert compact[0]["title"] == "Pagamentos Recorrentes"
