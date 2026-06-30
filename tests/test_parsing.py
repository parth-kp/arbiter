from arbiter.core.transcript import TranscriptEvent
from arbiter.judge import parse_verdicts, render_transcript
from arbiter.simuser import parse_user_turn


def test_user_turn_parsing_is_forgiving():
    assert parse_user_turn('{"status": "continue", "message": "hi"}').message == "hi"
    assert parse_user_turn('Sure! {"status":"done","message":""}').status == "done"
    assert parse_user_turn("just text").message == "just text"
    assert parse_user_turn('{"status": "weird", "message": "x"}').status == "continue"
    assert parse_user_turn('{"status": "continue", "message": ""}').status == "done"


def test_judge_verdict_parsing_defaults_to_fail():
    v = parse_verdicts('```json\n{"a": {"verdict": "PASS", "reasoning": "r"}, "b": "maybe", "c": "na"}\n```')
    assert v["a"]["verdict"] == "pass" and v["b"]["verdict"] == "fail" and v["c"]["verdict"] == "na"
    assert parse_verdicts("no json here") == {}


def test_render_transcript_truncates_long_tool_results():
    events = [TranscriptEvent(kind="tool_result", turn=0, tool="t", result="x" * 2000, ok=True)]
    assert "truncated" in render_transcript(events)
