"""SQLite locking and concurrent-write regression tests."""

from concurrent.futures import ThreadPoolExecutor

from app.db import Database
from app.repositories import NexusRepository


def agent_payload(agent, name):
    return {
        "name": name,
        "campaign": agent["campaign"],
        "greeting": agent["greeting"],
        "transfersEnabled": agent["transfersEnabled"],
        "requireConsent": agent["requireConsent"],
        "sttProvider": agent["sttProvider"],
        "sttModel": agent["sttModel"],
        "ttsProvider": agent["ttsProvider"],
        "ttsVoice": agent["ttsVoice"],
    }


def test_concurrent_agent_updates_keep_unique_sequential_versions(tmp_path):
    repository = NexusRepository(Database(tmp_path / "concurrent-agents.db"))
    original = repository.get_agent()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda index: repository.update_agent(original["id"], agent_payload(original, f"Concurrent Agent {index}")),
            (1, 2),
        ))
    assert sorted(result["version"] for result in results) == [2, 3]
    assert repository.list_agent_versions(original["id"])[0]["version"] == 3


def test_concurrent_turns_preserve_sequence_and_session_state(tmp_path):
    repository = NexusRepository(Database(tmp_path / "concurrent-turns.db"))
    session = repository.create_session("mma-nexus-intake")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda content: repository.add_turn(session["id"], content),
            ("maybe one", "maybe two"),
        ))
    assert sorted(result["turnCount"] for result in results) == [1, 2]
    restored = repository.get_session(session["id"])
    assert restored["turnCount"] == 2
    assert [turn["seq"] for turn in restored["turns"]] == [1, 2, 3, 4, 5]
    assert restored["status"] == "active"
