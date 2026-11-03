from app.agents.grounding import find_unsupported

OBS = [{
    "tool": "lookup_payment_status", "ok": True, "transaction_date": "2026-11-01", "net_total_brl": 361.55,
    "transactions": [{"transaction_id": "TX-DEMO-1001", "net_amount": 242.75, "settlement_date": "2026-11-04",
                      "settlement_status": "scheduled", "transaction_status": "approved"}],
}]


def test_values_copied_from_observations_are_supported_in_any_common_format():
    answer = ("A venda TX-DEMO-1001 de R$ 242,75 (aprovada) está agendada para 04/11/2026; "
              "o total líquido é R$ 361,55. Dados sintéticos.")
    assert find_unsupported(answer, OBS) == []


def test_invented_identifier_amount_date_and_status_are_reported():
    answer = "A venda TX-DEMO-9999 de R$ 500,00 será paga em 2026-11-10 e foi recusada."
    assert find_unsupported(answer, OBS) == ["id:TX-DEMO-9999", "date:2026-11-10", "value:500,00", "status:declined"]


def test_rounded_provider_values_are_accepted_but_other_numbers_are_not():
    fx = [{"tool": "frankfurter_exchange_rates", "date": "2026-10-30", "base": "USD", "quote": "BRL", "rate": 5.4321}]
    assert find_unsupported("1 USD = 5.43 BRL em 2026-10-30.", fx) == []
    assert find_unsupported("1 USD = 5.80 BRL.", fx) == ["value:5.80"]


def test_date_inside_an_iso_timestamp_counts_as_observed():
    observations = [{"data": {"terminal_id": "TERM-1988", "last_seen_at": "2026-11-03T00:36:38+00:00"}}]
    assert find_unsupported("O terminal TERM-1988 foi visto pela última vez em 2026-11-03.", observations) == []
    assert find_unsupported("O terminal TERM-1988 foi visto em 2026-11-04.", observations) != []
