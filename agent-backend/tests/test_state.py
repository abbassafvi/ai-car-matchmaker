from agent.state import Phase, SessionState


def test_missing_slots_all_empty_on_new_session():
    s = SessionState(session_id="s1")
    assert set(s.interview.missing_slots()) == {
        "use_case", "category", "budget_max", "transaction_type",
    }
    assert not s.interview.is_complete()


def test_save_interview_slots_fills_progressively():
    s = SessionState(session_id="s1")
    s.save_interview_slots(use_case="road trip", transaction_type="rent")
    assert s.interview.use_case == "road trip"
    assert "use_case" not in s.interview.missing_slots()
    assert "category" in s.interview.missing_slots()
    assert s.phase == Phase.INTERVIEWING  # still incomplete


def test_contradiction_overwrites_not_appends():
    """spec.md Edge Cases: budget changes twice -> latest value wins."""
    s = SessionState(session_id="s1")
    s.save_interview_slots(budget_max=25000)
    s.save_interview_slots(budget_max=30000)
    assert s.interview.budget_max == 30000


def test_phase_auto_transitions_when_interview_complete():
    s = SessionState(session_id="s1")
    s.save_interview_slots(
        use_case="commute",
        category="Sedan",
        budget_max=25000,
        transaction_type="buy",
        target_date="2026-09-01",
    )
    assert s.interview.is_complete()
    assert s.phase == Phase.RESEARCHING


def test_available_tools_gated_by_phase():
    s = SessionState(session_id="s1")
    assert s.available_tools() == ["save_interview_state"]
    assert "open_booking_form" not in s.available_tools()

    s.phase = Phase.FORM_FILLING
    assert "open_booking_form" in s.available_tools()
    assert "open_mock_checkout" not in s.available_tools()

    s.phase = Phase.AWAITING_PAYMENT
    assert "open_mock_checkout" in s.available_tools()
    assert "open_booking_form" not in s.available_tools()

    # ⚠️ INVERTED IN M4b. This asserted `"confirm_mock_payment" in
    # s.available_tools()` from M0 until M4b -- a committed, green test
    # encoding exactly the hole `TOOLS_BY_PHASE`'s own comment warns
    # about a few lines above the table. Nothing resolved the name, so it
    # bound to nothing and no test noticed across five audits.
    #
    # It must never be model-callable. Its arguments would be card-like,
    # and a model tool's arguments are written into the message history,
    # checkpointed to SQLite and handed to auto_instrument -- all three
    # of spec.md US4 AS2's prohibitions ("datastore, log file, or OTel
    # span") from a single binding. It is reachable only through the MCP
    # App bridge, which forwards nothing the browser sent.
    assert "confirm_mock_payment" not in s.available_tools()

    s.phase = Phase.CONFIRMED
    assert s.available_tools() == []


def test_session_state_round_trips_through_json():
    s = SessionState(session_id="s1")
    s.save_interview_slots(
        use_case="commute", category="Sedan", budget_max=25000,
        transaction_type="buy", target_date="2026-09-01",
    )
    restored = SessionState.model_validate_json(s.model_dump_json())
    assert restored == s
