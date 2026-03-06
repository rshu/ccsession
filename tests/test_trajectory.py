import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccsession.export.trajectory import (
    _transform_content_block,
    _transform_turn,
    _compute_statistics,
    format_trajectory,
)


# ---------------------------------------------------------------------------
# Fixtures: sample raw JSONL message dicts
# ---------------------------------------------------------------------------

def _user_msg(text="Hello", timestamp="2026-03-02T10:00:00Z", uuid="u1"):
    return {
        "uuid": uuid,
        "parentUuid": None,
        "isSidechain": False,
        "userType": "external",
        "cwd": "/home/user/project",
        "sessionId": "sess-1",
        "timestamp": timestamp,
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }


def _assistant_msg(text="Hi there", tool_calls=None, thinking=None,
                   timestamp="2026-03-02T10:00:05Z", uuid="a1",
                   model="claude-sonnet-4-20250514"):
    content = []
    if thinking:
        content.append({"type": "thinking", "thinking": thinking, "signature": "sig123"})
    content.append({"type": "text", "text": text})
    if tool_calls:
        content.extend(tool_calls)
    return {
        "uuid": uuid,
        "parentUuid": "u1",
        "isSidechain": False,
        "userType": "external",
        "cwd": "/home/user/project",
        "sessionId": "sess-1",
        "timestamp": timestamp,
        "type": "assistant",
        "requestId": "req_01TEST",
        "message": {
            "role": "assistant",
            "model": model,
            "id": "msg_01TEST",
            "type": "message",
            "content": content,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 30,
                "cache_creation_input_tokens": 10,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 0,
                    "ephemeral_1h_input_tokens": 30,
                },
                "service_tier": "standard",
                "inference_geo": "not_available",
            },
            "stop_reason": "end_turn",
            "stop_sequence": None,
        },
    }


def _tool_result_msg(tool_use_id="toolu_1", output="file contents...",
                     is_error=False, timestamp="2026-03-02T10:00:10Z",
                     duration_ms=150, exit_code=0, bytes_count=500):
    msg = {
        "uuid": "tr1",
        "parentUuid": "a1",
        "isSidechain": False,
        "userType": "external",
        "cwd": "/home/user/project",
        "sessionId": "sess-1",
        "timestamp": timestamp,
        "type": "user",
        "message": {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": output,
                "is_error": is_error,
            }],
        },
    }
    if duration_ms is not None:
        msg["toolUseResult"] = {
            "durationMs": duration_ms,
            "code": exit_code,
            "bytes": bytes_count,
        }
    return msg


# ---------------------------------------------------------------------------
# _transform_content_block
# ---------------------------------------------------------------------------

class TestTransformContentBlock:
    def test_text_block(self):
        result = _transform_content_block({"type": "text", "text": "hello"})
        assert result == {"type": "text", "text": "hello"}

    def test_thinking_block(self):
        result = _transform_content_block({"type": "thinking", "thinking": "reasoning...", "signature": "sig"})
        assert result == {"type": "thinking", "text": "reasoning...", "signature": "sig"}

    def test_thinking_block_no_signature(self):
        result = _transform_content_block({"type": "thinking", "thinking": "reasoning..."})
        assert result == {"type": "thinking", "text": "reasoning..."}

    def test_tool_use_becomes_tool_call(self):
        result = _transform_content_block({
            "type": "tool_use",
            "id": "toolu_1",
            "name": "Read",
            "input": {"file_path": "/tmp/test.py"},
        })
        assert result == {
            "type": "tool_call",
            "id": "toolu_1",
            "name": "Read",
            "input": {"file_path": "/tmp/test.py"},
        }

    def test_tool_result_renamed_fields(self):
        result = _transform_content_block({
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": "output text",
            "is_error": False,
        })
        assert result == {
            "type": "tool_result",
            "tool_call_id": "toolu_1",
            "output": "output text",
            "is_error": False,
        }

    def test_tool_result_non_string_content(self):
        result = _transform_content_block({
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": [{"type": "text", "text": "hi"}],
            "is_error": False,
        })
        assert isinstance(result["output"], str)

    def test_unknown_type_returns_none(self):
        result = _transform_content_block({"type": "unknown_type", "data": "something"})
        assert result is None

    def test_non_dict_returns_none(self):
        result = _transform_content_block("not a dict")
        assert result is None


# ---------------------------------------------------------------------------
# _transform_turn
# ---------------------------------------------------------------------------

class TestTransformTurn:
    def test_user_turn(self):
        turn = _transform_turn(_user_msg("Hello"), index=0)
        assert turn["index"] == 0
        assert turn["role"] == "user"
        assert turn["timestamp"] == "2026-03-02T10:00:00Z"
        assert len(turn["content"]) == 1
        assert turn["content"][0] == {"type": "text", "text": "Hello"}

    def test_user_turn_top_level_fields(self):
        turn = _transform_turn(_user_msg("Hello", uuid="u1"), index=0)
        assert turn["uuid"] == "u1"
        assert turn["parent_uuid"] is None
        assert turn["is_sidechain"] is False
        assert turn["user_type"] == "external"
        assert turn["cwd"] == "/home/user/project"

    def test_assistant_turn(self):
        turn = _transform_turn(_assistant_msg("Hi"), index=1)
        assert turn["role"] == "assistant"
        assert turn["model"] == "claude-sonnet-4-20250514"
        assert turn["stop_reason"] == "end_turn"
        assert "usage" in turn
        assert turn["usage"]["input_tokens"] == 100

    def test_assistant_turn_all_fields(self):
        turn = _transform_turn(_assistant_msg("Hi"), index=1)
        # Top-level JSONL fields
        assert turn["uuid"] == "a1"
        assert turn["parent_uuid"] == "u1"
        assert turn["is_sidechain"] is False
        assert turn["user_type"] == "external"
        assert turn["cwd"] == "/home/user/project"
        assert turn["request_id"] == "req_01TEST"
        # Message-level fields
        assert turn["message_id"] == "msg_01TEST"
        assert turn["stop_sequence"] is None
        # Full usage with nested cache_creation
        assert turn["usage"]["cache_creation"]["ephemeral_1h_input_tokens"] == 30
        assert turn["usage"]["service_tier"] == "standard"
        assert turn["usage"]["inference_geo"] == "not_available"

    def test_assistant_with_thinking(self):
        msg = _assistant_msg("Hi", thinking="I think...")
        turn = _transform_turn(msg, index=0)
        assert turn["content"][0] == {"type": "thinking", "text": "I think...", "signature": "sig123"}
        assert turn["content"][1] == {"type": "text", "text": "Hi"}

    def test_thinking_preserved(self):
        msg = _assistant_msg("Hi", thinking="reasoning here")
        turn = _transform_turn(msg, index=0)
        types = [b["type"] for b in turn["content"]]
        assert "thinking" in types

    def test_tool_result_turn_with_execution(self):
        msg = _tool_result_msg(duration_ms=200, exit_code=0, bytes_count=1024)
        turn = _transform_turn(msg, index=2)
        assert turn["role"] == "user"
        assert turn["content"][0]["type"] == "tool_result"
        # toolUseResult is passed through as-is (camelCase keys preserved)
        assert turn["tool_execution"]["durationMs"] == 200
        assert turn["tool_execution"]["code"] == 0
        assert turn["tool_execution"]["bytes"] == 1024

    def test_tool_execution_with_extra_fields(self):
        msg = _tool_result_msg()
        msg["toolUseResult"]["codeText"] = "OK"
        msg["toolUseResult"]["url"] = "https://example.com"
        turn = _transform_turn(msg, index=0)
        # Raw camelCase keys preserved from JSONL
        assert turn["tool_execution"]["codeText"] == "OK"
        assert turn["tool_execution"]["url"] == "https://example.com"

    def test_no_message_becomes_event(self):
        turn = _transform_turn({"uuid": "x", "type": "system", "timestamp": "t"}, index=0)
        assert turn["role"] == "event"
        assert turn["event_type"] == "system"
        assert turn["uuid"] == "x"
        assert turn["index"] == 0

    def test_no_role_becomes_event(self):
        turn = _transform_turn({"message": {"content": []}, "type": "unknown"}, index=0)
        assert turn["role"] == "event"

    def test_progress_event(self):
        turn = _transform_turn({
            "type": "progress",
            "uuid": "p1",
            "parentUuid": "a1",
            "cwd": "/home/user/project",
            "toolUseID": "toolu_1",
            "parentToolUseID": "toolu_0",
            "timestamp": "2026-03-02T10:00:03Z",
            "data": {"content": "searching..."},
        }, index=5)
        assert turn["role"] == "event"
        assert turn["event_type"] == "progress"
        assert turn["tool_use_id"] == "toolu_1"
        assert turn["parent_tool_use_id"] == "toolu_0"
        assert turn["data"] == {"content": "searching..."}

    def test_string_content(self):
        msg = {"message": {"role": "user", "content": "just text"}, "timestamp": "t"}
        turn = _transform_turn(msg, index=0)
        assert turn["content"] == [{"type": "text", "text": "just text"}]


# ---------------------------------------------------------------------------
# _compute_statistics
# ---------------------------------------------------------------------------

class TestComputeStatistics:
    def test_basic_stats(self):
        turns = [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "tool_call", "id": "t1", "name": "Read", "input": {}},
                    {"type": "tool_call", "id": "t2", "name": "Grep", "input": {}},
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 10,
                },
            },
            {"role": "user", "content": [{"type": "tool_result", "tool_call_id": "t1", "output": "x", "is_error": False}]},
            {
                "role": "assistant",
                "content": [{"type": "tool_call", "id": "t3", "name": "Read", "input": {}}],
                "usage": {"input_tokens": 200, "output_tokens": 100},
            },
        ]
        stats = _compute_statistics(turns)
        assert stats["turns"] == 4
        assert stats["user_turns"] == 2
        assert stats["assistant_turns"] == 2
        assert stats["tool_calls"] == 3
        assert stats["tool_calls_by_name"] == {"Read": 2, "Grep": 1}
        assert stats["tokens"]["input"] == 300
        assert stats["tokens"]["output"] == 150
        assert stats["tokens"]["cache_read"] == 20
        assert stats["tokens"]["cache_creation"] == 10

    def test_empty_trajectory(self):
        stats = _compute_statistics([])
        assert stats["turns"] == 0
        assert stats["tool_calls"] == 0
        assert stats["tokens"]["input"] == 0

    def test_tool_calls_sorted_by_count(self):
        turns = [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_call", "name": "Glob", "id": "1", "input": {}},
                    {"type": "tool_call", "name": "Read", "id": "2", "input": {}},
                    {"type": "tool_call", "name": "Read", "id": "3", "input": {}},
                    {"type": "tool_call", "name": "Read", "id": "4", "input": {}},
                ],
                "usage": {},
            },
        ]
        stats = _compute_statistics(turns)
        names = list(stats["tool_calls_by_name"].keys())
        assert names[0] == "Read"
        assert names[1] == "Glob"


# ---------------------------------------------------------------------------
# format_trajectory (integration)
# ---------------------------------------------------------------------------

class TestFormatTrajectory:
    def _make_metadata(self):
        return {
            "session_id": "sess-abc123",
            "start_time": "2026-03-02T10:00:00Z",
            "end_time": "2026-03-02T10:05:00Z",
            "project_dir": "/home/user/project",
            "total_messages": 3,
            "user_messages": 2,
            "assistant_messages": 1,
            "tool_uses": 1,
            "models_used": ["claude-sonnet-4-20250514"],
        }

    def _make_msg_meta(self):
        return {"version": "1.0.33", "git_branch": "main", "slug": "test-session"}

    def test_top_level_structure(self):
        messages = [_user_msg(), _assistant_msg()]
        result = format_trajectory(messages, self._make_metadata(), self._make_msg_meta())
        assert result["format"] == "ccsession-trajectory"
        assert result["format_version"] == "1.0"
        assert result["generator"]["name"] == "ccsession"
        assert "session" in result
        assert "statistics" in result
        assert "trajectory" in result
        assert "sub_agents" in result

    def test_session_metadata(self):
        messages = [_user_msg()]
        result = format_trajectory(messages, self._make_metadata(), self._make_msg_meta())
        session = result["session"]
        assert session["id"] == "sess-abc123"
        assert session["slug"] == "test-session"
        assert session["working_directory"] == "/home/user/project"
        assert session["git_branch"] == "main"
        assert session["claude_code_version"] == "1.0.33"
        assert session["duration_seconds"] == 300

    def test_trajectory_turns(self):
        tool_call = {"type": "tool_use", "id": "toolu_1", "name": "Read",
                     "input": {"file_path": "/tmp/x.py"}}
        messages = [
            _user_msg("Fix bug"),
            _assistant_msg("Let me look", tool_calls=[tool_call]),
            _tool_result_msg("toolu_1", "code here"),
        ]
        result = format_trajectory(messages, self._make_metadata(), self._make_msg_meta())
        traj = result["trajectory"]
        assert len(traj) == 3
        assert traj[0]["role"] == "user"
        assert traj[1]["role"] == "assistant"
        assert traj[2]["role"] == "user"  # tool result comes as user turn

        # Check tool_call
        tool_calls = [b for b in traj[1]["content"] if b["type"] == "tool_call"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "Read"

        # Check tool_result
        tool_results = [b for b in traj[2]["content"] if b["type"] == "tool_result"]
        assert len(tool_results) == 1
        assert tool_results[0]["tool_call_id"] == "toolu_1"

    def test_statistics_computed(self):
        tool_call = {"type": "tool_use", "id": "toolu_1", "name": "Bash",
                     "input": {"command": "ls"}}
        messages = [
            _user_msg("Run ls"),
            _assistant_msg("Sure", tool_calls=[tool_call]),
            _tool_result_msg("toolu_1", "file1\nfile2"),
        ]
        result = format_trajectory(messages, self._make_metadata(), self._make_msg_meta())
        stats = result["statistics"]
        assert stats["turns"] == 3
        assert stats["tool_calls"] == 1
        assert stats["tool_calls_by_name"]["Bash"] == 1
        assert stats["sub_agent_count"] == 0

    def test_no_sub_agents(self):
        messages = [_user_msg()]
        result = format_trajectory(messages, self._make_metadata(), self._make_msg_meta())
        assert result["sub_agents"] == []
        assert result["statistics"]["sub_agent_count"] == 0

    def test_thinking_preserved(self):
        messages = [_user_msg(), _assistant_msg("Hi", thinking="deep reasoning")]
        result = format_trajectory(messages, self._make_metadata(), self._make_msg_meta())
        assistant_turn = result["trajectory"][1]
        thinking_blocks = [b for b in assistant_turn["content"] if b["type"] == "thinking"]
        assert len(thinking_blocks) == 1
        assert thinking_blocks[0]["text"] == "deep reasoning"

    def test_tool_output_preserved(self):
        messages = [
            _user_msg(),
            _assistant_msg("ok", tool_calls=[{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]),
            _tool_result_msg("t1", "full output content"),
        ]
        result = format_trajectory(messages, self._make_metadata(), self._make_msg_meta())
        tool_results = [b for t in result["trajectory"] for b in t["content"]
                        if b.get("type") == "tool_result"]
        assert tool_results[0]["output"] == "full output content"

    def test_non_message_events_included(self):
        """Events without a 'message' key should be included as event entries."""
        messages = [
            {"uuid": "x", "type": "system", "timestamp": "t"},
            _user_msg("Hello"),
        ]
        result = format_trajectory(messages, self._make_metadata(), self._make_msg_meta())
        assert len(result["trajectory"]) == 2
        assert result["trajectory"][0]["role"] == "event"
        assert result["trajectory"][0]["event_type"] == "system"
        assert result["trajectory"][1]["role"] == "user"
        assert result["statistics"]["events"] == 1
