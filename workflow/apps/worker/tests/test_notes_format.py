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

    def test_commit_entries_keep_full_message(self):
        push = _push(
            commits=[{"id": "a" * 40, "message": "subject\n\nPatch notes:\n- General: X."}]
        )
        entries = nf.commit_entries(push)
        assert entries[0]["message"].startswith("subject\n")
        assert "Patch notes:" in entries[0]["message"]

    def test_commit_entries_caps_at_20(self):
        push = _push(commits=[{"id": str(i), "message": f"change {i}"} for i in range(50)])
        assert len(nf.commit_entries(push)) == nf.MAX_COMMITS


class TestPatchNotesBlock:
    def test_block_lines_with_trailer_after(self):
        msg = (
            "havoc: rotate waves\n\n"
            "Body text.\n\n"
            "Patch notes:\n"
            "- Havoc: Waves rotate on every map.\n"
            "- All game modes: Rewards pay at the end screen.\n"
            "\n"
            "Co-Authored-By: Someone <x>"
        )
        assert nf.patch_note_lines(msg) == [
            "Havoc: Waves rotate on every map.",
            "All game modes: Rewards pay at the end screen.",
        ]

    def test_first_bullet_on_the_same_line(self):
        assert nf.patch_note_lines("x\n\nPatch notes: - Launcher: Self-updates.") == [
            "Launcher: Self-updates."
        ]
        assert nf.patch_note_lines("x\n\nPatch notes: Launcher: Self-updates.") == [
            "Launcher: Self-updates."
        ]

    def test_none_internal_is_an_empty_block(self):
        assert nf.patch_note_lines("x\n\nPatch notes: none (internal)") == []
        assert nf.patch_note_lines("x\n\nPatch Notes: None (Internal)") == []

    def test_missing_block_returns_none(self):
        assert nf.patch_note_lines("add feature\n\nbody") is None
        assert nf.patch_note_lines("") is None

    def test_block_ends_at_paragraph(self):
        msg = "x\n\nPatch notes:\n- General: G.\nA trailing paragraph."
        assert nf.patch_note_lines(msg) == ["General: G."]

    def test_wrapped_bullets_are_joined(self):
        # 2026-11-07's commit wrapped its first block line across three
        # lines; only the first line ever reached the model before, so the
        # published note was truncated. Indented follow lines continue the
        # previous bullet.
        msg = (
            "daily contracts pay GP\n\n"
            "Patch notes:\n"
            "- All modes: Claiming a finished daily contract now also gives 200 GP on\n"
            "  top of its credits. The contract card still shows only the credits.\n"
            "- New players start with 10000 GP.\n"
            "\n"
            "Co-Authored-By: Someone <x>"
        )
        assert nf.patch_note_lines(msg) == [
            "All modes: Claiming a finished daily contract now also gives 200 GP on top of its credits. The contract card still shows only the credits.",
            "New players start with 10000 GP.",
        ]

    def test_context_lines_are_dropped(self):
        # 2026-11-17's failure mode: the operator's block carried context
        # lines, the model rightly published nothing for them, and the
        # coverage gate failed the run. Context is dropped before the model
        # now, like "none (internal)" — real changes in the same block stay.
        msg = (
            "accounts and sign-in\n\n"
            "Patch notes:\n"
            "- All game modes: no change for players; accounts are created in the launcher only.\n"
            "- Admin panel: game logs tell a crash on exit from a crash during play.\n"
            "- Havoc: Waves rotate on every map.\n"
        )
        assert nf.patch_note_lines(msg) == ["Havoc: Waves rotate on every map."]

    def test_context_only_block_is_empty(self):
        # a block that is all context is an internal commit: the push
        # completes with "no player-facing changes" instead of failing
        msg = (
            "sign-in wording\n\n"
            "Patch notes:\n"
            "- All game modes: no change for players; sign-in is by account only.\n"
        )
        assert nf.patch_note_lines(msg) == []

    def test_no_change_words_mid_sentence_are_kept(self):
        # only a line that OPENS with "no change" declares context; a real
        # change that merely contains the words mid-sentence stays
        msg = "x\n\nPatch notes:\n- Launcher: You can no longer change your email in-game."
        assert nf.patch_note_lines(msg) == [
            "Launcher: You can no longer change your email in-game."
        ]

    def test_bare_no_change_line_without_prefix_is_dropped(self):
        msg = "x\n\nPatch notes:\n- no change for players; maintenance behind the scenes.\n"
        assert nf.patch_note_lines(msg) == []

    def test_dashless_block_lines_are_parsed(self):
        # 2026-11-18's push wrote its block lines without "-" bullets, plain
        # at column 0; the parser treated them as the block's end, so a live
        # player-facing change was silently dropped. A column-0 line that
        # names its mode or area before the first colon is a dash-less bullet.
        msg = (
            "onslaught: size the creep manager\n\n"
            "Body paragraph.\n\n"
            "Patch notes:\n"
            "Onslaught: team 1 no longer loses a fighter every 2 seconds for nothing.\n"
            "All game modes: players get their team assigned the moment they join.\n"
            "\n"
            "Co-Authored-By: Someone <x>"
        )
        assert nf.patch_note_lines(msg) == [
            "Onslaught: team 1 no longer loses a fighter every 2 seconds for nothing.",
            "All game modes: players get their team assigned the moment they join.",
        ]

    def test_dashless_and_dashed_lines_can_mix(self):
        msg = (
            "x\n\n"
            "Patch notes:\n"
            "- Havoc: Waves rotate on every map.\n"
            "Launcher: Self-updates.\n"
            "- Onslaught: Creeps hold their cap.\n"
        )
        assert nf.patch_note_lines(msg) == [
            "Havoc: Waves rotate on every map.",
            "Launcher: Self-updates.",
            "Onslaught: Creeps hold their cap.",
        ]

    def test_dashless_context_lines_are_dropped(self):
        # the context filter applies to dash-less lines exactly like dashed
        # ones: an operator-side prefix still declares context
        msg = (
            "x\n\n"
            "Patch notes:\n"
            "Admin panel: game logs tell a crash on exit from a crash during play.\n"
            "All game modes: no change for players; sign-in is by account only.\n"
        )
        assert nf.patch_note_lines(msg) == []

    def test_bare_prose_without_colon_still_ends_the_block(self):
        # a dash-less line must name its area before the colon to count as a
        # bullet; plain prose at column 0 (no colon) still ends the block
        msg = "x\n\nPatch notes:\nOnslaught: Fixed.\nA trailing paragraph without colon."
        assert nf.patch_note_lines(msg) == ["Onslaught: Fixed."]


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

    def test_pr_url_number(self):
        assert nf.pr_url_number("https://github.com/o/r/pull/42") == 42
        assert nf.pr_url_number("https://github.com/o/r/pull/999/files") == 999
        # no PR number in the URL: auto-merge is skipped, not failed
        assert nf.pr_url_number("https://github.com/o/r/issues/7") is None
        assert nf.pr_url_number("created") is None
        assert nf.pr_url_number("") is None


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

    def test_parse_canonicalizes_known_titles(self):
        text = json.dumps(
            {
                "sections": [
                    {"title": "escalation", "bullets": ["B."]},
                    {"title": "all game modes", "bullets": ["A."]},
                    {"title": "Fresh unknown area", "bullets": ["U."]},
                ]
            }
        )
        titles = [s["title"] for s in nf.parse_llm_batch(text)]
        # parse canonicalizes titles but keeps the model's order; sorting is sort_sections' job
        assert titles == [
            "Escalation",
            "All game modes",
            "Fresh unknown area",
        ]

    def test_prompt_embeds_blocks_subjects_and_format(self):
        prompt = nf.build_prompt(
            "2026-11-05",
            ["Conquest: Points show as your team's territory."],
            ["fix dreadnought hp"],
        )
        assert "2026-11-05" in prompt
        assert "- Conquest: Points show as your team's territory." in prompt
        assert "- fix dreadnought hp" in prompt
        assert "Escalation" in prompt
        assert "All game modes" in prompt
        assert "Daily contracts" in prompt
        assert "Social" in prompt
        assert "Ryugu Haven" in prompt
        assert "strict JSON" in prompt
        # mapping guidance, and no known-issues closer (the site links the tracker)
        assert "actually affects" in prompt
        assert "please report" not in prompt
        assert "Known issues / please report" not in prompt
        # the coverage rule: every block line's change must survive into the batch
        assert "MUST reach the batch" in prompt
        assert "never drop a line" in prompt
        assert "A dropped block line fails the run" in prompt
        # the dedup rule: one change is published once, never repeated per mode
        assert "publish each change ONCE" in prompt.lower() or "Publish each change ONCE" in prompt
        assert "never the same sentence repeated" in prompt
        # the style rules: patch notes, not prose blobs
        assert "ONE sentence" in prompt
        assert "never more than 25" in prompt
        assert "is a blob, not a patch note" in prompt
        assert "never appear in two sections" in prompt

    def test_sort_sections_orders_per_skill(self):
        sections = [
            {"title": "General", "bullets": ["g"]},
            {"title": "Launcher", "bullets": ["l"]},
            {"title": "Conquest", "bullets": ["c"]},
            {"title": "Unknown thing", "bullets": ["u"]},
            {"title": "All game modes", "bullets": ["a"]},
            {"title": "Daily contracts", "bullets": ["d"]},
        ]
        titles = [s["title"] for s in nf.sort_sections(sections)]
        assert titles == [
            "Conquest",
            "All game modes",
            "Daily contracts",  # the progression system sits between cross-mode and out-of-match areas
            "Launcher",
            "General",
            "Unknown thing",
        ]


class TestBlockCoverage:
    def test_present_sections_pass(self):
        sections = [
            {"title": "Havoc", "bullets": ["Waves rotate."]},
            {"title": "All game modes", "bullets": ["Rewards at end screen."]},
        ]
        lines = ["Havoc: Waves rotate on every map.", "All game modes: Rewards pay at the end screen."]
        assert nf.missing_block_sections(sections, lines) == []
        nf.validate_block_coverage(sections, lines)  # no raise

    def test_dropped_section_is_reported(self):
        sections = [{"title": "Proving Grounds", "bullets": ["P."]}]
        lines = ["Proving Grounds: P.", "Escalation: E."]
        assert nf.missing_block_sections(sections, lines) == ["Escalation"]
        with pytest.raises(ValueError) as exc:
            nf.validate_block_coverage(sections, lines)
        assert "Escalation" in str(exc.value)

    def test_every_missing_section_named_once(self):
        sections = [{"title": "General", "bullets": ["G."]}]
        lines = [
            "Havoc: A.",
            "Havoc: B.",
            "Escalation: C.",
        ]
        assert nf.missing_block_sections(sections, lines) == ["Havoc", "Escalation"]

    def test_unknown_prefix_and_colonless_lines_are_the_models_call(self):
        sections = [{"title": "General", "bullets": ["G."]}]
        # "Some new area" is not a known title, and a line without a colon names
        # no section at all: placement is the model's decision, never a failure
        assert nf.missing_block_sections(sections, ["Some new area: X.", "no prefix at all"]) == []

    def test_prefix_is_canonicalized(self):
        assert nf.missing_block_sections([], ["all game modes: X."]) == ["All game modes"]
        assert nf.missing_block_sections([], ["escalation: X."]) == ["Escalation"]
        # an alias the skill does not list (like "TDM") is not a known title either
        assert nf.missing_block_sections([], ["TDM: X."]) == []

    def test_same_change_under_several_modes_is_one_change(self):
        # 2026-11-15's failure mode: the operator wrote the SAME join-in-progress
        # line for Team Deathmatch, Onslaught and Proving Grounds, and the batch
        # repeated the sentence three times. The gate treats the group as one
        # change: one bullet under any named mode passes...
        lines = [
            "Team Deathmatch: Queue in the first 3 minutes of a match and you join it.",
            "Onslaught: Queue in the first 3 minutes of a match and you join it.",
            "Proving Grounds: Queue in the first 3 minutes of a match and you join it.",
        ]
        one_mode = [
            {
                "title": "Team Deathmatch",
                "bullets": ["Queue in the first 3 minutes of a match and you join it."],
            }
        ]
        assert nf.missing_block_sections(one_mode, lines) == []
        nf.validate_block_coverage(one_mode, lines)  # no raise
        # ...and so does the cross-mode section the dedup rule asks the model for
        agm = [
            {
                "title": "All game modes",
                "bullets": ["Queue in the first 3 minutes of a match and you join it."],
            }
        ]
        assert nf.missing_block_sections(agm, lines) == []
        assert nf.missing_block_lines(agm, lines) == []
        nf.validate_block_coverage(agm, lines)  # no raise

    def test_repeated_change_still_needs_some_section(self):
        # covered nowhere at all (no named mode, no cross-mode section): the
        # whole group fails, and every title it named is reported
        lines = ["Havoc: Waves rotate.", "Onslaught: Waves rotate."]
        sections = [{"title": "General", "bullets": ["Waves rotate."]}]
        assert nf.missing_block_sections(sections, lines) == ["Havoc", "Onslaught"]
        with pytest.raises(ValueError) as exc:
            nf.validate_block_coverage(sections, lines)
        assert "Havoc" in str(exc.value)

    def test_single_mode_line_is_not_excused_by_all_game_modes(self):
        # the cross-mode section only covers a change the block named for
        # SEVERAL modes; one mode's line still demands its own section
        sections = [{"title": "All game modes", "bullets": ["Waves rotate."]}]
        line = "Havoc: Waves rotate on every map."
        assert nf.missing_block_sections(sections, [line]) == ["Havoc"]
        with pytest.raises(ValueError):
            nf.validate_block_coverage(sections, [line])


class TestBlockContentCoverage:
    """The content half of the gate: unprefixed or unknown-prefixed lines."""

    def test_dropped_unprefixed_line_is_reported(self):
        # 2026-11-07's second failure: "New players start with 10000 GP."
        # had no prefix, so the section half of the gate could not see it.
        sections = [
            {
                "title": "Daily contracts",
                "bullets": ["Claiming a finished daily contract now also gives 200 GP."],
            }
        ]
        lines = [
            "All modes: Claiming a finished daily contract now also gives 200 GP.",
            "New players start with 10000 GP.",
        ]
        assert nf.missing_block_lines(sections, lines) == ["New players start with 10000 GP."]
        with pytest.raises(ValueError) as exc:
            nf.validate_block_coverage(sections, lines)
        assert "10000" in str(exc.value)

    def test_reworded_but_recognizable_line_passes(self):
        sections = [{"title": "General", "bullets": ["Fresh accounts begin with 10000 GP."]}]
        line = "New players start with 10000 GP."
        assert nf.missing_block_lines(sections, [line]) == []
        nf.validate_block_coverage(sections, [line])  # no raise

    def test_unknown_prefix_line_covered_by_content(self):
        # "All modes" is not a section title, so the line passes on content:
        # the batch keeps the change recognizable even under another title.
        sections = [
            {
                "title": "Daily contracts",
                "bullets": ["Claiming a finished daily contract now also gives 200 GP on top of its credits."],
            }
        ]
        line = "All modes: Claiming a finished daily contract now also gives 200 GP on top of its credits."
        assert nf.missing_block_lines(sections, [line]) == []
        nf.validate_block_coverage(sections, [line])  # no raise

    def test_known_prefix_still_requires_its_section(self):
        # content present under the wrong section must not excuse the gate:
        # the author named the section on purpose
        sections = [{"title": "Havoc", "bullets": ["Escalation returns to the queues."]}]
        line = "Escalation: Escalation returns to the queues."
        assert nf.missing_block_lines(sections, [line]) == [line]
        with pytest.raises(ValueError) as exc:
            nf.validate_block_coverage(sections, [line])
        assert "Escalation" in str(exc.value)

    def test_line_without_distinctive_tokens_never_fails(self):
        # "GP is back." has no number and no five-letter word: nothing to
        # recognize, so the model's placement is trusted rather than guessed
        sections = [{"title": "General", "bullets": ["Completely different change."]}]
        assert nf.missing_block_lines(sections, ["GP is back."]) == []


class TestCollapseDuplicateBullets:
    """The deterministic backstop for 2026-11-15's repeated bullets."""

    def test_repeats_collapse_into_all_game_modes(self):
        dup = "Queue in the first 3 minutes of a match and you join it."
        sections = [
            {"title": "Team Deathmatch", "bullets": [dup]},
            {"title": "Onslaught", "bullets": [dup]},
            {"title": "Proving Grounds", "bullets": [dup]},
            {"title": "Launcher", "bullets": ["Tray icon."]},
        ]
        # order is preserved and the cross-mode section is appended; the
        # workflow path sorts sections after collapsing
        assert nf.collapse_duplicate_bullets(sections) == [
            {"title": "Launcher", "bullets": ["Tray icon."]},
            {"title": "All game modes", "bullets": [dup]},
        ]
        sorted_out = nf.sort_sections(nf.collapse_duplicate_bullets(sections))
        assert [s["title"] for s in sorted_out] == ["All game modes", "Launcher"]

    def test_copy_already_in_all_game_modes_wins(self):
        dup = "Matches are 5v5 again."
        sections = [
            {"title": "All game modes", "bullets": [dup, "Other change."]},
            {"title": "Onslaught", "bullets": [dup]},
        ]
        assert nf.collapse_duplicate_bullets(sections) == [
            {"title": "All game modes", "bullets": [dup, "Other change."]},
        ]

    def test_unique_bullets_untouched(self):
        sections = [
            {"title": "Havoc", "bullets": ["Waves rotate."]},
            {"title": "Onslaught", "bullets": ["Command ships fire."]},
        ]
        assert nf.collapse_duplicate_bullets(sections) == sections

    def test_markdown_noise_is_ignored_when_matching(self):
        # bold markers must not hide an identical change
        sections = [
            {"title": "Havoc", "bullets": ["Wave mode is here."]},
            {"title": "General", "bullets": ["**Wave mode** is here."]},
        ]
        assert nf.collapse_duplicate_bullets(sections) == [
            {"title": "All game modes", "bullets": ["Wave mode is here."]},
        ]


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
    assert "`abc1234` add map" in body
    assert "2026-11-05" in body
    assert "revival-patch-notes" in body
    # the body must tell the reviewer what happens to the PR
    assert "squash-merges this PR automatically" in body
