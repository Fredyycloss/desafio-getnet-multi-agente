def lookup_payment_status(user_id: str, date_label: str = "ontem") -> dict:
    """Demo tool: never claims to access real account data."""
    return {
        "tool": "lookup_payment_status",
        "status": "authentication_required",
        "simulated": True,
        "user_id_received": bool(user_id),
        "date_label": date_label,
        "message": "Consulta de recebíveis reais exige autenticação no portal ou aplicativo oficial. Nenhuma conta foi consultada por esta demonstração."
    }


def troubleshoot_terminal(issue: str) -> dict:
    lowered = issue.lower()
    if any(word in lowered for word in ("internet", "wifi", "wi-fi", "conectar", "conexão", "conexao", "sinal", "connect", "connection", "network")):
        steps = ["Confira se a maquininha está ligada e carregada.", "Verifique Wi-Fi ou sinal móvel e se o modo avião está desativado.", "Reinicie o equipamento e tente novamente.", "Se continuar sem conexão, contate o suporte oficial."]
    elif any(word in lowered for word in ("recus", "declin", "negad", "transação", "transacao", "declined", "decline", "transaction")):
        steps = ["Confira a mensagem de erro exibida.", "Verifique a conectividade e tente apenas uma nova operação se for seguro.", "O titular deve confirmar com o emissor se o cartão está apto para a compra.", "Se o problema persistir, contate o suporte oficial; não tente contornar controles antifraude."]
    else:
        steps = ["Anote a mensagem ou código de erro sem expor dados de cartão.", "Confira energia e conectividade do equipamento.", "Reinicie a maquininha se não houver uma operação em andamento.", "Se persistir, contate o suporte oficial."]
    return {"tool": "troubleshoot_terminal", "steps": steps, "simulated": False}
