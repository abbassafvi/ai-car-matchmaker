"""US5 (Session Resume) foundation: state written under one checkpointer
connection must be readable from a *separate* connection opened later
against the same SQLite file — this is what "surviving a backend restart"
actually means at the persistence layer, so the test opens two independent
connections rather than reusing one (which would prove nothing about
restart survival).
"""
import tempfile
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from agent.graph import compiled_graph, new_session_state


def test_state_survives_a_simulated_restart(tmp_path: Path):
    db_path = str(tmp_path / "sessions.sqlite")
    config = {"configurable": {"thread_id": "sess-1"}}

    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        app = compiled_graph(checkpointer)
        state = new_session_state("sess-1")
        state["phase"] = "RESEARCHING"
        app.invoke({"session": state}, config=config)

    # New connection, new compiled graph -> simulates a fresh process.
    with SqliteSaver.from_conn_string(db_path) as checkpointer_after_restart:
        app_after_restart = compiled_graph(checkpointer_after_restart)
        snapshot = app_after_restart.get_state(config)
        assert snapshot.values["session"]["phase"] == "RESEARCHING"
        assert snapshot.values["session"]["session_id"] == "sess-1"


def test_two_sessions_do_not_leak_into_each_other(tmp_path: Path):
    db_path = str(tmp_path / "sessions.sqlite")

    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        app = compiled_graph(checkpointer)

        state_a = new_session_state("sess-a")
        state_a["phase"] = "AWAITING_PAYMENT"
        app.invoke({"session": state_a}, config={"configurable": {"thread_id": "sess-a"}})

        state_b = new_session_state("sess-b")
        app.invoke({"session": state_b}, config={"configurable": {"thread_id": "sess-b"}})

        snap_a = app.get_state({"configurable": {"thread_id": "sess-a"}})
        snap_b = app.get_state({"configurable": {"thread_id": "sess-b"}})

        assert snap_a.values["session"]["phase"] == "AWAITING_PAYMENT"
        assert snap_b.values["session"]["phase"] == "INTERVIEWING"
