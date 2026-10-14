"""Tests for the import-time reference remapper, shaped after Claude Code 2.1.287 records."""
from __future__ import annotations

import copy
from pathlib import PurePosixPath, PureWindowsPath

from ccsession.importing.remap import RemapPlan, build_remap_plan, most_common_cwd, remap_record, remap_records

OLD_SID = "7f6738b0-d2cb-44ae-a806-09860af58e1f"
NEW_SID = "1daacb2b-ece9-454d-8640-89d7cbcde89a"
OLD_PROJECT = "/home/old/proj"
NEW_PROJECT = "/home/new/proj"
NEW_SESSION_DIR = f"/home/new/.claude/projects/-home-new-proj/{NEW_SID}"
NEW_FILE_HISTORY = f"/home/new/.claude/file-history/{NEW_SID}"
AGENT = "a9ba8b4d8b37efc78"


def _plan(uuid_map=None, old_project=OLD_PROJECT):
    """A plan with an explicit uuid map; path rules come from build_remap_plan so they stay in sync."""
    rules = build_remap_plan(
        main_records=[], agent_records_by_id={},
        old_session_id=OLD_SID, new_session_id=NEW_SID,
        old_project_path=old_project, new_project_path=NEW_PROJECT,
        new_session_dir=PurePosixPath(NEW_SESSION_DIR), new_file_history_dir=PurePosixPath(NEW_FILE_HISTORY),
        regenerate_ids=False,
    ).path_rules
    return RemapPlan(old_session_id=OLD_SID, new_session_id=NEW_SID, uuid_map=uuid_map or {}, path_rules=rules)


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
         "foldedUuids": ["u1", "u3"], "compactMetadata": {"preservedSegment": {"headUuid": "u1", "anchorUuid": "u3"},
                                                           "preservedMessages": {"uuids": ["u1", "u2"], "count": 2}}},
        {"type": "attachment", "uuid": "u3", "attachment": {"type": "queued_command", "origin": {"from": "u1"}}},
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
    assert out[7]["compactMetadata"]["preservedMessages"] == {"uuids": ["n1", "n2"], "count": 2}
    assert out[8]["attachment"]["origin"]["from"] == "n1", "references are rewritten by value, whatever the key"
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


def test_agent_ids_are_never_rewritten():
    """Claude Code matches toolUseResult.agentId against <task-id> tags inside message text
    (which import never touches) to decide whether a background agent finished; renaming the
    agent would make every finished background agent look orphaned on resume."""
    plan = build_remap_plan(main_records=[{"uuid": "u1"}], agent_records_by_id={AGENT: [{"uuid": "s1", "agentId": AGENT}]},
                            old_session_id=OLD_SID, new_session_id=NEW_SID,
                            old_project_path=OLD_PROJECT, new_project_path=NEW_PROJECT,
                            new_session_dir=PurePosixPath(NEW_SESSION_DIR), new_file_history_dir=PurePosixPath(NEW_FILE_HISTORY),
                            regenerate_ids=True)
    main = {"type": "user", "sessionId": OLD_SID, "message": {"role": "user", "content": "<task-id>" + AGENT + "</task-id>"},
            "toolUseResult": {"agentId": AGENT, "status": "async_launched"}}
    sub = {"type": "assistant", "agentId": AGENT, "sessionId": OLD_SID, "message": {"role": "assistant", "content": []}}
    meta = {"agentType": "general-purpose", "toolUseId": "toolu_01", "parentAgentId": "c0c0c0c0c0c0c0c0c", "spawnDepth": 2}

    assert remap_record(main, plan)["toolUseResult"]["agentId"] == AGENT
    assert remap_record(sub, plan)["agentId"] == AGENT
    assert remap_record(meta, plan) == meta


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
    assert out["toolUseResult"]["persistedOutputPath"] == f"{PurePosixPath(NEW_SESSION_DIR)}/tool-results/b7.txt"
    assert out["toolUseResult"]["transcriptDir"] == str(PurePosixPath(NEW_SESSION_DIR))
    assert remap_record(delta, plan)["backup"] == f"{PurePosixPath(NEW_FILE_HISTORY)}/160c@v3"


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


def test_build_plan_assigns_fresh_ids_to_every_uuid():
    main = [{"uuid": "u1"}, {"uuid": "u2", "toolUseResult": {"agentId": AGENT}}]
    agents = {AGENT: [{"uuid": "s1", "agentId": AGENT}, {"uuid": "s2", "agentId": AGENT}]}
    plan = build_remap_plan(main_records=main, agent_records_by_id=agents,
                            old_session_id=OLD_SID, new_session_id=NEW_SID,
                            old_project_path=OLD_PROJECT, new_project_path=NEW_PROJECT,
                            new_session_dir=PurePosixPath(NEW_SESSION_DIR), new_file_history_dir=PurePosixPath(NEW_FILE_HISTORY),
                            regenerate_ids=True)
    assert set(plan.uuid_map) == {"u1", "u2", "s1", "s2"}
    assert len(set(plan.uuid_map.values())) == 4 and not set(plan.uuid_map.values()) & set(plan.uuid_map)


def test_preserve_mode_keeps_ids_and_only_relocates_paths():
    plan = build_remap_plan(main_records=[{"uuid": "u1"}], agent_records_by_id={AGENT: [{"uuid": "s1"}]},
                            old_session_id=OLD_SID, new_session_id=OLD_SID,
                            old_project_path=OLD_PROJECT, new_project_path=NEW_PROJECT,
                            new_session_dir=PurePosixPath(NEW_SESSION_DIR), new_file_history_dir=PurePosixPath(NEW_FILE_HISTORY),
                            regenerate_ids=False)
    out = remap_record({"uuid": "u1", "sessionId": OLD_SID, "cwd": OLD_PROJECT, "agentId": AGENT}, plan)
    assert out == {"uuid": "u1", "sessionId": OLD_SID, "cwd": NEW_PROJECT, "agentId": AGENT}


def test_most_common_cwd_ignores_records_without_one():
    records = [{"type": "mode"}, {"cwd": "/a"}, {"cwd": "/b"}, {"cwd": "/a"}]
    assert most_common_cwd(records) == "/a"
    assert most_common_cwd([{"type": "mode"}]) is None


def test_windows_paths_are_relocated_whatever_the_separator():
    old_root = "C:\\Users\\me\\proj"
    session_dir = PureWindowsPath("D:/claude/projects/proj") / NEW_SID
    file_history_dir = PureWindowsPath("D:/claude/file-history") / NEW_SID
    plan = build_remap_plan(main_records=[], agent_records_by_id={},
                            old_session_id=OLD_SID, new_session_id=NEW_SID,
                            old_project_path=old_root, new_project_path="D:\\work\\proj",
                            new_session_dir=session_dir, new_file_history_dir=file_history_dir,
                            regenerate_ids=False)
    record = {"type": "user", "cwd": old_root,
              "toolUseResult": {"filePath": old_root + "\\calc\\ops.py",
                                "persistedOutputPath": "C:\\Users\\me\\.claude\\projects\\C--Users-me-proj\\" + OLD_SID + "\\tool-results\\b7.txt"},
              "attachment": {"snapshot": {"workingDirectory": "C:\\Users\\me\\projx"}}}
    out = remap_record(record, plan)
    assert out["cwd"] == "D:\\work\\proj"
    assert out["toolUseResult"]["filePath"] == "D:\\work\\proj\\calc\\ops.py"
    assert out["toolUseResult"]["persistedOutputPath"] == str(session_dir / "tool-results" / "b7.txt")
    assert out["attachment"]["snapshot"]["workingDirectory"] == "C:\\Users\\me\\projx", "a sibling dir is not under the project"


def test_windows_paths_imported_into_posix_use_target_separators():
    plan = build_remap_plan(main_records=[], agent_records_by_id={},
                            old_session_id=OLD_SID, new_session_id=NEW_SID,
                            old_project_path="C:\\Users\\me\\proj", new_project_path=NEW_PROJECT,
                            new_session_dir=PurePosixPath(NEW_SESSION_DIR), new_file_history_dir=PurePosixPath(NEW_FILE_HISTORY),
                            regenerate_ids=False)
    for original in ("C:\\Users\\me\\proj\\calc\\ops.py", "C:/Users/me/proj/calc/ops.py"):
        assert remap_record({"filePath": original}, plan)["filePath"] == NEW_PROJECT + "/calc/ops.py"
    assert remap_record({"backup": "C:\\Users\\me\\.claude\\file-history\\" + OLD_SID + "\\160c@v3"}, plan)["backup"] == NEW_FILE_HISTORY + "/160c@v3"


def test_posix_paths_imported_into_windows_use_target_separators():
    session_dir = PureWindowsPath("D:/claude/projects/proj") / NEW_SID
    file_history_dir = PureWindowsPath("D:/claude/file-history") / NEW_SID
    plan = build_remap_plan(main_records=[], agent_records_by_id={},
                            old_session_id=OLD_SID, new_session_id=NEW_SID,
                            old_project_path=OLD_PROJECT, new_project_path="D:\\work\\proj",
                            new_session_dir=session_dir, new_file_history_dir=file_history_dir,
                            regenerate_ids=False)
    assert remap_record({"filePath": OLD_PROJECT + "/calc/ops.py"}, plan)["filePath"] == "D:\\work\\proj\\calc\\ops.py"
    original_output = f"/home/old/.claude/projects/proj/{OLD_SID}/tool-results/b7.txt"
    assert remap_record({"persistedOutputPath": original_output}, plan)["persistedOutputPath"] == str(session_dir / "tool-results" / "b7.txt")


def test_posix_root_paths_relocate_without_a_double_separator():
    plan = _plan(old_project="/")
    assert remap_record({"cwd": "/", "filePath": "/calc/ops.py"}, plan) == {
        "cwd": NEW_PROJECT, "filePath": NEW_PROJECT + "/calc/ops.py"}


def test_posix_paths_preserve_literal_backslashes():
    plan = build_remap_plan(main_records=[], agent_records_by_id={},
                            old_session_id=OLD_SID, new_session_id=NEW_SID,
                            old_project_path="/old/proj\\", new_project_path="/new/proj\\",
                            new_session_dir=PurePosixPath(NEW_SESSION_DIR), new_file_history_dir=PurePosixPath(NEW_FILE_HISTORY),
                            regenerate_ids=False)
    assert remap_record({"cwd": "/old/proj\\", "filePath": "/old/proj\\/calc\\ops.py"}, plan) == {
        "cwd": "/new/proj\\", "filePath": "/new/proj\\/calc\\ops.py"}
    assert remap_record({"filePath": "/old/proj\\other/file"}, plan)["filePath"] == "/old/proj\\other/file"


def test_windows_paths_with_a_drive_implicit_root_use_windows_separators():
    session_dir = PureWindowsPath("/config/projects/new")
    plan = build_remap_plan(main_records=[], agent_records_by_id={},
                            old_session_id=OLD_SID, new_session_id=NEW_SID,
                            old_project_path="C:\\work\\proj", new_project_path=PureWindowsPath("/new/project"),
                            new_session_dir=session_dir, new_file_history_dir=PureWindowsPath("/config/file-history/new"),
                            regenerate_ids=False)
    original_output = "C:\\config\\projects\\proj\\" + OLD_SID + "\\tool-results\\b7.txt"
    assert remap_record({"persistedOutputPath": original_output}, plan)["persistedOutputPath"] == str(session_dir / "tool-results" / "b7.txt")
    assert remap_record({"filePath": "C:/work/proj/src/main.py"}, plan)["filePath"] == "\\new\\project\\src\\main.py"
