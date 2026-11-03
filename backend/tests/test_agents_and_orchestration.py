import json

from app.agents.critic_agent import CriticAgent
from app.agents.escalation_agent import EscalationAgent
from app.agents.human_handoff_agent import HumanHandoffAgent
from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.risk_assessment_agent import RiskAssessmentAgent
from app.agents.supervisor_agent import SupervisorAgent
from app.agents.support_agent import CustomerSupportAgent
from app.agents.web_research_agent import WebResearchAgent


class ScriptedSupervisorModel:
    """Script only the model transport; the real supervisor and real specialist execute tools."""
    model = "scripted-test-model"

    def __init__(self): self.calls = 0
    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None, temperature=0.0, max_tokens=None, purpose="chat"):
        if json_schema is not None:
            if "contextual classification component" in messages[0]["content"]:
                return {"message": {"content": json.dumps(context_assessment())}}
            if "approved" in json_schema.get("properties", {}):
                return {"message": {"content": json.dumps({"approved": True, "issues": []})}}
        if json_mode:
            return {"message": {"content": json.dumps({"approved": True, "issues": [], "corrected_answer": ""})}}
        self.calls += 1
        if self.calls == 1:
            return {"message": {"tool_calls": [{"function": {"name": "knowledge_specialist", "arguments": {"query": "What is Get Lite monthly rental?"}}}]}}
        return {"message": {"content": "Get Lite has no monthly rental fee; the offer uses a one-time enrollment fee. [1]"}}


def build_supervisor(db, documents, model=None):
    handoff = HumanHandoffAgent(db)
    llm = model
    knowledge = KnowledgeAgent(documents, db=db, llm=None)
    support = CustomerSupportAgent(db, llm=None)
    return SupervisorAgent(llm=llm, db=db, knowledge=knowledge, support=support, web=WebResearchAgent(),
                           risk=RiskAssessmentAgent(), escalation=EscalationAgent(handoff), critic=CriticAgent(model))


def context_assessment(**overrides):
    assessment = {
        "intent": "product_information",
        "context": "The user asks about a Getnet product fee.",
        "emotional_state": None,
        "figurative_language": False,
        "figurative_signals": [],
        "ambiguity_level": "low",
        "risk_level": "safe",
        "confidence": 0.96,
        "needs_clarification": False,
        "clarification_question": None,
        "needs_human": False,
        "recommended_agents": ["knowledge_specialist"],
        "recommended_destination": "knowledge_specialist",
        "recommended_action": "route_to_agent",
        "operational_reason": "The product policy question belongs in grounded knowledge.",
        "blocked_tools": [],
    }
    return {**assessment, **overrides}


def test_supervisor_uses_real_knowledge_specialist_tool(db, documents):
    # A confident single-specialist assessment is dispatched directly (fast path):
    # the real Knowledge specialist runs, the Critic reviews, no planning generation.
    model = ScriptedSupervisorModel()
    supervisor = build_supervisor(db, documents, model)
    result = supervisor.run(message="What is Get Lite monthly rental?", user_id="cliente1988", session_id="s1", language="en", history=[], trace_id="trace-test")
    assert result["orchestration_mode"] == "context_directed_dispatch"
    assert "tool:knowledge_specialist" in result["trace"]
    assert result["tool_calls"] >= 1
    assert result["critic"]["approved"] is True
    assert result["critic"]["mode"] == "llm_critic"
    assert "Get Lite" in result["answer"]
    assert model.calls == 0


class PlanningSupervisorModel:
    """Context recommends several agents (or is unsure), so the planner loop must run."""
    model = "scripted-test-model"

    def __init__(self, assessment):
        self.assessment = assessment
        self.plan_calls = 0
        self.tools_offered: list[str] = []

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None, temperature=0.0, max_tokens=None, purpose="chat"):
        if json_schema is not None:
            if "contextual classification component" in messages[0]["content"]:
                return {"message": {"content": json.dumps(self.assessment)}}
            return {"message": {"content": json.dumps({"approved": True, "issues": []})}}
        self.plan_calls += 1
        self.tools_offered = [tool["function"]["name"] for tool in tools or []]
        if self.plan_calls == 1:
            return {"message": {"tool_calls": [{"function": {"name": "knowledge_specialist", "arguments": {"query": "Get Lite monthly rental"}}}]}}
        return {"message": {"content": "FINAL"}}


def test_supervisor_planning_loop_runs_for_multiple_recommended_agents(db, documents):
    model = PlanningSupervisorModel(context_assessment(
        recommended_agents=["knowledge_specialist", "customer_support_specialist"],
    ))
    supervisor = build_supervisor(db, documents, model)
    result = supervisor.run(message="What is Get Lite monthly rental?", user_id="cliente1988", session_id="plan-1",
                            language="en", history=[], trace_id="plan-multi")

    assert result["orchestration_mode"] == "llm_tool_calling"
    assert "tool:knowledge_specialist" in result["trace"]
    assert "supervisor_final_marker" in result["trace"]
    assert model.plan_calls == 2
    assert "quality_critic_specialist" not in model.tools_offered
    assert result["critic"]["approved"] is True
    # FINAL means the specialist answer is the draft; no extra rewrite generation.
    assert result["answer"] == result["specialist_observations"][0]["answer"]


def test_supervisor_planning_loop_runs_when_context_confidence_is_low(db, documents):
    model = PlanningSupervisorModel(context_assessment(confidence=0.6))
    supervisor = build_supervisor(db, documents, model)
    result = supervisor.run(message="What is Get Lite monthly rental?", user_id="cliente1988", session_id="plan-2",
                            language="en", history=[], trace_id="plan-low-confidence")

    assert result["orchestration_mode"] == "llm_tool_calling"
    assert model.plan_calls == 2


class TimeoutAfterContextModel:
    model = "scripted-test-model"

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None, temperature=0.0, max_tokens=None, purpose="chat"):
        from app.infra.ollama_client import OllamaBudgetExceeded
        if json_schema is not None and "contextual classification component" in messages[0]["content"]:
            return {"message": {"content": json.dumps(context_assessment(
                recommended_agents=["customer_support_specialist"], recommended_destination="customer_support_specialist",
            ))}}
        raise OllamaBudgetExceeded("budget exhausted in test")


def test_llm_budget_exhaustion_returns_honest_deterministic_answer_even_when_llm_required(db, documents):
    handoff = HumanHandoffAgent(db)
    model = TimeoutAfterContextModel()
    supervisor = SupervisorAgent(
        llm=model, db=db, knowledge=KnowledgeAgent(documents, db=db, llm=None),
        support=CustomerSupportAgent(db, llm=model), web=WebResearchAgent(), risk=RiskAssessmentAgent(),
        escalation=EscalationAgent(handoff), critic=CriticAgent(model, required=True), llm_required=True,
    )
    result = supervisor.run(message="When will the money from yesterday's sales be deposited?", user_id="cliente1988",
                            session_id="budget-1", language="en", history=[], trace_id="budget-exhausted")

    assert result["orchestration_mode"] == "deterministic_fallback_llm_budget"
    assert "llm_budget_exhausted" in result["trace"]
    assert result["critic"]["mode"] == "deterministic_lint"
    assert "synthetic" in result["answer"].lower()


class UnclearContextModel:
    model = "scripted-test-model"

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None, temperature=0.0, max_tokens=None, purpose="chat"):
        return {"message": {"content": json.dumps(context_assessment(
            intent="unclear",
            ambiguity_level="high",
            risk_level="ambiguous",
            confidence=0.4,
            needs_clarification=True,
            needs_human=True,
        ))}}


def test_unclear_request_gets_topic_options_including_human(db, documents):
    supervisor = build_supervisor(db, documents, UnclearContextModel())

    result = supervisor.run(
        message="Isso está estranho.",
        user_id="cliente1988",
        session_id="unclear-1",
        language="pt",
        history=[],
        trace_id="unclear-topic-options",
    )

    assert result["orchestration_mode"] == "context_policy_clarification"
    assert result["handoff"] is False
    assert result["clarification_options"][-1]["id"] == "human_support"
    assert "figurada" in result["answer"]
    assert "rationale" not in result["context_assessment"]


def test_selecting_human_option_creates_handoff(db, documents):
    supervisor = build_supervisor(db, documents)
    history = [{
        "role": "assistant",
        "content": "Escolha um assunto.",
        "clarification_options": [
            {"id": "terminal_support", "label": "Maquininha, conexão ou falha"},
            {"id": "sales_payments", "label": "Vendas, pagamentos ou recebimentos"},
            {"id": "products_fees", "label": "Produtos, taxas ou serviços Getnet"},
            {"id": "human_support", "label": "Falar com atendente humano"},
        ],
    }]

    result = supervisor.run(
        message="4",
        user_id="cliente1988",
        session_id="choose-human-1",
        language="pt",
        history=history,
        trace_id="choose-human-option",
    )

    assert result["intent"] == "human_handoff"
    assert result["handoff"] is True
    assert result["real_agent_connected"] is False


def test_selecting_topic_by_number_reenters_context_and_routes_to_specialist(db, documents):
    supervisor = build_supervisor(db, documents)
    history = [{
        "role": "user",
        "content": "Minha maquininha está estranha.",
    }, {
        "role": "assistant",
        "content": "Escolha um assunto.",
        "clarification_options": [
            {"id": "terminal_connection", "label": "Problemas de conexão"},
            {"id": "human_support", "label": "Falar com atendente humano"},
        ],
    }]

    result = supervisor.run(
        message="1",
        user_id="cliente1988",
        session_id="choose-topic-1",
        language="pt",
        history=history,
        trace_id="choose-topic-by-number",
    )

    assert result["orchestration_mode"] == "specialist_intake_clarification"
    assert result["intent"] == "customer_support_clarification"
    assert result["agent"] == "customer_support_agent"
    assert "context_intelligence" in result["trace"]
    assert "customer_support_agent" in result["trace"]
    assert "terminal_connection" in result["answer"].lower() or "rede" in result["answer"].lower()


def test_live_context_topic_selection_does_not_start_a_second_supervisor_llm_loop(db, documents):
    model = ScriptedSupervisorModel()
    supervisor = build_supervisor(db, documents, model)
    history = [{
        "role": "user", "content": "Minha maquininha está estranha.",
    }, {
        "role": "assistant", "content": "Escolha um assunto.",
        "clarification_options": [
            {"id": "terminal_connection", "label": "Problemas de conexão"},
            {"id": "human_support", "label": "Falar com atendente humano"},
        ],
    }]

    result = supervisor.run(
        message="1", user_id="cliente1988", session_id="choose-topic-live-context",
        language="pt", history=history, trace_id="choose-topic-no-second-loop",
    )

    assert result["intent"] == "customer_support_clarification"
    assert result["context_assessment"]["assessment_mode"] == "llm_context_intelligence"
    assert result["context_assessment"]["model"] == "scripted-test-model"
    assert "customer_support_agent" in result["trace"]
    assert model.calls == 0


def test_topic_option_can_be_selected_by_text_and_a_subject_change_is_not_a_selection(db, documents):
    options_history = [{
        "role": "assistant", "content": "Escolha um assunto.",
        "clarification_options": [
            {"id": "terminal_connection", "label": "Problemas de conexão"},
            {"id": "human_support", "label": "Falar com atendente humano"},
        ],
    }]
    assert SupervisorAgent._selected_clarification_option("Problemas de conexão", options_history) == "terminal_connection"
    assert SupervisorAgent._selected_clarification_option("Na verdade, quero saber se Get Lite tem aluguel mensal", options_history) is None

    supervisor = build_supervisor(db, documents)
    history = [{"role": "user", "content": "Minha maquininha está estranha."}, *options_history]
    result = supervisor.run(
        message="Na verdade, quero saber se Get Lite tem aluguel mensal.",
        user_id="cliente1988", session_id="changed-topic", language="pt", history=history,
        trace_id="changed-topic-after-menu",
    )
    assert result["intent"] == "product_information"
    assert result["retrieved_chunks"] > 0


def test_selecting_topic_by_text_routes_using_original_conversation(db, documents):
    supervisor = build_supervisor(db, documents)
    history = [
        {"role": "user", "content": "Minha máquina está estranha."},
        {"role": "assistant", "content": "Escolha um assunto.", "clarification_options": [
            {"id": "terminal_connection", "label": "Problemas de conexão"},
            {"id": "human_support", "label": "Falar com atendente humano"},
        ]},
    ]

    result = supervisor.run(
        message="Problemas de conexão", user_id="cliente1988", session_id="select-by-text",
        language="pt", history=history, trace_id="select-by-text",
    )

    assert result["intent"] == "customer_support_clarification"
    assert result["agent"] == "customer_support_agent"
    assert "maquininha" in result["answer"].lower()
    assert "context_intelligence" in result["trace"]


class UnsupportedKnowledgeModel:
    model = "scripted-test-model"

    def __init__(self):
        self.tool_call_sent = False

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None, temperature=0.0, max_tokens=None, purpose="chat"):
        if json_schema is not None:
            return {"message": {"content": json.dumps(context_assessment())}}
        if not self.tool_call_sent:
            self.tool_call_sent = True
            return {"message": {"tool_calls": [{"function": {
                "name": "knowledge_specialist",
                "arguments": {"query": "Does Getnet sponsor a 2028 moon festival on Mars?"},
            }}]}}
        return {"message": {"content": "Yes, Getnet sponsors that event."}}


def test_unsupported_knowledge_question_never_uses_unobserved_model_claim(db, documents):
    supervisor = build_supervisor(db, documents, UnsupportedKnowledgeModel())

    result = supervisor.run(
        message="Does Getnet sponsor a 2028 moon festival on Mars?",
        user_id="cliente1988",
        session_id="unknown-topic-1",
        language="en",
        history=[],
        trace_id="knowledge-scope-check",
    )

    assert result["orchestration_mode"] == "grounded_knowledge_abstention"
    assert result["intent"] == "knowledge_scope_clarification"
    assert result["clarification_options"][-1]["id"] == "human_support"
    assert "sponsors that event" not in result["answer"]


def test_fallback_supervisor_executes_real_support_tools(db, documents):
    supervisor = build_supervisor(db, documents)
    result = supervisor.run(message="When will the money from yesterday's sales be deposited?", user_id="cliente1988", session_id="s1", language="en", history=[], trace_id="fallback")
    assert result["orchestration_mode"] == "deterministic_fallback"
    assert "synthetic" in result["answer"].lower()
    assert any("lookup_payment_status" in str(item) for item in result.get("specialist_observations", []))


def test_risk_agent_overrides_regular_troubleshooting(db, documents):
    supervisor = build_supervisor(db, documents)
    result = supervisor.run(message="Minha maquininha explodiu e está saindo fumaça", user_id="cliente1988", session_id="risk1", language="pt", history=[], trace_id="risk")
    assert result["intent"] == "physical_safety"
    assert result["handoff"] is True
    assert result["handoff_severity"] == "critical"
    assert "193" in result["answer"]
    assert result["real_agent_connected"] is False
    assert result["trace"][0] == "context_intelligence"


def test_risk_agent_uses_prior_device_context():
    risk = RiskAssessmentAgent()
    history = [{"role": "user", "content": "My payment terminal is overheating."}]
    result = risk.assess("Now it is smoking", history, "en")
    assert result["requires_handoff"] is True
    assert result["severity"] == "critical"


def test_handoff_ticket_persists_and_reuses_protocol(db):
    agent = HumanHandoffAgent(db)
    first = agent.create_ticket(user_id="cliente1988", message="Terminal exploded", reason="physical_safety_critical", language="en", severity="critical", session_id="s1")
    second = agent.create_ticket(user_id="cliente1988", message="There is still smoke", reason="physical_safety_critical", language="en", severity="critical", session_id="s1")
    assert first["protocol"] == second["protocol"]
    assert second["real_agent_connected"] is False
    assert len(second["messages"]) == 2


def test_handoff_ticket_preserves_conversation_context_and_current_request(db):
    ticket = HumanHandoffAgent(db).create_ticket(
        user_id="cliente1988", message="Quero falar com alguém.", reason="human_requested",
        language="pt", session_id="human-context-1",
        history=[
            {"role": "user", "content": "Minha máquina não conecta desde ontem."},
            {"role": "assistant", "content": "Você já tentou outra rede?"},
        ],
    )

    assert [(item["role"], item["content"]) for item in ticket["messages"]] == [
        ("user", "Minha máquina não conecta desde ontem."),
        ("assistant", "Você já tentou outra rede?"),
        ("user", "Quero falar com alguém."),
    ]
    assert ticket["session_id"] == "human-context-1"


def test_explicit_human_request_does_not_call_or_get_blocked_by_critic(db, documents):
    supervisor = build_supervisor(db, documents)

    def reject(*args, **kwargs):
        raise AssertionError("Critic must not run on an explicit human request")

    supervisor.critic.review = reject
    result = supervisor.run(
        message="Não quero falar com robô, transfira para alguém.", user_id="cliente1988",
        session_id="human-priority", language="pt", history=[], trace_id="human-priority",
    )

    assert result["handoff"] is True
    assert result["trace"][0] == "context_intelligence"
    assert result["real_agent_connected"] is False


def test_support_model_tools_do_not_allow_model_to_change_user_id(db):
    support = CustomerSupportAgent(db, llm=None)
    result = support.run("show my terminal status", "cliente1988", "en")
    assert "TERM-1988" in result["answer"]
    assert "demo" in result["answer"].lower()


class NoToolModel:
    model = "scripted-test-model"

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None, temperature=0.0, max_tokens=None, purpose="chat"):
        if json_schema is not None:
            # Below the fast-path threshold, so the planner loop under test runs.
            return {"message": {"content": json.dumps(context_assessment(confidence=0.6))}}
        if json_mode:
            return {"message": {"content": json.dumps({"approved": True, "issues": [], "corrected_answer": ""})}}
        return {"message": {"content": "The answer is definitely that Get Lite has no rental."}}


def test_supervisor_rejects_unobserved_model_answer_and_falls_back_to_real_rag(db, documents):
    supervisor = build_supervisor(db, documents, NoToolModel())
    result = supervisor.run(message="Does Get Lite have a monthly rental?", user_id="cliente1988", session_id="s1", language="en", history=[], trace_id="no-tool")
    assert result["orchestration_mode"] == "deterministic_fallback_no_specialist_observation"
    assert result["retrieved_chunks"] > 0
    assert any("get-lite" in source["url"] for source in result["sources"])


class SupportSelectionModel:
    model = "scripted-test-model"

    def __init__(self, tool_calls, answer="", fail_answer=False):
        self.tool_calls = tool_calls
        self.answer = answer
        self.fail_answer = fail_answer
        self.calls = []

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None, temperature=0.0, max_tokens=None, purpose="chat"):
        self.calls.append({"purpose": purpose, "max_tokens": max_tokens, "payload": messages[-1]["content"],
                           "tools": [t["function"]["name"] for t in tools or []]})
        if purpose.endswith(":tool_selection"):
            return {"message": {"tool_calls": self.tool_calls, "content": ""}}
        if self.fail_answer:
            from app.infra.ollama_client import OllamaTimeout
            raise OllamaTimeout("answer timed out in test")
        return {"message": {"content": self.answer}}


def test_support_model_selects_tools_and_writes_answer_from_observations(db):
    model = SupportSelectionModel(
        [{"function": {"name": "get_terminal_status", "arguments": {}}}],
        answer="Seu terminal demonstrativo TERM-1988 está offline (erro NET-001). Dados sintéticos de demonstração.",
    )
    result = CustomerSupportAgent(db, llm=model).run("Minha maquininha não conecta", "cliente1988", "pt")

    assert [c["purpose"] for c in model.calls] == ["customer_support_agent:tool_selection", "customer_support_agent:answer"]
    assert model.calls[0]["max_tokens"] <= 80
    assert model.calls[0]["tools"] == ["get_customer_profile", "get_terminal_status"]
    sent = json.loads(model.calls[1]["payload"])
    assert sent["observations"][0]["data"]["terminal_id"] == "TERM-1988"
    assert "user_id" not in sent["observations"][0]["data"]
    assert "tool:get_terminal_status" in result["trace"]
    assert "llm_answer_from_tool_observations" in result["trace"]
    assert result["answer"] == model.answer
    assert result["degraded"] is False
    # Common specialist contract.
    assert {"agent", "task", "answer", "evidence", "tool_calls", "sources", "confidence", "missing_info",
            "degraded", "duration_ms"} <= set(result)
    assert result["tool_calls"][0]["tool"] == "get_terminal_status" and result["tool_calls"][0]["ok"] is True


def test_payments_agent_owns_settlement_and_decline_tools(db):
    model = SupportSelectionModel(
        [{"function": {"name": "lookup_payment_status", "arguments": {"period": "yesterday"}}},
         {"function": {"name": "find_declined_transactions", "arguments": {"period": "yesterday"}}},
         {"function": {"name": "get_terminal_status", "arguments": {}}}],
        answer="A venda TX-DEMO-1001 está agendada. Dados sintéticos.",
    )
    from app.agents.payments_agent import PaymentsAgent
    result = PaymentsAgent(db, llm=model).run("Quando cai o dinheiro de ontem e por que recusou?", "cliente1988", "pt")

    assert model.calls[0]["tools"] == ["lookup_payment_status", "find_declined_transactions"]
    assert [c["tool"] for c in result["tool_calls"]] == ["lookup_payment_status", "find_declined_transactions"]
    assert result["agent"] == "payments_agent" and result["degraded"] is False


def test_model_choosing_no_tool_is_a_degraded_keyword_fallback(db):
    from app.agents.payments_agent import PaymentsAgent
    model = SupportSelectionModel([], answer="As vendas demonstrativas estão agendadas. Dados sintéticos.")
    result = PaymentsAgent(db, llm=model).run("When will yesterday's sales be deposited?", "cliente1988", "en")

    assert "model_selected_no_tool" in result["trace"]
    assert result["degraded"] is True and result["degraded_reason"] == "model_selected_no_tool"
    assert any(o.get("tool") == "lookup_payment_status" for o in result["tool_observations"])


def test_template_is_only_a_degraded_fallback_when_answer_generation_fails(db):
    model = SupportSelectionModel([{"function": {"name": "get_terminal_status", "arguments": {}}}], fail_answer=True)
    result = CustomerSupportAgent(db, llm=model).run("My card machine won't connect", "cliente1988", "en")

    assert "template_fallback" in result["trace"]
    assert result["degraded"] is True and result["degraded_reason"] == "llm_timeout"
    assert "TERM-1988" in result["answer"]


def _payments_supervisor(db, documents, model):
    from app.agents.payments_agent import PaymentsAgent
    handoff = HumanHandoffAgent(db)
    return SupervisorAgent(
        llm=model, db=db, knowledge=KnowledgeAgent(documents, db=db, llm=None), support=CustomerSupportAgent(db, llm=model),
        web=WebResearchAgent(), risk=RiskAssessmentAgent(), escalation=EscalationAgent(handoff),
        critic=CriticAgent(model, required=True), payments=PaymentsAgent(db, llm=model),
    )


class ScriptedPaymentsModel(SupportSelectionModel):
    """CI routes to payments; the specialist invents a value; the replan answer is configurable."""

    def __init__(self, answer, replan_answer):
        super().__init__([{"function": {"name": "lookup_payment_status", "arguments": {"period": "yesterday"}}}], answer=answer)
        self.replan_answer = replan_answer

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None, temperature=0.0, max_tokens=None, purpose="chat"):
        if purpose == "context_intelligence":
            return {"message": {"content": json.dumps(context_assessment(
                recommended_agents=["payments_specialist"], recommended_destination="payments_specialist"))}}
        if purpose == "critic":
            self.calls.append({"purpose": purpose})
            return {"message": {"content": json.dumps({"approved": True, "issues": []})}}
        if purpose == "supervisor_replan":
            self.calls.append({"purpose": purpose, "payload": messages[-1]["content"]})
            return {"message": {"content": self.replan_answer}}
        return super().chat(messages, tools, json_mode=json_mode, json_schema=json_schema, think=think,
                            temperature=temperature, max_tokens=max_tokens, purpose=purpose)


def test_critic_rejects_invented_value_then_one_replan_fixes_it(db, documents):
    model = ScriptedPaymentsModel(
        answer="A venda TX-DEMO-1001 de R$ 999,99 cai amanhã. Dados sintéticos.",
        replan_answer="A venda TX-DEMO-1001 tem valor líquido de R$ 242,75. Dados sintéticos de demonstração.",
    )
    result = _payments_supervisor(db, documents, model).run(
        message="Quando cai o dinheiro das vendas de ontem?", user_id="cliente1988",
        session_id="replan-ok", language="pt", history=[], trace_id="replan-ok")

    assert "critic_rejected" in result["trace"] and "supervisor_replan" in result["trace"]
    assert "Critic issues" in [c for c in model.calls if c["purpose"] == "supervisor_replan"][0]["payload"]
    assert result["critic"]["approved"] is True
    assert result["intent"] == "customer_support"  # route family; the agent is payments
    assert result["specialist_observations"][0]["agent"] == "payments_agent"
    assert "999,99" not in result["answer"] and "242,75" in result["answer"]


def test_critic_rejecting_twice_hands_off_to_a_human(db, documents):
    model = ScriptedPaymentsModel(
        answer="A venda TX-DEMO-1001 de R$ 999,99 cai amanhã. Dados sintéticos.",
        replan_answer="A venda TX-DEMO-4242 de R$ 1,00. Dados sintéticos.",
    )
    result = _payments_supervisor(db, documents, model).run(
        message="Quando cai o dinheiro das vendas de ontem?", user_id="cliente1988",
        session_id="replan-fail", language="pt", history=[], trace_id="replan-fail")

    assert result["critic"]["mode"] == "deterministic_grounding_check"
    assert result["critic"]["approved"] is False
    assert result["intent"] == "quality_escalation" and result["handoff"] is True
    assert "999,99" not in result["answer"] and "4242" not in result["answer"]
    assert not any(c["purpose"] == "critic" for c in model.calls)  # grounding failed first both times


def test_response_without_llm_is_marked_degraded(db, documents):
    supervisor = build_supervisor(db, documents)
    result = supervisor.run(message="When will the money from yesterday's sales be deposited?", user_id="cliente1988",
                            session_id="degraded-1", language="en", history=[], trace_id="degraded-1")
    assert result["degraded"] is True and result["degraded_reason"] == "llm_disabled"
    assert result["orchestration_mode"] == "deterministic_fallback"
