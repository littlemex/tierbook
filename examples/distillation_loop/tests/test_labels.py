from examples.distillation_loop.labels import first_word, grade


def test_the_first_word_is_the_answer_whatever_surrounds_it():
    assert [first_word(t) for t in ("Bullish", " neutral.", "**bearish**", "", "123")] == \
        ["bullish", "neutral", "bearish", None, None]


def test_a_label_is_accepted_only_when_it_is_the_gold_one_and_errors_are_left_ungraded():
    items = {"i": {"label": "bullish"}}
    calls = [{"item": "i", "arm": "a", "response": {"choices": [{"message": {"content": "Bullish"}}]}},
             {"item": "i", "arm": "b", "response": {"choices": [{"message": {"content": "neutral"}}]}},
             {"item": "i", "arm": "c", "error": "HTTP 502"}]
    assert [(r["arm"], r["outcome"]) for r in grade(calls, items)] == [("a", "accepted"), ("b", "rejected")]


def test_window_of_reads_the_suffix_and_leaves_unwindowed_arms_alone():
    from examples.distillation_loop.progress import window_of
    assert [window_of(a) for a in ("student-w3", "prismyra-confidence-w12", "prismyra", "gpt-6.1-terra")] == \
        [3, 12, None, None]
