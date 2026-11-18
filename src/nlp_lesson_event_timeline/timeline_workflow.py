from datetime import datetime, timezone

from .ordering import derive, diff_versions, latest_clues, same_timeline, step_basis
from .timeline import Event, TimeClue, STATUS_WITHDRAWN


def _now():
    return datetime.now(timezone.utc).isoformat()


class TimelineWorkflow:
    """维护事件、时间依据、参与者与查询结果之间的联系。

    每次登记事件或修订时间依据都会重新推导时间线版本：查询结果始终读取最新版本，
    课堂材料按版本号引用历史版本，版本之间的排序变化依据可查询。
    """

    def __init__(self, store):
        self.store = store

    # ---- 登记 ----

    @staticmethod
    def _apply_event(state, event):
        """把事件写入 state，返回是否有变化；违反修订号规则时抛错。"""
        previous = next((item for item in state["events"]
                         if item["event_id"] == event["event_id"]), None)
        if previous is not None:
            if event["revision"] < previous["revision"]:
                raise ValueError("事件修订号必须递增")
            if event["revision"] == previous["revision"]:
                if event != previous:
                    raise ValueError("相同修订号的事件内容不一致")
                return False  # 幂等重放
            state["events"] = [item for item in state["events"]
                               if item["event_id"] != event["event_id"]]
        state["events"].append(event)
        state["events"].sort(key=lambda item: item["event_id"])
        return True

    @staticmethod
    def _apply_clue(state, clue):
        """把时间依据追加到 state，返回是否有变化；违反修订号规则时抛错。"""
        if clue["event_id"] not in {item["event_id"] for item in state["events"]}:
            raise ValueError("时间依据指向未登记的事件")
        current = latest_clues(state["clues"]).get(clue["clue_id"])
        if current is not None:
            if clue["revision"] < current["revision"]:
                raise ValueError("时间依据修订号必须递增")
            if clue["revision"] == current["revision"]:
                if clue != current:
                    raise ValueError("相同修订号的时间依据内容不一致")
                return False  # 幂等重放
        state["clues"].append(clue)
        return True

    def register_event(self, value, at=None):
        event = Event.from_dict(value).to_dict()
        state = self.store.read()
        if self._apply_event(state, event):
            self._rederive(state, {"action": "register_event", "event_id": event["event_id"],
                                   "revision": event["revision"]}, at)
            self.store.replace(state)
        return event

    def register_clue(self, value, at=None):
        clue = TimeClue.from_dict(value).to_dict()
        state = self.store.read()
        if self._apply_clue(state, clue):
            self._rederive(state, {"action": "register_clue", "clue_id": clue["clue_id"],
                                   "event_id": clue["event_id"], "revision": clue["revision"]}, at)
            self.store.replace(state)
        return clue

    def ingest_bundle(self, values, at=None):
        """原子导入一批事件与时间依据：全部校验通过才落盘，只产生一个新版本。"""
        if not isinstance(values, dict):
            raise TypeError("导入内容必须是包含 events 与 clues 的对象")
        events = [Event.from_dict(item).to_dict() for item in values.get("events", [])]
        clues = [TimeClue.from_dict(item).to_dict() for item in values.get("clues", [])]
        state = self.store.read()
        changed = False
        for event in events:
            changed = self._apply_event(state, event) or changed
        for clue in clues:
            changed = self._apply_clue(state, clue) or changed
        if changed:
            self._rederive(state, {"action": "ingest_bundle",
                                   "events": len(events), "clues": len(clues)}, at)
            self.store.replace(state)
        return {"events": len(events), "clues": len(clues),
                "version": state["versions"][-1]["version"] if state["versions"] else None}

    def withdraw_clue(self, clue_id, revision, at=None):
        """撤回一条时间依据：线索保留在历史中，事件不会被当作没有发生。"""
        state = self.store.read()
        current = latest_clues(state["clues"]).get(clue_id)
        if current is None:
            raise ValueError("时间依据不存在")
        if current["status"] == STATUS_WITHDRAWN:
            raise ValueError("时间依据已撤回")
        if int(revision) <= current["revision"]:
            raise ValueError("撤回修订号必须大于现有修订号")
        withdrawn = dict(current, revision=int(revision), status=STATUS_WITHDRAWN)
        state["clues"].append(withdrawn)
        self._rederive(state, {"action": "withdraw_clue", "clue_id": clue_id,
                               "event_id": current["event_id"], "revision": withdrawn["revision"]}, at)
        self.store.replace(state)
        return withdrawn

    def _rederive(self, state, cause, at):
        candidate = derive(state["events"], state["clues"], cause, at or _now())
        previous = state["versions"][-1] if state["versions"] else None
        if previous is not None and same_timeline(previous, candidate):
            return
        candidate["version"] = (previous["version"] if previous else 0) + 1
        candidate["changes"] = diff_versions(previous, candidate)
        state["versions"].append(candidate)

    # ---- 课堂引用 ----

    def issue_handout(self, title, handout_id=None, at=None):
        """按当前版本生成课堂材料引用；版本被固定保留，后续更正不影响已发材料。"""
        state = self.store.read()
        if not state["versions"]:
            raise ValueError("尚无可引用的时间线版本")
        handout_id = (handout_id or "").strip() or f"handout-{len(state['handouts']) + 1}"
        if any(item["handout_id"] == handout_id for item in state["handouts"]):
            raise ValueError("课堂材料编号已存在")
        handout = {"handout_id": handout_id, "title": str(title).strip(),
                   "timeline_version": state["versions"][-1]["version"], "issued_at": at or _now()}
        if not handout["title"]:
            raise ValueError("课堂材料缺少标题")
        state["handouts"].append(handout)
        self.store.replace(state)
        return handout

    # ---- 查询 ----

    def current_timeline(self, chapter=None):
        state = self.store.read()
        if not state["versions"]:
            raise ValueError("尚无可查询的时间线版本")
        return self._render(state, state["versions"][-1], chapter)

    def timeline_version(self, number, chapter=None):
        state = self.store.read()
        return self._render(state, self._find_version(state, number), chapter)

    def handout_view(self, handout_id, chapter=None):
        state = self.store.read()
        matches = [item for item in state["handouts"] if item["handout_id"] == handout_id]
        if not matches:
            raise ValueError("课堂材料不存在")
        handout = matches[0]
        view = self._render(state, self._find_version(state, handout["timeline_version"]), chapter)
        view["handout"] = handout
        return view

    def review_queue(self):
        state = self.store.read()
        if not state["versions"]:
            return {"version": None, "items": []}
        version = state["versions"][-1]
        return {"version": version["version"], "items": version["review_items"]}

    def version_diff(self, old_number, new_number):
        state = self.store.read()
        old = self._find_version(state, old_number)
        new = self._find_version(state, new_number)
        return {"from": old["version"], "to": new["version"],
                "cause": new["cause"], "changes": diff_versions(old, new)}

    def list_events(self):
        return self.store.read()["events"]

    def list_clues(self, event_id=None, include_withdrawn=True):
        clues = list(latest_clues(self.store.read()["clues"]).values())
        clues.sort(key=lambda item: item["clue_id"])
        if event_id:
            clues = [clue for clue in clues if clue["event_id"] == event_id]
        if not include_withdrawn:
            clues = [clue for clue in clues if clue["status"] != STATUS_WITHDRAWN]
        return clues

    def list_versions(self):
        return [{"version": item["version"], "derived_at": item["derived_at"],
                 "cause": item["cause"], "changes": item["changes"]}
                for item in self.store.read()["versions"]]

    def list_handouts(self):
        return self.store.read()["handouts"]

    # ---- 内部 ----

    @staticmethod
    def _find_version(state, number):
        for version in state["versions"]:
            if version["version"] == int(number):
                return version
        raise ValueError("时间线版本不存在")

    @staticmethod
    def _render(state, version, chapter):
        """把版本与当前登记的事件、参与者关联成查询结果。"""
        events = {item["event_id"]: item for item in state["events"]}
        placements = {item["event_id"]: item for item in version["placements"]}

        def describe(event_id):
            event = events.get(event_id)
            placement = placements[event_id]
            return {
                "event_id": event_id,
                "summary": event["summary"] if event else "",
                "chapter": placement["chapter"],
                "participants": event["participants"] if event else [],
                "date": placement["date"],
                "date_kind": placement["date_kind"],
                "clue_ids": placement["clue_ids"],
            }

        sequence = []
        kept = [event_id for event_id in version["sequence"]
                if chapter is None or placements[event_id]["chapter"] == chapter]
        for index, event_id in enumerate(kept):
            entry = describe(event_id)
            following = kept[index + 1] if index + 1 < len(kept) else None
            entry["step_to_next"] = (
                step_basis(placements[event_id], placements[following]) if following else None)
            sequence.append(entry)
        undated = [describe(event_id) for event_id in version["undated"]
                   if chapter is None or placements[event_id]["chapter"] == chapter]
        review = [item for item in version["review_items"]
                  if chapter is None or any(
                      placements.get(event_id, {}).get("chapter") == chapter
                      for event_id in item["event_ids"])]
        return {"version": version["version"], "derived_at": version["derived_at"],
                "sequence": sequence, "undated": undated, "review_items": review}
