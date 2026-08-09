

# --- a budget belongs to the basis it was stated against (AE-20) ---------
#
# "I want to lease a Sedan under $30,000" became transaction_type=rent with
# budget_max=30000, which the marketplace compares against
# rent_price_per_day -- so an explicit constraint excluded nothing and the
# user was shown the whole catalogue as though it had been narrowed.

def test_a_purchase_budget_is_dropped_when_the_user_switches_to_renting():
    from agent.state import SessionState

    session = SessionState(session_id="t")
    session.save_interview_slots(
        use_case="commute", category="Sedan", budget_max=30000,
        transaction_type="buy", target_date="2026-10-01",
    )
    assert session.interview.budget_basis == "buy"

    session.save_interview_slots(transaction_type="rent")
    assert session.interview.budget_max is None, (
        "$30,000 carried into a rental search is compared against a DAILY "
        "rate, which excludes nothing"
    )
    assert "budget_max" in session.interview.missing_slots(), (
        "a dropped budget must be re-asked, not silently absent"
    )


def test_a_daily_budget_is_dropped_when_the_user_switches_to_buying():
    from agent.state import SessionState

    session = SessionState(session_id="t")
    session.save_interview_slots(
        use_case="trip", category="SUV", budget_max=120,
        transaction_type="rent", target_date="2026-10-01",
    )
    assert session.interview.budget_basis == "rent"
    session.save_interview_slots(transaction_type="buy")
    assert session.interview.budget_max is None, (
        "$120 carried into a purchase search would match almost nothing"
    )


def test_both_and_buy_share_a_basis_so_a_budget_survives_between_them():
    """"both" is filtered on the sale price, so a purchase budget still applies."""
    from agent.state import SessionState

    session = SessionState(session_id="t")
    session.save_interview_slots(
        use_case="commute", category="Sedan", budget_max=25000,
        transaction_type="buy", target_date="2026-10-01",
    )
    session.save_interview_slots(transaction_type="both")
    assert session.interview.budget_max == 25000
    assert session.interview.budget_basis == "buy"


def test_a_budget_restated_with_the_new_intent_is_kept():
    from agent.state import SessionState

    session = SessionState(session_id="t")
    session.save_interview_slots(
        use_case="commute", category="Sedan", budget_max=30000,
        transaction_type="buy", target_date="2026-10-01",
    )
    session.save_interview_slots(transaction_type="rent", budget_max=120)
    assert session.interview.budget_max == 120
    assert session.interview.budget_basis == "rent"
    assert session.interview.is_complete()


def test_lease_is_named_as_unavailable_rather_than_silently_mapped():
    from agent.tools import _coerce_transaction_type

    value, note = _coerce_transaction_type("lease")
    assert value == "rent"
    assert note and "does not offer lease" in note
    assert "per-day rate" in note, "the units change must be carried to the model"

    assert _coerce_transaction_type("rent") == ("rent", None)


def test_lease_does_not_turn_a_purchase_budget_into_a_daily_rate():
    """The headline AE-20 case, and it arrives as ONE tool call.

    "I want to lease a Sedan under $30,000" maps transaction_type to `rent`
    and passes budget_max=30000 in the same call. Recording that as a
    per-day rate leaves a filter that excludes nothing -- the user states a
    constraint and is shown the whole catalogue as though it applied.

    The budget's basis follows the word the user used, not the value we
    coerced it to, so it is dropped and re-asked in the units that now hold.
    """
    from agent.state import SessionState
    from agent.tools import save_interview_state

    state = {"session": SessionState(session_id="t").model_dump(mode="json")}
    result = save_interview_state.invoke({
        "args": {"use_case": "commuting", "category": "Sedan", "budget_max": 30000,
                 "transaction_type": "lease", "target_date": "2026-10-01",
                 "state": state},
        "name": "save_interview_state", "type": "tool_call", "id": "t1",
    })
    session = SessionState.model_validate(result.update["session"])

    assert session.interview.transaction_type.value == "rent"
    assert session.interview.budget_max is None, (
        "$30,000 kept as a daily rate is a filter that excludes nothing"
    )
    assert session.phase.value == "INTERVIEWING", (
        "an incomplete interview must not start researching"
    )
    told = result.update["messages"][0].content
    assert "does not offer lease" in told
    assert "per day" in told


def test_financing_keeps_the_budget_because_the_basis_is_unchanged():
    """finance -> buy is a mapping *within* one basis, so the number survives."""
    from agent.state import SessionState
    from agent.tools import save_interview_state

    state = {"session": SessionState(session_id="t").model_dump(mode="json")}
    result = save_interview_state.invoke({
        "args": {"use_case": "commuting", "category": "Sedan", "budget_max": 30000,
                 "transaction_type": "financing", "target_date": "2026-10-01",
                 "state": state},
        "name": "save_interview_state", "type": "tool_call", "id": "t1",
    })
    session = SessionState.model_validate(result.update["session"])
    assert session.interview.transaction_type.value == "buy"
    assert session.interview.budget_max == 30000
    assert session.interview.budget_basis == "buy"


def test_a_rental_budget_stated_as_rental_is_kept():
    from agent.state import SessionState
    from agent.tools import save_interview_state

    state = {"session": SessionState(session_id="t").model_dump(mode="json")}
    result = save_interview_state.invoke({
        "args": {"use_case": "trip", "category": "SUV", "budget_max": 120,
                 "transaction_type": "rent", "target_date": "2026-10-01",
                 "state": state},
        "name": "save_interview_state", "type": "tool_call", "id": "t1",
    })
    session = SessionState.model_validate(result.update["session"])
    assert session.interview.budget_max == 120
    assert session.interview.budget_basis == "rent"
    assert session.interview.is_complete()
