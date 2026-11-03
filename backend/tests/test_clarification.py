from app.agents.clarification import clarification_result
from app.agents.clarification import selected_topic_result


def test_topic_clarification_always_offers_human_support_in_portuguese():
    result = clarification_result("pt")

    assert len(result["clarification_options"]) == 4
    assert result["clarification_options"][-1] == {
        "id": "human_support",
        "label": "Falar com atendente humano",
    }
    assert "Qual assunto" in result["answer"]


def test_context_clarification_distinguishes_literal_risk_from_figurative_language():
    result = clarification_result("en", contextual=True)

    labels = [option["label"] for option in result["clarification_options"]]
    assert "There is a real physical hazard happening now" in labels
    assert "It is a figurative expression or frustration" in labels
    assert "Speak with a human attendant" in labels


def test_unsupported_topic_discloses_missing_evidence_and_offers_topics():
    result = clarification_result("pt", unsupported=True)

    assert "Não encontrei informação suficiente" in result["answer"]
    assert len(result["clarification_options"]) == 4
    assert result["handoff"] is False


def test_topic_choice_prompts_for_the_details_needed_to_answer():
    result = selected_topic_result("pt", "sales_payments")

    assert "venda, pagamento, recebimento" in result["answer"]
    assert result["clarification_topic"] == "sales_payments"


def test_terminal_uncertainty_gets_contextual_terminal_topics_and_human_option():
    result = clarification_result("pt", intent="technical_support", message="Minha máquina está estranha")

    labels = [option["label"] for option in result["clarification_options"]]
    assert labels == [
        "Problemas de conexão",
        "Problemas para realizar vendas",
        "Defeito ou funcionamento da maquininha",
        "Dúvidas sobre pagamentos",
        "Quero falar com atendimento humano",
    ]


def test_ambiguous_machine_issue_prefers_terminal_topics_over_generic_risk_menu():
    result = clarification_result(
        "pt", contextual=True, intent="technical_support", message="Minha maquininha está estranha"
    )

    assert [option["id"] for option in result["clarification_options"]] == [
        "terminal_connection", "terminal_sales", "terminal_defect", "sales_payments", "human_support"
    ]


def test_ambiguous_physical_hazard_keeps_safety_confirmation_options():
    result = clarification_result(
        "pt", contextual=True, intent="technical_support", message="Essa máquina parece uma bomba"
    )

    assert [option["id"] for option in result["clarification_options"]] == [
        "literal_hazard", "figurative_expression", "getnet_topic", "human_support"
    ]
