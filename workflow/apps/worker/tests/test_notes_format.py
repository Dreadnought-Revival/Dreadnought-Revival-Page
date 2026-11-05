"""Tests for the stdlib-only patch-notes helpers. No SDK imports required."""

import json

import pytest

from worker.workflows import notes_format as nf


def _push(commits=None, repo="Dreadnought-Revival-server", ref="refs/heads/master", default="master"):
    return {
        "repository": {"name": repo, "default_branch": default},
        "ref": ref,
        "commits": commits if commits is not None else [],
    }


class TestPushPayload:
    def test_repo_name(self):
        assert nf.repo_name(_push()) == "Dreadnought-Revival-server"
        assert nf.repo_name({}) == ""

    def test_default_branch_ref(self):
        assert nf.default_branch_ref(_push()) == "refs/heads/master"
        assert nf.default_branch_ref({"repository": {}}) is None

    def test_commit_entries_skip_merges_and_empties(self):
        push = _push(
            commits=[
                {"id": "a" * 40, "message": "add havoc rotation\n\nlong body"},
                {"id": "b" * 40, "message": "Merge pull request #12 from someone"},
                {"id": "c" * 40, "message": "  "},
                {"id": "d" * 40, "message": "fix corvette spread"},
            ]
        )
        entries = nf.commit_entries(push)
        assert [e["subject"] for e in entries] == ["add havoc rotation", "fix corvette spread"]
        assert entries[0]["sha"] == "a" * 40

    def test_commit_entries_caps_at_20(self):
        push = _push(commits=[{"id": str(i), "message": f"change {i}"} for i in range(50)])
        assert len(nf.commit_entries(push)) == nf.MAX_COMMITS


class TestConnectorShapes:
    def test_extract_file_text_mcp_shape(self):
        result = ["headers", {"resource": {"uri": "repo://x", "text": '{"notes": []}'}}]
        assert nf.extract_file_text(result) == '{"notes": []}'

    def test_extract_file_text_bare_resource(self):
        assert nf.extract_file_text({"resource": {"text": "plain"}}) == "plain"

    def test_extract_file_text_plain_string(self):
        assert nf.extract_file_text("raw") == "raw"

    def test_extract_pr_url(self):
        assert nf.extract_pr_url({"url": "https://github.com/x"}) == "https://github.com/x"
        assert nf.extract_pr_url(["h", {"url": "https://github.com/y"}]) == "https://github.com/y"
        assert nf.extract_pr_url({}) == "created"


class TestLlmBatch:
    def test_parse_plain_json(self):
        text = json.dumps({"sections": [{"title": "General", "bullets": ["Fixed X."]}]})
        assert nf.parse_llm_batch(text) == [{"title": "General", "bullets": ["Fixed X."]}]

    def test_parse_fenced_json(self):
        text = '```json\n{"sections": [{"title": "Havoc", "bullets": ["Added **Ravager**."]}]}\n```'
        assert nf.parse_llm_batch(text)[0]["title"] == "Havoc"

    def test_parse_rejects_missing_object(self):
        with pytest.raises(ValueError):
            nf.parse_llm_batch("no json here")

    def test_parse_rejects_no_sections(self):
        with pytest.raises(ValueError):
            nf.parse_llm_batch('{"foo": 1}')

    def test_parse_drops_empty_bullets(self):
        sections = nf.parse_llm_batch('{"sections": [{"title": "General", "bullets": ["", "ok"]}, {"title": "X"}]}')
        assert sections == [{"title": "General", "bullets": ["ok"]}]

    def test_prompt_embeds_subjects_and_format(self):
        prompt = nf.build_prompt("2026-11-05", ["add new map", "fix dreadnought hp"])
        assert "2026-11-05" in prompt
        assert "- add new map" in prompt
        assert "**bold**" in prompt
        assert "Known issues / please report" in prompt
        assert "strict JSON" in prompt


class TestMergeBatch:
    def test_new_day_prepends(self):
        data = {"generated_at": None, "notes": [{"date": "2026-10-02", "sections": []}]}
        out = nf.merge_batch(data, "2026-11-05", [{"title": "General", "bullets": ["B."]}], "now")
        assert out["notes"][0]["date"] == "2026-11-05"
        assert out["notes"][1]["date"] == "2026-10-02"
        assert out["generated_at"] == "now"

    def test_same_day_merges_and_dedupes(self):
        data = {
            "generated_at": None,
            "notes": [
                {
                    "date": "2026-11-05",
                    "sections": [{"title": "General", "bullets": ["B1."]}, {"title": "Havoc", "bullets": ["H."]}],
                }
            ],
        }
        out = nf.merge_batch(
            data,
            "2026-11-05",
            [
                {"title": "general", "bullets": ["B1.", "B2."]},
                {"title": "Market", "bullets": ["M."]},
            ],
            "now2",
        )
        entry = out["notes"][0]
        assert len(entry["sections"]) == 3
        general = next(s for s in entry["sections"] if s["title"] == "General")
        assert general["bullets"] == ["B1.", "B2."]
        assert out["generated_at"] == "now2"

    def test_render_roundtrip(self):
        data = nf.merge_batch({}, "2026-11-05", [{"title": "General", "bullets": ["B."]}], "now")
        rendered = nf.render_notes_json(data)
        assert json.loads(rendered)["notes"][0]["date"] == "2026-11-05"
        assert rendered.endswith("\n")


def test_pr_body_lists_commits():
    body = nf.build_pr_body("2026-11-05", [{"sha": "abc1234", "subject": "add map"}])
    assert "`abc123` add map" in body
    assert "2026-11-05" in body
    assert "revival-patch-notes" in body
