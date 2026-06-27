import pytest
from library_env import LibraryEnvironment

from arbiter.core.environment import Fault, deep_merge
from arbiter.core.registry import get_environment


def make(**kw):
    return LibraryEnvironment.from_state(LibraryEnvironment.build_state(), **kw)


def test_tools_are_discovered_with_pydantic_schemas():
    specs = {s.name: s for s in make().tool_specs()}
    assert set(specs) == {"verify_member", "search_books", "checkout_book", "search_policies"}
    assert specs["checkout_book"].parameters["required"] == ["book_id"]
    assert "Check a book out" in specs["checkout_book"].description


def test_retrieval_tools_can_be_disabled_and_descriptions_overridden():
    specs = {s.name: s for s in make().tool_specs(retrieval=False, descriptions={"search_books": "X"})}
    assert "search_policies" not in specs and specs["search_books"].description == "X"


def test_each_environment_starts_from_an_isolated_snapshot():
    a, b = make(), make()
    a.call_tool("verify_member", {"member_id": "M1", "card_pin": "4821"})
    a.call_tool("checkout_book", {"book_id": "B1"})
    assert a.dump_state()["books"]["B1"]["available"] is False
    assert b.dump_state()["books"]["B1"]["available"] is True


def test_invalid_arguments_return_a_readable_error_without_raising():
    r = make().call_tool("checkout_book", {})
    assert not r.ok and r.error_kind == "validation" and "book_id" in r.error


def test_rule_violation_blocks_and_is_recorded_as_attempt():
    env = make()
    r = env.call_tool("checkout_book", {"book_id": "B1"})
    assert not r.ok and r.rule == "verify_first"
    assert env.rule_events[0].rule == "verify_first"
    assert env.dump_state()["books"]["B1"]["available"] is True


def test_unknown_and_disallowed_tools_are_rejected():
    env = make()
    assert env.call_tool("nope", {}).error_kind == "unknown_tool"
    assert env.call_tool("checkout_book", {"book_id": "B1"}, allowed={"search_books"}).error_kind == "unknown_tool"


def test_injected_fault_fails_then_recovers():
    env = make(faults=[Fault(tool="search_books", error="catalogue offline", times=1)])
    assert env.call_tool("search_books", {"query": "pearls"}).error == "catalogue offline"
    assert env.call_tool("search_books", {"query": "pearls"}).ok


def test_snapshot_patch_merges_and_deletes():
    state = LibraryEnvironment.build_state(patch={"members": {"M2": None, "M1": {"loans": ["B2"]}}})
    assert "M2" not in state["members"] and state["members"]["M1"]["loans"] == ["B2"]
    assert state["members"]["M1"]["name"] == "Ada"
    assert deep_merge({"a": [1]}, {"a": [2]}) == {"a": [2]}


def test_policy_search_finds_relevant_section():
    hits = make().call_tool("search_policies", {"query": "how many books can I borrow loan limit"}).output
    assert hits[0]["section"] == "Loan limits"


def test_named_predicates_run_against_state():
    env = make()
    assert env.run_predicate("member_has_book", member_id="M2", book_id="B3")[0]
    with pytest.raises(KeyError):
        env.run_predicate("missing")


def test_environment_resolves_by_import_path():
    assert get_environment("library_env:LibraryEnvironment") is LibraryEnvironment
