from pathlib import Path

import pytest
from library_env import LibraryEnvironment

from arbiter.scenarios.generate import generate, render

ROOT = Path(__file__).parent / "fixtures" / "library_scenarios"


def test_render_requires_every_placeholder():
    assert render("a {{x}} b", {"x": 1}) == "a 1 b"
    with pytest.raises(KeyError):
        render("{{missing}}", {})


def test_generate_expands_validates_and_dedupes():
    accepted, rejected = generate(LibraryEnvironment, ROOT, existing_ids=set())
    ids = [a["id"] for a in accepted]
    assert ids == ["lib-gen-a", "lib-gen-b"]
    assert any("duplicate" in r for r in rejected)
    assert all(a["generated_from"] == "library-checkout" for a in accepted)


def test_generate_skips_existing_ids():
    accepted, rejected = generate(LibraryEnvironment, ROOT, existing_ids={"lib-gen-a"})
    assert [a["id"] for a in accepted] == ["lib-gen-b"]
    assert any("already exists" in r for r in rejected)
