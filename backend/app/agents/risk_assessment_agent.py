"""Safety triage: high-severity physical incidents bypass normal troubleshooting."""
from __future__ import annotations

import re
from ..language import normalize


class RiskAssessmentAgent:
    name = "risk_assessment_agent"
    CRITICAL = (
        r"\b(explod(?:e|ed|ing|es|sion)|blown up|caught fire|on fire|flames?|smok(?:e|ing)|sparks?|electric(?:al)? shock)\b",
        r"\b(explod(?:iu|ir|indo|iu)|explos[aã]o|peg(?:ou|ando) fogo|em chamas|inc[eê]ndio|fumac[aã]|soltando fumac[aã]|saindo fumac[aã]|fa[ií]scas?|choque el[eé]trico)\b",
        r"\bchoque\b.{0,35}\b(carregador|maquina|terminal|tomada|eletric[oa])\b",
    )
    HIGH = (
        r"\b(burning smell|smell of burning|overheating|overheated|too hot to touch|swollen battery|battery swelling|battery.{0,35}swollen)\b",
        r"\b(cheiro de queimado|superaquec\w*|quente demais|bateria.{0,35}(estufada|inchada))\b",
    )
    DEVICE = r"\b(maquininha|maquina|terminal|equipamento|aparelho|bateria|carregador|fonte|machine|device|payment reader|card reader|charger|battery|pos|get lite|get smart)\b"
    # Explicit retraction or self-declared figure of speech. It removes the
    # deterministic hazard only when no concrete hazard term is present, and
    # the Context Intelligence still keeps such turns at "clarify" at least.
    EXPLICIT_FIGURATIVE = (
        r"\b(brincadeira|brincando|zoeira|zoando|exagerei|exagero|de alegria|de felicidade)\b",
        r"\b(express[aã]o figurada|modo de dizer|maneira de dizer|for[cç]a de express[aã]o|met[aá]fora|figurad[oa])\b",
        r"\b(just kidding|joking|i exaggerated|figurative expression|figuratively|figure of speech|metaphor)\b",
    )
    # Idiomatic intensifiers about business activity ("on fire with so many
    # customers"). The span is removed before hazard matching.
    ACTIVITY_IDIOM = (
        r"\bpegando fogo de tanto (movimento|venda|vendas|cliente|clientes|gente|pedido|pedidos)\b",
        r"\bon fire with (customers|sales|orders|people)\b",
    )
    CONCRETE_HAZARD = (
        r"\b(smoke|smoking|flames?|on fire|caught fire|sparks?|electric(?:al)? shock|overheating|swollen battery)\b",
        r"\b(fumaca|fumacando|chamas?|pegando fogo|pegou fogo|incendio|faiscas?|choque|superaquec|cheiro de queimado|bateria.{0,35}(estufada|inchada|inchou))\b",
    )
    # Broad physical-danger vocabulary (not a hazard by itself). Used by the
    # Context Intelligence as a conservative floor when the model says "safe".
    DANGER_VOCABULARY = (
        r"\b(explo\w*|bomba\w*|fogo|chamas?|fumac\w*|faisca\w*|choque|queim\w*|derret\w*|estour\w*|incendi\w*|"
        r"machuc\w*|ferid\w*|ferir|perig\w*|medo|receio|estalo|inchad\w*|estufad\w*)\b",
        r"\b(explo\w*|bomb\w*|fire|flames?|smok\w*|sparks?|shock\w*|burn\w*|melt\w*|hurt|injur\w*|danger\w*|afraid|scared|swollen)\b",
    )

    @classmethod
    def strip_idioms(cls, text: str) -> str:
        for pattern in cls.ACTIVITY_IDIOM:
            text = re.sub(pattern, " ", text, flags=re.I)
        return text

    @classmethod
    def danger_vocabulary(cls, message: str, history: list[dict] | None = None) -> bool:
        prior = " ".join(normalize(str(m.get("content", ""))) for m in (history or [])[-8:] if m.get("role") == "user")
        text = cls.strip_idioms(prior + " " + normalize(message))
        return any(re.search(p, text, re.I) for p in cls.DANGER_VOCABULARY)

    @classmethod
    def explicit_figurative(cls, message: str) -> bool:
        return any(re.search(p, normalize(message), re.I) for p in cls.EXPLICIT_FIGURATIVE)

    def assess(self, message: str, history: list[dict] | None = None, language: str = "pt") -> dict:
        current = self.strip_idioms(normalize(message))
        prior = self.strip_idioms(" ".join(
            normalize(str(m.get("content", ""))) for m in (history or [])[-8:] if m.get("role") == "user"))
        context = prior + " " + current
        critical = any(re.search(p, context, re.I) for p in self.CRITICAL)
        high = any(re.search(p, context, re.I) for p in self.HIGH)
        explicit_figurative = any(re.search(p, current, re.I) for p in self.EXPLICIT_FIGURATIVE)
        concrete_hazard = any(re.search(p, context, re.I) for p in self.CONCRETE_HAZARD)
        if explicit_figurative and not concrete_hazard:
            critical = False
            high = False
        has_device = bool(re.search(self.DEVICE, context, re.I))
        # Explicit catastrophic events are critical even if the user omits the word terminal.
        if critical and (has_device or any(re.search(p, current, re.I) for p in self.CRITICAL)):
            severity, reason = "critical", "physical_safety_critical"
        elif high and has_device:
            severity, reason = "high", "physical_safety_high"
        else:
            return {"requires_handoff": False, "severity": "normal", "trace": ["risk_assessment_agent", "no_immediate_hazard"]}
        if language == "en":
            message_template = ("Stop using the device immediately. Do not touch, charge, restart, move, or repair a hot, smoking, burning, swollen, or damaged payment terminal. "
              "Move away, keep other people clear, and do not inhale smoke. Do not attempt to extinguish an electrical or battery fire yourself. "
              "If there is fire, smoke, explosion, or immediate danger in Brazil, call the Fire Department at 193; elsewhere call your local emergency number. "
              "If anyone is injured, seek emergency medical help.\n\nIncident protocol: {protocol}. This is a simulated queue; no real human is monitoring this chat. Do not wait here for emergency assistance.")
        else:
            message_template = ("Pare de usar o equipamento imediatamente. Não toque, carregue, reinicie, mova nem tente consertar uma maquininha quente, soltando fumaça, em chamas, com bateria estufada ou danificada. "
              "Afaste-se, mantenha outras pessoas longe e evite inalar a fumaça. Não tente apagar sozinho um incêndio elétrico ou de bateria. "
              "Se houver fogo, fumaça, explosão ou perigo imediato no Brasil, ligue para os Bombeiros no 193. Se alguém se feriu, procure atendimento médico de emergência.\n\n"
              "Protocolo do incidente: {protocol}. Esta é uma fila simulada; nenhum atendente real monitora este chat. Não espere por ajuda de emergência aqui.")
        return {"requires_handoff": True, "severity": severity, "reason": reason, "message_template": message_template,
                "trace": ["risk_assessment_agent", "hazard_context_analysis", "safety_override"]}
