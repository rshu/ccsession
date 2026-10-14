"""Tests for the import-time reference remapper, shaped after Claude Code 2.1.287 records."""
from __future__ import annotations

import copy
from pathlib import Path

from ccsession.importing.remap import RemapPlan, build_remap_plan, most_common_cwd, remap_record, remap_records

OLD_SID = "7f6738b0-d2cb-44ae-a806-09860af58e1f"
NEW_SID = "1daacb2b-ece9-454d-8640-89d7cbcde89a"
OLD_PROJECT = "/home/old/proj"
NEW_PROJECT = "/home/new/proj"
NEW_SESSION_DIR = f"/home/new/.claude/projects/-home-new-proj/{NEW_SID}"
NEW_FILE_HISTORY = f"/home/new/.claude/file-history/{NEW_SID}"
AGENT = "a9ba8b4d8b37efc78"


def _plan(uuid_map=None, agent_map=None, old_project=OLD_PROJECT):
    """A plan with explicit id maps; path rules come from build_remap_plan so they stay in sync."""
    rules = build_remap_plan(
        main_records=[], agent_records_by_id={},
        old_session_id=OLD_SID, new_session_id=NEW_SID,
        old_project_path=old_project, new_project_path=NEW_PROJECT,
        new_session_dir=Path(NEW_SESSION_DIR), new_file_history_dir=Path(NEW_FILE_HISTORY),
        regenerate_ids=False,
    ).path_rules
    return RemapPlan(old_session_id=OLD_SID, new_session_id=NEW_SID,
                     uuid_map=uuid_map or {}, agent_map=agent_map or {}, path_rules=rules)


def test_uuid_references_are_rewritten_consistently_across_every_field():
    plan = _plan(uuid_map={"u1": "n1", "u2": "n2", "u3": "n3"})
    records = [
        {"type": "user", "uuid": "u1", "parentUuid": None, "sessionId": OLD_SID},
        {"type": "assistant", "uuid": "u2", "parentUuid": "u1", "sessionId": OLD_SID, "supersedesUuids": ["u1"]},
        {"type": "user", "uuid": "u3", "parentUuid": "u2", "sessionId": OLD_SID, "sourceToolAssistantUUID": "u2"},
        {"type": "last-prompt", "sessionId": OLD_SID, "lastPrompt": "x", "leafUuid": "u3"},
        {"type": "file-history-snapshot", "messageId": "u1", "snapshot": {"messageId": "u1", "trackedFileBackups": {}}},
        {"type": "file-history-delta", "messageId": "u3", "snapshotMessageId": "u1"},
        {"type": "queue-operation", "operation": "dequeue", "sessionId": OLD_SID, "commandUuid": "u2"},
        {"type": "system", "subtype": "compact_boundary", "uuid": "u2", "logicalParentUuid": "u1",
         "foldedUuids": ["u1", "u3"], "compactMetadata": {"preservedSegment": {"headUuid": "u1", "anchorUuid": "u3"}}},
    ]

    out = remap_records(records, plan)

    assert [r.get("uuid") for r in out][:3] == ["n1", "n2", "n3"]
    assert out[1]["parentUuid"] == "n1" and out[1]["supersedesUuids"] == ["n1"]
    assert out[2]["sourceToolAssistantUUID"] == "n2"
    assert out[3]["leafUuid"] == "n3"
    assert out[4]["messageId"] == "n1" and out[4]["snapshot"]["messageId"] == "n1"
    assert out[5] == {"type": "file-history-delta", "messageId": "n3", "snapshotMessageId": "n1"}
    assert out[6]["commandUuid"] == "n2"
    assert out[7]["logicalParentUuid"] == "n1" and out[7]["foldedUuids"] == ["n1", "n3"]
    assert out[7]["compactMetadata"]["preservedSegment"] == {"headUuid": "n1", "anchorUuid": "n3"}
    assert records[1]["parentUuid"] == "u1", "input must not be mutated"


def test_unknown_reference_values_are_left_alone():
    plan = _plan(uuid_map={"u1": "n1"})
    record = {"type": "last-prompt", "leafUuid": "not-in-any-transcript", "sessionId": OLD_SID,
              "ownerAccountUuid": "acc-1", "requestId": "req_01", "promptId": "p-1"}
    out = remap_record(record, plan)
    assert out["leafUuid"] == "not-in-any-transcript"
    assert out["ownerAccountUuid"] == "acc-1" and out["requestId"] == "req_01" and out["promptId"] == "p-1"


def test_session_id_is_rewritten_only_when_it_names_the_old_session():
    plan = _plan()
    bg = {"type": "attachment", "sessionId": OLD_SID, "session_id": "2184c23b-0000-0000-0000-000000000000", "sessionKind": "bg"}
    same = {"type": "user", "sessionId": OLD_SID, "session_id": OLD_SID}
    assert remap_record(bg, plan)["sessionId"] == NEW_SID
    assert remap_record(bg, plan)["session_id"] == "2184c23b-0000-0000-0000-000000000000"
    assert remap_record(same, plan)["session_id"] == NEW_SID


def test_agent_ids_are_rewritten_in_tool_results_records_and_meta():
    plan = _plan(agent_map={AGENT: "bbbbbbbbbbbbbbbbb", "c0c0c0c0c0c0c0c0c": "ddddddddddddddddd"})
    main = {"type": "user", "sessionId": OLD_SID,
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_01", "content": "done"}]},
            "toolUseResult": {"agentId": AGENT, "status": "completed", "prompt": "find it"}}
    sub = {"type": "assistant", "agentId": AGENT, "sessionId": OLD_SID, "message": {"role": "assistant", "content": []}}
    meta = {"agentType": "general-purpose", "toolUseId": "toolu_01", "parentAgentId": "c0c0c0c0c0c0c0c0c", "spawnDepth": 2}

    assert remap_record(main, plan)["toolUseResult"]["agentId"] == "bbbbbbbbbbbbbbbbb"
    assert remap_record(sub, plan)["agentId"] == "bbbbbbbbbbbbbbbbb"
    out_meta = remap_record(meta, plan)
    assert out_meta["parentAgentId"] == "ddddddddddddddddd" and out_meta["toolUseId"] == "toolu_01"


def test_paths_under_old_project_are_relocated_and_others_untouched():
    plan = _plan()
    record = {"type": "user", "cwd": OLD_PROJECT, "sessionId": OLD_SID,
              "toolUseResult": {"filePath": f"{OLD_PROJECT}/calc/ops.py", "stdout": f"ran in {OLD_PROJECT}"},
              "attachment": {"type": "environment", "snapshot": {"workingDirectory": f"{OLD_PROJECT}/sub"}}}
    elsewhere = {"type": "user", "cwd": "/home/old/projx", "toolUseResult": {"filePath": "/etc/hosts"}}

    out = remap_record(record, plan)
    assert out["cwd"] == NEW_PROJECT
    assert out["toolUseResult"]["filePath"] == f"{NEW_PROJECT}/calc/ops.py"
    assert out["toolUseResult"]["stdout"] == f"ran in {OLD_PROJECT}", "free text is not a path field"
    assert out["attachment"]["snapshot"]["workingDirectory"] == f"{NEW_PROJECT}/sub"
    assert remap_record(elsewhere, plan) == elsewhere


def test_session_dir_and_file_history_paths_follow_the_new_session():
    plan = _plan()
    record = {"type": "user",
              "toolUseResult": {"persistedOutputPath": f"/Users/old/.claude/projects/-home-old-proj/{OLD_SID}/tool-results/b7.txt",
                                "transcriptDir": f"/Users/old/.claude/projects/-home-old-proj/{OLD_SID}"}}
    delta = {"type": "file-history-delta", "backup": f"/Users/old/.claude/file-history/{OLD_SID}/160c@v3"}

    out = remap_record(record, plan)
    assert out["toolUseResult"]["persistedOutputPath"] == f"{NEW_SESSION_DIR}/tool-results/b7.txt"
    assert out["toolUseResult"]["transcriptDir"] == NEW_SESSION_DIR
    assert remap_record(delta, plan)["backup"] == f"{NEW_FILE_HISTORY}/160c@v3"


def test_message_content_is_never_touched():
    plan = _plan(uuid_map={"u1": "n1"})
    record = {"type": "assistant", "uuid": "u1", "sessionId": OLD_SID, "requestId": "req_01",
              "message": {"id": "msg_01", "role": "assistant", "content": [
                  {"type": "thinking", "thinking": f"cwd is {OLD_PROJECT} and parent u1", "signature": "SIG"},
                  {"type": "tool_use", "id": "toolu_01", "name": "Read", "input": {"file_path": f"{OLD_PROJECT}/a.py"}},
                  {"type": "text", "text": OLD_SID}]}}
    before = copy.deepcopy(record["message"])
    out = remap_record(record, plan)
    assert out["message"] == before and out["uuid"] == "n1" and out["requestId"] == "req_01"


def test_build_plan_assigns_fresh_ids_to_every_uuid_and_agent():
    main = [{"uuid": "u1"}, {"uuid": "u2", "toolUseResult": {"agentId": AGENT}}]
    agents = {AGENT: [{"uuid": "s1", "agentId": AGENT}, {"uuid": "s2", "agentId": AGENT}]}
    plan = build_remap_plan(main_records=main, agent_records_by_id=agents,
                            old_session_id=OLD_SID, new_session_id=NEW_SID,
                            old_project_path=OLD_PROJECT, new_project_path=NEW_PROJECT,
                            new_session_dir=Path(NEW_SESSION_DIR), new_file_history_dir=Path(NEW_FILE_HISTORY),
                            regenerate_ids=True)
    assert set(plan.uuid_map) == {"u1", "u2", "s1", "s2"}
    assert len(set(plan.uuid_map.values())) == 4 and not set(plan.uuid_map.values()) & set(plan.uuid_map)
    assert set(plan.agent_map) == {AGENT} and len(plan.agent_map[AGENT]) == 17 and plan.agent_map[AGENT] != AGENT


def test_preserve_mode_keeps_ids_and_only_relocates_paths():
    plan = build_remap_plan(main_records=[{"uuid": "u1"}], agent_records_by_id={AGENT: [{"uuid": "s1"}]},
                            old_session_id=OLD_SID, new_session_id=OLD_SID,
                            old_project_path=OLD_PROJECT, new_project_path=NEW_PROJECT,
                            new_session_dir=Path(NEW_SESSION_DIR), new_file_history_dir=Path(NEW_FILE_HISTORY),
                            regenerate_ids=False)
    out = remap_record({"uuid": "u1", "sessionId": OLD_SID, "cwd": OLD_PROJECT, "agentId": AGENT}, plan)
    assert out == {"uuid": "u1", "sessionId": OLD_SID, "cwd": NEW_PROJECT, "agentId": AGENT}


def test_most_common_cwd_ignores_records_without_one():
    records = [{"type": "mode"}, {"cwd": "/a"}, {"cwd": "/b"}, {"cwd": "/a"}]
    assert most_common_cwd(records) == "/a"
    assert most_common_cwd([{"type": "mode"}]) is None
