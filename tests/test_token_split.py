"""What a single token total hides, which the first real pair demonstrated."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
import token_split as ts  # noqa: E402


def joined(tmp_path, name, legs, turns=1):
    p = tmp_path / name
    p.write_text(json.dumps({"rows": [{"legs": legs, "turns": turns}]}))
    return p


def test_the_cache_hit_rate_is_what_separated_the_first_real_pair(tmp_path):
    """14.3 million tokens against 23.6 million looked like different amounts of work. The self-hosted arm read
    12.97 million of its 14.29 from a prefix cache, so 1.22 million were fresh; the metered path cached nothing."""
    box = ts.split(joined(tmp_path, "box.json",
                          {"fresh_in": 1_223_646, "cached_in": 12_971_904, "cache_write": 0, "out": 97_516}))
    api = ts.split(joined(tmp_path, "api.json",
                          {"fresh_in": 23_390_260, "cached_in": 0, "cache_write": 0, "out": 226_281}))
    assert box["cache_hit_rate"] == pytest.approx(0.9138, abs=0.0002)
    assert api["cache_hit_rate"] == 0.0
    assert api["fresh_in"] / box["fresh_in"] == pytest.approx(19.1, abs=0.1)


def test_an_arm_with_no_input_at_all_reports_no_hit_rate_rather_than_zero(tmp_path):
    """Zero would read as a cache that missed everything, which is a different fact from nothing measured."""
    got = ts.split(joined(tmp_path, "x.json", {"fresh_in": 0, "cached_in": 0, "cache_write": 0, "out": 5}))
    assert got["cache_hit_rate"] is None and got["total"] == 5


def test_labels_must_match_the_inputs(tmp_path, capsys):
    p = joined(tmp_path, "a.json", {"fresh_in": 1, "cached_in": 0, "cache_write": 0, "out": 1})
    old = sys.argv
    sys.argv = ["token_split", "--joined", str(p), "--label", "one", "--label", "two"]
    try:
        with pytest.raises(SystemExit) as e:
            ts.main()
    finally:
        sys.argv = old
    assert "one --label per --joined" in str(e.value)
