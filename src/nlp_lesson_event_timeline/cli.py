import argparse
import json
from pathlib import Path

from .repository import RecordRepository
from .timeline_store import TimelineStore
from .timeline_workflow import TimelineWorkflow
from .workflow import TextWorkflow


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _timeline(args):
    return TimelineWorkflow(TimelineStore(args.timeline))


def main():
    parser = argparse.ArgumentParser(description="本地教研文本与课文事件时间线工具")
    parser.add_argument("--state", default="var/records.json", help="文本记录库路径")
    parser.add_argument("--timeline", default="var/timeline.json", help="时间线存储路径")
    actions = parser.add_subparsers(dest="action", required=True)

    ingest = actions.add_parser("ingest", help="导入文本记录")
    ingest.add_argument("path", nargs="?", default="fixtures/records.json")
    actions.add_parser("list", help="查看文本记录")

    bundle = actions.add_parser("ingest-timeline", help="导入事件与时间依据")
    bundle.add_argument("path", nargs="?", default="fixtures/timeline.json")
    event = actions.add_parser("event", help="登记或修订事件（JSON 文件，单个或列表）")
    event.add_argument("path")
    clue = actions.add_parser("clue", help="登记或修订时间依据（JSON 文件，单个或列表）")
    clue.add_argument("path")
    withdraw = actions.add_parser("withdraw", help="撤回一条时间依据（事件保留）")
    withdraw.add_argument("clue_id")
    withdraw.add_argument("--revision", type=int, required=True)

    timeline = actions.add_parser("timeline", help="查看当前或指定版本的时间线")
    timeline.add_argument("--chapter")
    timeline.add_argument("--version", type=int)
    actions.add_parser("versions", help="列出时间线版本及变化依据")
    diff = actions.add_parser("diff", help="比较两个版本的排序变化")
    diff.add_argument("old", type=int)
    diff.add_argument("new", type=int)
    actions.add_parser("review", help="查看待复核的先后关系")
    actions.add_parser("events", help="列出事件")
    clues = actions.add_parser("clues", help="列出时间依据")
    clues.add_argument("--event")

    handout = actions.add_parser("handout", help="按当前版本生成课堂材料引用")
    handout.add_argument("title")
    handout.add_argument("--id", dest="handout_id")
    actions.add_parser("handouts", help="列出课堂材料引用")
    show = actions.add_parser("handout-show", help="查看课堂材料引用的历史版本")
    show.add_argument("handout_id")
    show.add_argument("--chapter")

    args = parser.parse_args()

    if args.action == "ingest":
        result = TextWorkflow(RecordRepository(args.state)).ingest(_load_json(args.path))
    elif args.action == "list":
        result = TextWorkflow(RecordRepository(args.state)).list_records()
    else:
        workflow = _timeline(args)
        if args.action == "ingest-timeline":
            result = workflow.ingest_bundle(_load_json(args.path))
        elif args.action == "event":
            values = _load_json(args.path)
            values = values if isinstance(values, list) else [values]
            result = [workflow.register_event(value) for value in values]
        elif args.action == "clue":
            values = _load_json(args.path)
            values = values if isinstance(values, list) else [values]
            result = [workflow.register_clue(value) for value in values]
        elif args.action == "withdraw":
            result = workflow.withdraw_clue(args.clue_id, args.revision)
        elif args.action == "timeline":
            result = (workflow.timeline_version(args.version, chapter=args.chapter)
                      if args.version else workflow.current_timeline(chapter=args.chapter))
        elif args.action == "versions":
            result = workflow.list_versions()
        elif args.action == "diff":
            result = workflow.version_diff(args.old, args.new)
        elif args.action == "review":
            result = workflow.review_queue()
        elif args.action == "events":
            result = workflow.list_events()
        elif args.action == "clues":
            result = workflow.list_clues(event_id=args.event)
        elif args.action == "handout":
            result = workflow.issue_handout(args.title, handout_id=args.handout_id)
        elif args.action == "handouts":
            result = workflow.list_handouts()
        elif args.action == "handout-show":
            result = workflow.handout_view(args.handout_id, chapter=args.chapter)
        else:
            parser.error("未知操作")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
