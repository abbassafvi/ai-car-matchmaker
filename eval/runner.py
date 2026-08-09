"""
T046 — Eval runner: scores personas against SC-001/SC-002.

SC-001: Structured interview slot extraction
SC-002: Grounded, relevant recommendations

Usage:
    python -m eval.runner                    # run all personas
    python -m eval.runner --persona p01      # run one persona
    python -m eval.runner --export           # export results to JSON
"""
import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

# The `agent` package lives in agent-backend/, not at the repo root, so the
# old single insert made every persona die with "No module named 'agent'" --
# an error the runner then swallowed into result["error"] and reported as a
# tidy scorecard of 0.00. Both paths are needed: the root for `eval.personas`
# and agent-backend/ for `agent.*`.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agent-backend"))

from eval.personas import PERSONAS, Persona, get_persona_by_id


def score_sc001(slots: dict, expected: dict) -> tuple[float, list[str]]:
    """Score SC-001: interview slot extraction.

    Returns (score 0-1, list of issues).
    """
    if not expected:
        return 1.0, []  # no expectations = pass

    issues = []
    correct = 0

    for key, expected_val in expected.items():
        actual_val = slots.get(key, "")
        if not actual_val:
            issues.append(f"missing slot: {key}")
        elif str(expected_val).lower() in str(actual_val).lower():
            correct += 1
        else:
            issues.append(f"slot {key}: expected '{expected_val}', got '{actual_val}'")

    score = correct / len(expected) if expected else 1.0
    return score, issues


def score_sc002(results: list[dict], persona: Persona) -> tuple[float, list[str]]:
    """Score SC-002: grounded recommendations.

    Returns (score 0-1, list of issues).
    """
    issues = []

    if len(results) < persona.expected_min_results:
        issues.append(
            f"expected at least {persona.expected_min_results} results, "
            f"got {len(results)}"
        )
        return 0.0, issues

    # Check each result has required grounded fields
    grounded_fields = ["id", "brand", "model", "year", "price"]
    for i, result in enumerate(results):
        missing = [f for f in grounded_fields if f not in result]
        if missing:
            issues.append(f"result {i} missing fields: {missing}")

    # Check budget constraint (if specified)
    budget = persona.expected_slots.get("budget_max")
    if budget:
        try:
            budget_val = float(budget)
            over_budget = [r for r in results if r.get("price", 0) > budget_val]
            if over_budget:
                issues.append(
                    f"{len(over_budget)} results exceed budget ${budget_val}"
                )
        except ValueError:
            pass

    score = 1.0 if not issues else max(0, 1.0 - len(issues) * 0.2)
    return score, issues


def run_persona_eval(persona: Persona, verbose: bool = False) -> dict:
    """Run evaluation for a single persona.

    Returns a dict with scores and details.
    """
    result = {
        "persona_id": persona.id,
        "persona_name": persona.name,
        "sc001_score": 0.0,
        "sc001_issues": [],
        "sc002_score": 0.0,
        "sc002_issues": [],
        "total_score": 0.0,
        "duration_seconds": 0,
        "error": None,
    }

    start = time.time()

    try:
        # Import here to avoid circular imports and allow graceful degradation
        from agent.graph import compiled_graph, new_session_state
        from langgraph.checkpoint.memory import MemorySaver

        # ⚠️ `compiled_graph` is the M0 placeholder: one node, `_touch`, which
        # returns state unchanged. No model, no tools, and a `GraphState` with
        # no `messages` key -- so the persona's turns below are discarded and
        # `interview_slots` / `candidate_listings` are empty whatever the
        # agent would really have done. Every persona therefore scored 0.00,
        # and the summary printed that as if it were a measurement.
        #
        # Refusing is the honest state until this is pointed at the real
        # per-phase agents (`PhaseAgentRegistry` + `run_research`, the path
        # `api/main.py` takes). A harness that cannot measure must not
        # produce a number that looks like a measurement.
        raise NotImplementedError(
            "eval/runner.py still drives agent.graph.compiled_graph -- the M0 "
            "placeholder graph, which has no model and no tools. Every score "
            "it produces is 0.00 by construction. Point it at "
            "PhaseAgentRegistry/run_research before trusting any output."
        )

        checkpointer = MemorySaver()
        app = compiled_graph(checkpointer)
        config = {"configurable": {"thread_id": f"eval-{persona.id}"}}

        state = new_session_state(f"eval-{persona.id}")

        # Send each message through the agent
        for msg in persona.messages:
            app.invoke(
                {"session": state, "messages": [{"role": "user", "content": msg}]},
                config=config,
            )

        # Get final state
        snapshot = app.get_state(config)
        final_state = snapshot.values.get("session", {})

        # Extract slots for SC-001
        slots = final_state.get("interview_slots", {})
        sc001_score, sc001_issues = score_sc001(slots, persona.expected_slots)

        # Extract results for SC-002
        results = final_state.get("candidate_listings", [])
        sc002_score, sc002_issues = score_sc002(results, persona)

        result["sc001_score"] = sc001_score
        result["sc001_issues"] = sc001_issues
        result["sc002_score"] = sc002_score
        result["sc002_issues"] = sc002_issues
        result["total_score"] = (sc001_score + sc002_score) / 2

    except Exception as e:
        result["error"] = str(e)
        if verbose:
            import traceback
            traceback.print_exc()

    result["duration_seconds"] = round(time.time() - start, 2)
    return result


def run_all_personas(verbose: bool = False) -> list[dict]:
    """Run evaluation for all personas."""
    results = []
    for persona in PERSONAS:
        print(f"  Evaluating {persona.id}: {persona.name}...", end=" ", flush=True)
        result = run_persona_eval(persona, verbose)
        results.append(result)
        status = "✓" if result["error"] is None else "✗"
        print(f"{status} ({result['duration_seconds']}s, score={result['total_score']:.2f})")
    return results


def print_summary(results: list[dict]) -> None:
    """Print a summary of eval results."""
    print("\n" + "=" * 60)
    print("EVAL SUMMARY")
    print("=" * 60)

    total = len(results)
    passed = sum(1 for r in results if r["total_score"] >= 0.8 and r["error"] is None)
    errors = sum(1 for r in results if r["error"] is not None)

    sc001_avg = sum(r["sc001_score"] for r in results) / total if total else 0
    sc002_avg = sum(r["sc002_score"] for r in results) / total if total else 0
    total_avg = sum(r["total_score"] for r in results) / total if total else 0

    print(f"\nPersonas: {total} total, {passed} passed (score >= 0.8), {errors} errors")
    print(f"\nSC-001 (slot extraction) avg: {sc001_avg:.2f}")
    print(f"SC-002 (recommendations) avg: {sc002_avg:.2f}")
    print(f"Overall avg: {total_avg:.2f}")

    if errors:
        print(f"\nFailed personas:")
        for r in results:
            if r["error"]:
                print(f"  {r['persona_id']}: {r['error']}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Eval runner for AI Car Matchmaker")
    parser.add_argument("--persona", help="Run a specific persona ID")
    parser.add_argument("--export", action="store_true", help="Export results to JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    if args.persona:
        persona = get_persona_by_id(args.persona)
        if not persona:
            print(f"Unknown persona: {args.persona}")
            print(f"Available: {', '.join(p.id for p in PERSONAS)}")
            sys.exit(1)
        results = [run_persona_eval(persona, args.verbose)]
    else:
        print("Running eval for all personas...")
        results = run_all_personas(args.verbose)

    print_summary(results)

    # A scoring harness that cannot run must not look like a run that scored
    # zero. Anything that errored is a broken harness, not a failing agent,
    # and the exit code has to say which.
    broken = [r for r in results if r["error"]]
    if broken:
        print(
            f"\n{len(broken)} persona(s) did not execute -- these are harness "
            f"errors, not agent scores. The averages above are meaningless.",
            file=sys.stderr,
        )

    if args.export:
        output_path = "eval/results.json"
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults exported to {output_path}")

    if broken:
        sys.exit(1)


if __name__ == "__main__":
    main()
