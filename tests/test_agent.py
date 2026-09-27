"""Agent loop tests: planning, budget cap, citation validation, fallbacks."""
from app import agent
from app.agent import DeterministicBackend, run_agent, validate_verdicts


def test_deterministic_run_fixture():
    data = run_agent("python", "Bengaluru", backend=DeterministicBackend())
    assert data["brain"] == "deterministic"
    assert len(data["cards"]) == 3
    kinds = [t["kind"] for t in data["trace"]]
    assert "tool" in kinds and "synthesis" in kinds
    assert data["spent"] == 0  # fixture mode costs nothing
    assert data["spent"] <= data["budget"]
    scores = {c["company"] or "?": c["score"] for c in data["cards"]}
    assert scores["HCL Technologies"] > scores["Nimbuspark Technologies"]


def test_budget_cap_enforced():
    class Greedy(DeterministicBackend):
        def next_action(self, goal, trace, state):
            return {"tool": "company_news", "args": {"company": "X"}}

    data = run_agent("python", "Bengaluru", backend=Greedy())
    assert data["spent"] <= data["budget"]
    assert any(t["kind"] == "deny" for t in data["trace"])


def test_unknown_tool_denied():
    class Weird(DeterministicBackend):
        def next_action(self, goal, trace, state):
            return {"tool": "delete_database", "args": {}}

    data = run_agent("python", "Bengaluru", backend=Weird())
    assert any(t["kind"] == "deny" for t in data["trace"])
    # first step is always the hardcoded jobs_search (planner-roundtrip saver),
    # so jobs exist; the unknown tool itself never runs
    assert all(t.get("tool") != "delete_database" or t["kind"] == "deny" for t in data["trace"])


def test_citation_validator_corrects_hallucinated_ids():
    from app import scoring
    from app import serpapi_client as api

    raw = api.load_fixture("jobs_bengaluru_python.json")
    jobs = scoring.dedupe([scoring.normalize_job(j) for j in raw["jobs_results"]])
    fake = [{"job": i, "score": 5, "reasons": ["looks fine [E99]"]} for i in range(len(jobs))]
    job_ev = {i: {"news": 0, "presence": False, "ids": ["E1"], "nums": {1}} for i in range(len(jobs))}
    fixed, corrections = validate_verdicts(fake, jobs, job_ev)
    assert corrections == len(jobs) and len(fixed) == len(jobs)
    assert all("[E99]" not in " ".join(v["reasons"]) for v in fixed)


def test_broken_backend_still_returns_cards():
    class Broken(DeterministicBackend):
        def next_action(self, goal, trace, state):
            raise RuntimeError("brain exploded")

        def synthesize(self, jobs, evidence, job_ev):
            raise RuntimeError("mouth exploded")

    data = run_agent("python", "Bengaluru", backend=Broken())
    # planner falls back to deterministic steps; synthesis falls back too
    assert len(data["cards"]) == 3
    assert data["errors"], "failures must be visible, never hidden"
