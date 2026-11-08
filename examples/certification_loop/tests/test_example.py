"""The example's own pieces: the grader commits only to an answer that names one option, and the sampler never
overlaps the routed set with the measured one."""
from examples.certification_loop.grade import grade, letter_of
from examples.certification_loop.prepare_mmlu_pro import sample


def test_the_grader_reads_a_leading_letter_or_a_stated_answer_and_nothing_else():
    assert [letter_of(t) for t in ("B", "B.", "(C) because", "**D**", "The answer is E.", "G\n\nbecause")] == \
        ["B", "B", "C", "D", "E", "G"]
    assert letter_of("A function f is continuous") is None
    assert letter_of("To find the answer we") is None


def test_an_errored_call_is_not_graded_so_ingest_can_mark_it_unobserved():
    items = {"i": {"answer": "B"}}
    calls = [{"item": "i", "arm": "a", "run": "r", "error": "HTTP 502"},
             {"item": "i", "arm": "b", "run": "r",
              "response": {"choices": [{"message": {"content": "B"}}]}}]
    assert grade(calls, items) == [{"item": "i", "arm": "b", "run": "r", "outcome": "accepted", "reason": "",
                                    "grader": "mmlu-pro-letter"}]


def test_a_skipped_sample_never_overlaps_the_first():
    rows = [{"question_id": i, "category": "law", "question": f"q{i}", "options": ["x", "y"], "answer": "A"}
            for i in range(50)]
    first = {x["item"] for x in sample(rows, ["law"], 20, seed=1)}
    second = {x["item"] for x in sample(rows, ["law"], 20, seed=1, skip=20)}
    assert len(first) == len(second) == 20 and not first & second


def test_candidates_come_from_the_gateway_rates_and_an_unpriced_arm_is_refused():
    import pytest
    from examples.certification_loop.rates_to_candidates import candidates_from_rates
    rates = {"version": None, "as_of": "t", "rates": [
        {"pricing_key": "haiku", "models": ["claude-haiku-4-5"], "input_per_mtok_microusd": 1100000,
         "output_per_mtok_microusd": 5500000, "cache_read_per_mtok_microusd": 110000,
         "cache_write_per_mtok_microusd": 1375000}]}
    c = candidates_from_rates(rates, ["claude-haiku-4-5"], base_url="https://g.example/v1", api_key_env="K")
    assert c["candidates"]["claude-haiku-4-5"]["price_per_mtok"] == {"fresh_in": 1.1, "cached_in": 0.11, "out": 5.5}
    with pytest.raises(SystemExit, match="prices no model"):
        candidates_from_rates(rates, ["gpt-x"], base_url="https://g.example/v1", api_key_env="K")
