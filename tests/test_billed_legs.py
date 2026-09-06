"""The gateway bills four token legs and the wire tells you which of two conventions it used.

Every test here is a number that would have looked plausible and been wrong. The occasion is
stratoclave v1.3.0, which started reporting the prompt-cache read and write legs after a measured
request billed 3,538 tokens and answered `total_tokens: 14`; the fix reports them as keys *disjoint*
from `prompt_tokens`, while the OpenAI-compatible pass-through keeps forwarding the provider's own
`prompt_tokens_details.cached_tokens`, where a cache read is a *subset* of it. One gateway, two
conventions, told apart by the key the value arrived under -- so a harness that assumes either one
globally is wrong on half its traffic and silently.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "harness"))
from tierbook import policy  # noqa: E402
import transport  # noqa: E402


# The two calls stratoclave measured over one 3,524-token cached prefix, as its own release note
# reports them: 10 uncached input, 4 output, and the prefix as a write on the first call and a read
# on the second. `total_tokens` is 14 on both, which is the defect these keys exist to close.
MEASURED_WRITE = {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14,
                  "cache_creation_input_tokens": 3524}
MEASURED_READ = {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14,
                 "cache_read_input_tokens": 3524}


def _read(usage):
    reply = transport.Reply(model="m")
    transport._usage(reply, usage)
    return reply


# --- which convention, read from the wire rather than assumed -------------------------------------


def test_a_top_level_cache_leg_is_disjoint_from_prompt_tokens():
    reply = _read(MEASURED_READ)
    assert reply.legs_are_subset is False
    # The whole point: `prompt_tokens` is the uncached input, so all 10 of it is fresh. Subtracting
    # the read leg gives max(0, 10 - 3524) = 0 and prices a warm turn as if none of it were fresh.
    assert reply.fresh_prompt_tokens == 10
    assert reply.cached_prompt_tokens == 3524
    assert reply.billed_input_tokens == 3534


def test_a_nested_cache_leg_is_a_subset_of_prompt_tokens():
    reply = _read({"prompt_tokens": 3534, "completion_tokens": 4,
                   "prompt_tokens_details": {"cached_tokens": 3524}})
    assert reply.legs_are_subset is True
    assert reply.fresh_prompt_tokens == 10
    assert reply.billed_input_tokens == 3534


def test_the_two_conventions_agree_on_what_was_billed():
    # Same call, two spellings. If the readings disagree, one of the two transports is mispriced.
    disjoint = _read(MEASURED_READ)
    subset = _read({"prompt_tokens": 3534, "completion_tokens": 4,
                    "prompt_tokens_details": {"cached_tokens": 3524}})
    for leg in ("fresh_prompt_tokens", "cached_prompt_tokens", "billed_input_tokens"):
        assert getattr(disjoint, leg) == getattr(subset, leg), leg


def test_a_write_leg_is_disjoint_and_does_not_eat_the_fresh_leg():
    reply = _read(MEASURED_WRITE)
    assert reply.legs_are_subset is False
    assert (reply.fresh_prompt_tokens, reply.cache_write_tokens) == (10, 3524)


def test_no_cache_leg_leaves_the_convention_unanswered():
    # And leaves the subtraction a no-op, so an uncached call prices identically either way.
    reply = _read({"prompt_tokens": 900, "completion_tokens": 12})
    assert reply.legs_are_subset is None
    assert reply.fresh_prompt_tokens == 900


def test_an_absent_leg_is_not_a_measured_zero():
    # The gateway omits a leg it did not observe rather than reporting 0, on the same reasoning that
    # made an unreadable usage block stop settling as a measured zero. Reading a 0 back into the
    # convention flag would turn "not reported" into "reported as none".
    assert _read(MEASURED_READ).cache_write_tokens == 0
    assert _read({"prompt_tokens": 10, "completion_tokens": 4,
                  "cache_read_input_tokens": 0}).legs_are_subset is False


# --- a call served entirely from cache is still a priced call -------------------------------------


def test_a_fully_cached_turn_is_not_mistaken_for_a_broken_stream():
    # Under the disjoint convention `prompt_tokens` is 0 when nothing was fresh. Treating that as
    # unpriced would overwrite the provider's own figures with a character-count estimate.
    reply = _read({"prompt_tokens": 0, "completion_tokens": 0, "cache_read_input_tokens": 3524})
    assert reply.priced is True
    before = reply.cached_prompt_tokens
    reply.estimate_usage(40_000)
    assert reply.cached_prompt_tokens == before and reply.estimated is False


def test_an_estimate_declares_the_convention_it_built():
    # An estimate takes a share OF the whole input, so its legs are a subset. Left at None the
    # cached share would be charged twice, once as cached and once inside the fresh remainder.
    reply = transport.Reply(model="m")
    reply.estimate_usage(4_000, cached_share=0.5)
    assert reply.legs_are_subset is True
    assert reply.fresh_prompt_tokens + reply.cached_prompt_tokens == reply.prompt_tokens


# --- the price card can express what the gateway bills ---------------------------------------------


def _card(**over):
    base = {"unit": "usd_per_mtok", "source": "test", "fresh_in": 3.0, "cached_in": 0.3,
            "cache_write": 3.75, "output": 15.0}
    return policy.Tier("t", {"price_card": {**base, **over}})


def test_all_four_legs_are_charged():
    cost = _card().token_cost(1_000_000, 1_000_000, 1_000_000, cache_write=1_000_000)
    assert round(cost, 4) == round(3.0 + 0.3 + 15.0 + 3.75, 4)


def test_a_card_with_no_write_rate_charges_the_write_as_fresh_and_says_it_is_a_floor():
    # Not zero. A write the card cannot express is the same failure as a cache rate it cannot
    # express: unmeasured is not free, and the tier that cannot report it would come out cheapest.
    blind = _card(cache_write=None)
    assert round(blind.token_cost(0, 0, 0, cache_write=1_000_000), 4) == 3.0
    assert blind.write_rate_is_a_floor is True
    assert _card().write_rate_is_a_floor is False


def test_omitting_the_write_leg_is_the_same_as_not_having_one():
    # So every existing three-leg caller keeps its number.
    assert _card().token_cost(1_000, 1_000, 1_000) == _card().token_cost(1_000, 1_000, 1_000, 0)


# --- a reasoning parameter the provider's wire cannot read ------------------------------------------


def test_a_claude_tier_is_recognised_as_speaking_the_anthropic_wire():
    from harness import policy as hp  # noqa: PLC0415
    assert hp.speaks_anthropic_wire("claude-fable-5") is True
    assert hp.speaks_anthropic_wire("us.anthropic.claude-fable-5") is True
    assert hp.speaks_anthropic_wire("gpt-5.6-terra") is False
    assert hp.speaks_anthropic_wire("Qwen/Qwen3.6-35B-A3B") is False


def test_reasoning_effort_on_the_anthropic_wire_is_refused_at_load(tmp_path):
    """The defect this closes cost a whole arm.

    `reasoning_effort` is the OpenAI-shaped channel. On the gateway's Anthropic wire nothing reads it
    -- the string is absent from the backend -- so a tiers.json pairing the two declared a thinking
    arm, measured a non-thinking one, and paid premium prices for the privilege without a single
    warning. Silence is the failure; the fix is that the run does not start.
    """
    import json  # noqa: PLC0415
    import harness.loop as hl  # noqa: PLC0415
    import pytest  # noqa: PLC0415

    def tiers(effort):
        p = tmp_path / f"tiers-{effort}.json"
        p.write_text(json.dumps({
            "premium": {"model": "claude-fable-5", "pricing_key": "fable", "reasoning_effort": effort},
            "cheap": {"model": "gpt-5.6-terra", "pricing_key": "gpt-5.6-terra",
                      "reasoning_effort": effort, "api": "responses"},
        }))
        return p

    with pytest.raises(SystemExit) as caught:
        hl.load_tiers(tiers("high"), "https://gateway.example/v1")
    message = str(caught.value)
    assert "reasoning_effort" in message and "claude-fable-5" in message
    # It says what to do instead, because a refusal that does not is a wall.
    assert "thinking" in message

    # 'none' is a declaration that the arm does not think, which is true and allowed.
    assert hl.load_tiers(tiers("none"), "https://gateway.example/v1").premium.effort == "none"


def test_the_shipped_tier_configs_load():
    """They carried the defect above, so they are the regression case."""
    from pathlib import Path  # noqa: PLC0415
    import harness.loop as hl  # noqa: PLC0415
    for name in ("tiers.example.json", "tiers.function-calling.json"):
        path = Path(__file__).resolve().parents[1] / "harness" / name
        assert hl.load_tiers(path, "https://gateway.example/v1").premium.effort is None, name


def test_the_self_hosted_engine_write_leg_is_read():
    """vLLM's own spelling, observed on the cluster.

    It reports `prompt_tokens_details: {"cached_tokens": 0, "created_cache_tokens": 7392}` -- the subset
    convention for the read leg and a FOURTH name for the write leg. Missing it counted the box's cache
    writes as nothing, and the box is the tier whose write rate equals its fresh rate, so the leg
    silently dropped was the expensive one.
    """
    reply = _read({"prompt_tokens": 7495, "completion_tokens": 2, "total_tokens": 7497,
                   "prompt_tokens_details": {"cached_tokens": 0, "created_cache_tokens": 7392}})
    assert reply.cache_write_tokens == 7392
    assert reply.legs_are_subset is True
    assert reply.fresh_prompt_tokens == 103
    assert reply.billed_input_tokens == 7495
