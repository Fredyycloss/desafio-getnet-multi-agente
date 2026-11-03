from app.agents.risk_assessment_agent import RiskAssessmentAgent


def test_swollen_battery_phrase_with_intervening_device_text_is_high_risk():
    result = RiskAssessmentAgent().assess("A bateria do terminal está estufada.", [], "pt")

    assert result["requires_handoff"] is True
    assert result["severity"] == "high"


def test_electric_shock_while_connecting_charger_is_critical():
    result = RiskAssessmentAgent().assess(
        "Levei um choque ao conectar o carregador da máquina.", [], "pt"
    )

    assert result["requires_handoff"] is True
    assert result["severity"] == "critical"


def test_recent_smoke_in_history_remains_critical_on_follow_up():
    history = [{"role": "user", "content": "Minha maquininha começou a soltar fumaça."}]

    result = RiskAssessmentAgent().assess("Agora piorou.", history, "pt")

    assert result["requires_handoff"] is True
    assert result["severity"] == "critical"


def test_busy_store_fire_metaphor_does_not_trigger_device_hazard():
    result = RiskAssessmentAgent().assess(
        "Hoje a loja está pegando fogo de tanto movimento.", [], "pt"
    )

    assert result["requires_handoff"] is False


def test_explicitly_joking_about_a_crash_does_not_become_confirmed_hazard():
    result = RiskAssessmentAgent().assess(
        "Brincadeira, falei que explodiu porque travou na tela inicial.", [], "pt"
    )

    assert result["requires_handoff"] is False


def test_assistant_safety_question_does_not_create_a_historical_hazard():
    history = [{"role": "assistant", "content": "Há fumaça, fogo ou faíscas neste momento?"}]

    result = RiskAssessmentAgent().assess("Não.", history, "pt")

    assert result["requires_handoff"] is False
