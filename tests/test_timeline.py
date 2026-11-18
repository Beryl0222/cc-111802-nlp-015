import json
import tempfile
import unittest
from pathlib import Path

from nlp_lesson_event_timeline.timeline_store import TimelineStore
from nlp_lesson_event_timeline.timeline_workflow import TimelineWorkflow

CH1 = "第一章 禁烟"
CH2 = "第二章 战事"


def make_workflow(directory):
    return TimelineWorkflow(TimelineStore(Path(directory) / "timeline.json"))


def event(event_id, chapter=CH1, revision=1, participants=()):
    return {"event_id": event_id, "summary": f"{event_id} 摘要", "chapter": chapter,
            "revision": revision,
            "participants": [{"person": person, "role": role} for person, role in participants]}


def explicit(clue_id, event_id, day, chapter=CH1, revision=1):
    return {"clue_id": clue_id, "event_id": event_id, "kind": "explicit",
            "expression": f"原文日期 {day}", "chapter": chapter, "date": day,
            "revision": revision}


def relative(clue_id, event_id, anchor, offset=1, chapter=CH1, revision=1):
    return {"clue_id": clue_id, "event_id": event_id, "kind": "relative",
            "expression": "翌日" if offset == 1 else f"{offset}日后", "chapter": chapter,
            "anchor_event_id": anchor, "offset_days": offset, "revision": revision}


def order_of(view):
    return [entry["event_id"] for entry in view["sequence"]]


class CorrectionTests(unittest.TestCase):
    def test_time_correction_updates_order_and_keeps_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = make_workflow(directory)
            workflow.register_event(event("evt-a", participants=(("林则徐", "主持"),)))
            workflow.register_event(event("evt-b"))
            workflow.register_clue(explicit("clue-a", "evt-a", "1839-03-10"))
            workflow.register_clue(explicit("clue-b", "evt-b", "1839-03-12"))
            handout = workflow.issue_handout("第一课时时间线", handout_id="lesson-1")

            first = workflow.current_timeline()
            self.assertEqual(order_of(first), ["evt-a", "evt-b"])
            self.assertEqual(first["sequence"][0]["step_to_next"], "explicit")
            self.assertEqual(first["sequence"][0]["participants"],
                             [{"person": "林则徐", "role": "主持"}])

            # 教师更正时间：evt-a 实际晚于 evt-b
            workflow.register_clue(explicit("clue-a", "evt-a", "1839-03-15", revision=2))
            corrected = workflow.current_timeline()
            self.assertEqual(order_of(corrected), ["evt-b", "evt-a"])
            self.assertEqual(corrected["version"], first["version"] + 1)

            # 已发放的课堂材料仍引用旧版本，新旧版本都可查询
            pinned = workflow.handout_view("lesson-1")
            self.assertEqual(pinned["handout"]["timeline_version"], handout["timeline_version"])
            self.assertEqual(order_of(pinned), ["evt-a", "evt-b"])
            self.assertEqual(order_of(workflow.timeline_version(first["version"])), ["evt-a", "evt-b"])

            # 排序变化依据可查：日期更正 + 先后翻转，并指向起因线索
            diff = workflow.version_diff(first["version"], corrected["version"])
            kinds = [change["kind"] for change in diff["changes"]]
            self.assertIn("date_corrected", kinds)
            self.assertIn("reordered", kinds)
            self.assertEqual(diff["cause"]["clue_id"], "clue-a")
            reordered = next(c for c in diff["changes"] if c["kind"] == "reordered")
            self.assertEqual(reordered["events"], ["evt-a", "evt-b"])

    def test_no_version_created_when_nothing_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = make_workflow(directory)
            workflow.register_event(event("evt-a"))
            workflow.register_clue(explicit("clue-a", "evt-a", "1839-03-10"))
            versions = len(workflow.list_versions())
            workflow.register_clue(explicit("clue-a", "evt-a", "1839-03-10"))  # 幂等重放
            workflow.register_event(event("evt-a"))  # 幂等重放
            self.assertEqual(len(workflow.list_versions()), versions)


class BasisTests(unittest.TestCase):
    def test_explicit_inferred_and_ambiguous_steps_are_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = make_workflow(directory)
            for event_id in ("evt-a", "evt-b", "evt-c"):
                workflow.register_event(event(event_id))
            workflow.register_clue(explicit("clue-a", "evt-a", "1839-03-10"))
            workflow.register_clue(relative("clue-b", "evt-b", "evt-a"))  # 翌日 -> 推断
            workflow.register_clue(explicit("clue-c", "evt-c", "1839-03-11"))  # 与 evt-b 同日

            view = workflow.current_timeline()
            self.assertEqual(order_of(view), ["evt-a", "evt-b", "evt-c"])
            self.assertEqual(view["sequence"][0]["step_to_next"], "inferred")
            self.assertEqual(view["sequence"][1]["date_kind"], "inferred")
            self.assertEqual(view["sequence"][1]["date"], "1839-03-11")
            self.assertEqual(view["sequence"][1]["step_to_next"], "ambiguous")
            kinds = {item["kind"] for item in view["review_items"]}
            self.assertIn("same_day_order", kinds)

    def test_relative_chain_resolves_within_chapter(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = make_workflow(directory)
            for event_id in ("evt-a", "evt-b", "evt-c"):
                workflow.register_event(event(event_id))
            workflow.register_clue(explicit("clue-a", "evt-a", "1839-03-10"))
            workflow.register_clue(relative("clue-b", "evt-b", "evt-a"))
            workflow.register_clue(relative("clue-c", "evt-c", "evt-b"))
            dates = {entry["event_id"]: entry["date"]
                     for entry in workflow.current_timeline()["sequence"]}
            self.assertEqual(dates["evt-c"], "1839-03-12")


class ChapterScopeTests(unittest.TestCase):
    def test_relative_time_does_not_chain_across_chapters(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = make_workflow(directory)
            workflow.register_event(event("evt-a", chapter=CH1))
            workflow.register_event(event("evt-d", chapter=CH2))
            workflow.register_clue(explicit("clue-a", "evt-a", "1839-06-03", chapter=CH1))
            # 第二章的“翌日”不得挂到第一章的事件上
            workflow.register_clue(relative("clue-d", "evt-d", "evt-a", chapter=CH2))

            view = workflow.current_timeline()
            self.assertEqual(order_of(view), ["evt-a"])
            self.assertEqual([entry["event_id"] for entry in view["undated"]], ["evt-d"])
            cross = [item for item in view["review_items"]
                     if item["kind"] == "cross_chapter_relative"]
            self.assertEqual(len(cross), 1)
            self.assertEqual(cross[0]["clue_ids"], ["clue-d"])
            self.assertEqual(cross[0]["status"], "pending")

    def test_chapter_filter_keeps_basis_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = make_workflow(directory)
            workflow.register_event(event("evt-a", chapter=CH1))
            workflow.register_event(event("evt-b", chapter=CH1))
            workflow.register_event(event("evt-c", chapter=CH2))
            workflow.register_clue(explicit("clue-a", "evt-a", "1839-03-10", chapter=CH1))
            workflow.register_clue(relative("clue-b", "evt-b", "evt-a", chapter=CH1))
            workflow.register_clue(explicit("clue-c", "evt-c", "1839-03-11", chapter=CH2))
            view = workflow.current_timeline(chapter=CH1)
            self.assertEqual(order_of(view), ["evt-a", "evt-b"])
            self.assertEqual(view["sequence"][0]["step_to_next"], "inferred")


class WithdrawTests(unittest.TestCase):
    def test_withdraw_clue_keeps_event_but_marks_it_undated(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = make_workflow(directory)
            workflow.register_event(event("evt-a"))
            workflow.register_event(event("evt-b"))
            workflow.register_clue(explicit("clue-a", "evt-a", "1839-03-10"))
            workflow.register_clue(explicit("clue-b", "evt-b", "1839-03-12"))
            before = workflow.current_timeline()["version"]

            workflow.withdraw_clue("clue-b", revision=2)
            view = workflow.current_timeline()
            self.assertEqual(order_of(view), ["evt-a"])
            # 事件没有被当作没有发生：仍出现在查询结果中，只是时间未定
            self.assertEqual([entry["event_id"] for entry in view["undated"]], ["evt-b"])
            self.assertEqual(view["undated"][0]["summary"], "evt-b 摘要")
            self.assertEqual(view["undated"][0]["date_kind"], "none")

            diff = workflow.version_diff(before, view["version"])
            self.assertIn("event_undated", [change["kind"] for change in diff["changes"]])
            self.assertIn("order_unknown", {item["kind"] for item in view["review_items"]})

            # 线索历史保留，撤回状态可查
            clues = workflow.list_clues(event_id="evt-b")
            self.assertEqual(clues[0]["status"], "withdrawn")
            self.assertEqual(workflow.list_clues(event_id="evt-b", include_withdrawn=False), [])

            # 重新登记时间依据后事件回到排序中
            workflow.register_clue(explicit("clue-b2", "evt-b", "1839-03-12"))
            self.assertEqual(order_of(workflow.current_timeline()), ["evt-a", "evt-b"])

    def test_withdraw_unknown_or_repeated_clue_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = make_workflow(directory)
            workflow.register_event(event("evt-a"))
            workflow.register_clue(explicit("clue-a", "evt-a", "1839-03-10"))
            with self.assertRaises(ValueError):
                workflow.withdraw_clue("missing", revision=2)
            with self.assertRaises(ValueError):
                workflow.withdraw_clue("clue-a", revision=1)  # 修订号必须更大
            workflow.withdraw_clue("clue-a", revision=2)
            with self.assertRaises(ValueError):
                workflow.withdraw_clue("clue-a", revision=3)  # 已撤回


class ReviewTests(unittest.TestCase):
    def test_unconfirmable_pairs_stay_pending_until_evidence_arrives(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = make_workflow(directory)
            workflow.register_event(event("evt-a"))
            workflow.register_event(event("evt-e"))
            workflow.register_clue(explicit("clue-a", "evt-a", "1839-03-10"))
            queue = workflow.review_queue()
            pending = [item for item in queue["items"] if item["kind"] == "order_unknown"]
            self.assertEqual(pending[0]["event_ids"], ["evt-a", "evt-e"])
            self.assertEqual(pending[0]["status"], "pending")

            before = queue["version"]
            workflow.register_clue(explicit("clue-e", "evt-e", "1839-03-20"))
            queue = workflow.review_queue()
            self.assertEqual([item for item in queue["items"]
                              if item["kind"] == "order_unknown"], [])
            diff = workflow.version_diff(before, queue["version"])
            self.assertIn("review_resolved", [change["kind"] for change in diff["changes"]])

    def test_conflicting_explicit_dates_go_to_review(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = make_workflow(directory)
            workflow.register_event(event("evt-a"))
            workflow.register_clue(explicit("clue-a1", "evt-a", "1839-03-10"))
            workflow.register_clue(explicit("clue-a2", "evt-a", "1839-03-11"))
            view = workflow.current_timeline()
            self.assertEqual([entry["event_id"] for entry in view["undated"]], ["evt-a"])
            self.assertIn("explicit_conflict",
                          {item["kind"] for item in view["review_items"]})


class ValidationTests(unittest.TestCase):
    def test_invalid_clue_is_rejected_without_partial_write(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TimelineStore(Path(directory) / "timeline.json")
            workflow = TimelineWorkflow(store)
            workflow.register_event(event("evt-a"))
            with self.assertRaises(ValueError):
                workflow.register_clue(explicit("clue-x", "evt-missing", "1839-03-10"))
            with self.assertRaises(ValueError):
                workflow.register_clue(explicit("clue-y", "evt-a", "不是日期"))
            with self.assertRaises(ValueError):
                workflow.register_clue(relative("clue-z", "evt-a", ""))
            self.assertEqual(store.read()["clues"], [])

    def test_revision_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = make_workflow(directory)
            workflow.register_event(event("evt-a"))
            workflow.register_clue(explicit("clue-a", "evt-a", "1839-03-10"))
            with self.assertRaises(ValueError):
                workflow.register_clue(explicit("clue-a", "evt-a", "1839-03-11"))  # 同号不同内容
            workflow.register_clue(explicit("clue-a", "evt-a", "1839-03-11", revision=2))
            with self.assertRaises(ValueError):
                workflow.register_clue(explicit("clue-a", "evt-a", "1839-03-12", revision=2))
            with self.assertRaises(ValueError):
                workflow.register_event(event("evt-a", revision=1,
                                              participants=(("林则徐", "主持"),)))  # 同号不同内容

    def test_bundle_ingest_is_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TimelineStore(Path(directory) / "timeline.json")
            workflow = TimelineWorkflow(store)
            bad = {"events": [event("evt-a")],
                   "clues": [explicit("clue-x", "evt-missing", "1839-03-10")]}
            with self.assertRaises(ValueError):
                workflow.ingest_bundle(bad)
            self.assertEqual(store.read()["events"], [])
            self.assertEqual(store.read()["versions"], [])


class FixtureTests(unittest.TestCase):
    def test_fixture_ingest_is_idempotent_and_scoped(self):
        fixture = json.loads(Path("fixtures/timeline.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            workflow = make_workflow(directory)
            first = workflow.ingest_bundle(fixture)
            second = workflow.ingest_bundle(fixture)
            self.assertEqual(first["version"], second["version"])
            self.assertEqual(len(workflow.list_versions()), 1)

            view = workflow.current_timeline()
            self.assertEqual(order_of(view), [
                "evt-arrive-guangzhou", "evt-seize-opium",
                "evt-humen-destroy", "evt-dinghai-fall",
            ])
            # 第二章的“翌日”没有串到第一章：英军北上时间未定，进入复核
            undated = {entry["event_id"] for entry in view["undated"]}
            self.assertEqual(undated, {"evt-british-north", "evt-negotiation"})
            kinds = {item["kind"] for item in view["review_items"]}
            self.assertIn("cross_chapter_relative", kinds)
            self.assertIn("order_unknown", kinds)
            # 参与者随查询结果返回
            seize = view["sequence"][1]
            self.assertEqual(seize["date"], "1839-03-11")
            self.assertEqual(seize["date_kind"], "inferred")
            self.assertEqual([p["person"] for p in seize["participants"]], ["林则徐", "义律"])

    def test_fixture_correction_flow(self):
        fixture = json.loads(Path("fixtures/timeline.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            workflow = make_workflow(directory)
            workflow.ingest_bundle(fixture)
            handout = workflow.issue_handout("鸦片战争时间线")
            # 更正定海陷落日期，使其早于林则徐抵达广州
            workflow.register_clue(explicit("clue-dinghai-date", "evt-dinghai-fall",
                                            "1839-03-01", chapter=CH2, revision=2))
            current = workflow.current_timeline()
            self.assertEqual(order_of(current)[0], "evt-dinghai-fall")
            pinned = workflow.handout_view(handout["handout_id"])
            self.assertEqual(order_of(pinned)[0], "evt-arrive-guangzhou")
            diff = workflow.version_diff(handout["timeline_version"], current["version"])
            self.assertIn("reordered", [change["kind"] for change in diff["changes"]])


if __name__ == "__main__":
    unittest.main()
