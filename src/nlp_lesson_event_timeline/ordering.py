"""从事件与时间依据推导时间线版本。

推导规则：
- 明示日期（explicit）直接定位事件；相对时间（relative）只在同一篇章内沿锚点事件传递，
  不同篇章的“翌日”不得串联；
- 每个事件可能因线索撤回而没有日期，事件本身保留，只是先后关系待复核；
- 相邻事件的先后依据标记为 explicit（双方原文明示）、inferred（至少一方为推断）
  或 ambiguous（同日等无法确认的情形）。
"""

from datetime import date, timedelta

from .timeline import KIND_EXPLICIT, KIND_RELATIVE, STATUS_ACTIVE

DATE_EXPLICIT = "explicit"
DATE_INFERRED = "inferred"
DATE_NONE = "none"

BASIS_EXPLICIT = "explicit"
BASIS_INFERRED = "inferred"
BASIS_AMBIGUOUS = "ambiguous"


def step_basis(left, right):
    """相邻两个有日期事件的先后依据：明示、推断或歧义。"""
    if left["date"] == right["date"]:
        return BASIS_AMBIGUOUS
    if left["date_kind"] == DATE_EXPLICIT and right["date_kind"] == DATE_EXPLICIT:
        return BASIS_EXPLICIT
    return BASIS_INFERRED


def latest_clues(clues):
    """按 clue_id 取最高修订号，返回 {clue_id: clue}。"""
    current = {}
    for clue in clues:
        previous = current.get(clue["clue_id"])
        if previous is None or clue["revision"] > previous["revision"]:
            current[clue["clue_id"]] = clue
    return current


def _pick(group):
    """在同一事件的同类线索中取最高修订号；并列且内容冲突时返回 (None, 冲突组)。"""
    top_revision = max(clue["revision"] for clue in group)
    tops = [clue for clue in group if clue["revision"] == top_revision]
    keys = {
        (clue["kind"], clue["date"], clue["anchor_event_id"], clue["offset_days"], clue["chapter"])
        for clue in tops
    }
    if len(keys) > 1:
        return None, tops
    return sorted(tops, key=lambda clue: clue["clue_id"])[0], None


def _review(kind, event_ids, clue_ids, detail):
    return {
        "kind": kind,
        "event_ids": sorted(event_ids),
        "clue_ids": sorted(clue_ids),
        "detail": detail,
        "status": "pending",
    }


def _review_key(item):
    return (item["kind"], tuple(item["event_ids"]), tuple(item["clue_ids"]))


def _resolve_dates(events, active):
    """返回 ({event_id: (date, kind, clue_ids)}, 复核项列表)。"""
    by_id = {event["event_id"]: event for event in events}
    review = []
    explicit_groups = {}
    relative_groups = {}
    for clue in active:
        if clue["event_id"] not in by_id:
            review.append(_review("clue_without_event", [], [clue["clue_id"]],
                                  "时间依据指向未登记的事件"))
            continue
        groups = explicit_groups if clue["kind"] == KIND_EXPLICIT else relative_groups
        groups.setdefault(clue["event_id"], []).append(clue)

    dates = {}
    for event_id, group in sorted(explicit_groups.items()):
        chosen, conflict = _pick(group)
        if chosen is None:
            review.append(_review("explicit_conflict", [event_id],
                                  [clue["clue_id"] for clue in conflict],
                                  "同一事件的多条明示日期互相冲突"))
        else:
            dates[event_id] = (date.fromisoformat(chosen["date"]), DATE_EXPLICIT, [chosen["clue_id"]])

    pending = {}
    for event_id, group in sorted(relative_groups.items()):
        if event_id in dates:
            continue  # 明示日期优先，相对线索保留为佐证
        chosen, conflict = _pick(group)
        if chosen is None:
            review.append(_review("relative_conflict", [event_id],
                                  [clue["clue_id"] for clue in conflict],
                                  "同一事件的多条相对时间互相冲突"))
        else:
            pending[event_id] = chosen

    while pending:
        progressed = False
        for event_id, clue in list(pending.items()):
            anchor = by_id.get(clue["anchor_event_id"])
            if anchor is None:
                review.append(_review("relative_anchor_missing", [event_id], [clue["clue_id"]],
                                      "相对时间的锚点事件未登记"))
                del pending[event_id]
                progressed = True
                continue
            if anchor["chapter"] != clue["chapter"] or by_id[event_id]["chapter"] != clue["chapter"]:
                review.append(_review("cross_chapter_relative",
                                      [event_id, clue["anchor_event_id"]], [clue["clue_id"]],
                                      "相对时间不能跨篇章串联"))
                del pending[event_id]
                progressed = True
                continue
            base = dates.get(clue["anchor_event_id"])
            if base is not None:
                base_date, _, base_clues = base
                dates[event_id] = (base_date + timedelta(days=clue["offset_days"]),
                                   DATE_INFERRED, [clue["clue_id"], *base_clues])
                del pending[event_id]
                progressed = True
        if not progressed:
            for event_id, clue in sorted(pending.items()):
                review.append(_review("relative_unresolved", [event_id, clue["anchor_event_id"]],
                                      [clue["clue_id"]],
                                      "相对时间的锚点没有可用日期（可能循环或锚点本身未定）"))
            pending.clear()
    return dates, review


def _pair_review(events, dates):
    """同篇章内无法确认先后的事件对进入复核队列。"""
    review = []
    by_chapter = {}
    for event in events:
        by_chapter.setdefault(event["chapter"], []).append(event["event_id"])
    for chapter, event_ids in sorted(by_chapter.items()):
        ordered = sorted(event_ids)
        for index, first in enumerate(ordered):
            for second in ordered[index + 1:]:
                first_date = dates.get(first)
                second_date = dates.get(second)
                if first_date is None or second_date is None:
                    review.append(_review("order_unknown", [first, second], [],
                                          "同一篇章内缺少可确认先后的时间依据"))
                elif first_date[0] == second_date[0]:
                    review.append(_review("same_day_order", [first, second], [],
                                          "同一篇章内日期相同，先后不明"))
    return review


def derive(events, clues, cause, derived_at):
    """根据当前事件与全部线索历史推导一个时间线版本（不含版本号）。"""
    active = [clue for clue in latest_clues(clues).values() if clue["status"] == STATUS_ACTIVE]
    dates, review = _resolve_dates(events, active)
    review.extend(_pair_review(events, dates))

    placements = []
    for event in sorted(events, key=lambda item: item["event_id"]):
        resolved = dates.get(event["event_id"])
        placements.append({
            "event_id": event["event_id"],
            "chapter": event["chapter"],
            "date": resolved[0].isoformat() if resolved else None,
            "date_kind": resolved[1] if resolved else DATE_NONE,
            "clue_ids": resolved[2] if resolved else [],
        })

    dated = [item for item in placements if item["date"] is not None]
    dated.sort(key=lambda item: (item["date"], item["event_id"]))
    sequence = [item["event_id"] for item in dated]
    by_event = {item["event_id"]: item for item in placements}
    steps = []
    for first, second in zip(sequence, sequence[1:]):
        steps.append({"before": first, "after": second,
                      "basis": step_basis(by_event[first], by_event[second])})

    review.sort(key=_review_key)
    return {
        "derived_at": derived_at,
        "cause": cause,
        "placements": placements,
        "sequence": sequence,
        "steps": steps,
        "undated": [item["event_id"] for item in placements if item["date"] is None],
        "review_items": review,
    }


def _core(version):
    return {key: version[key] for key in ("placements", "sequence", "steps", "undated", "review_items")}


def same_timeline(first, second):
    return _core(first) == _core(second)


def diff_versions(old, new):
    """比较两个版本，给出排序变化依据。"""
    changes = []
    old_placements = {item["event_id"]: item for item in (old or {}).get("placements", [])}
    new_placements = {item["event_id"]: item for item in new.get("placements", [])}
    for event_id in sorted(new_placements):
        before = old_placements.get(event_id)
        after = new_placements[event_id]
        if before is None:
            changes.append({"kind": "event_added", "event_id": event_id,
                            "date": after["date"], "date_kind": after["date_kind"]})
        elif (before["date"], before["date_kind"]) != (after["date"], after["date_kind"]):
            if after["date"] is None:
                kind = "event_undated"
            elif before["date"] is None:
                kind = "event_dated"
            elif before["date"] != after["date"]:
                kind = "date_corrected"
            else:
                kind = "basis_changed"
            changes.append({"kind": kind, "event_id": event_id,
                            "old_date": before["date"], "new_date": after["date"],
                            "old_kind": before["date_kind"], "new_kind": after["date_kind"]})
    for event_id in sorted(set(old_placements) - set(new_placements)):
        changes.append({"kind": "event_removed", "event_id": event_id})

    old_order = {event_id: index for index, event_id in enumerate((old or {}).get("sequence", []))}
    new_order = {event_id: index for index, event_id in enumerate(new.get("sequence", []))}
    shared = sorted(set(old_order) & set(new_order))
    for index, first in enumerate(shared):
        for second in shared[index + 1:]:
            old_sign = old_order[first] - old_order[second]
            new_sign = new_order[first] - new_order[second]
            if old_sign * new_sign < 0:
                changes.append({"kind": "reordered", "events": [first, second]})

    old_steps = {(step["before"], step["after"]): step["basis"] for step in (old or {}).get("steps", [])}
    for step in new.get("steps", []):
        key = (step["before"], step["after"])
        if key in old_steps and old_steps[key] != step["basis"]:
            changes.append({"kind": "step_basis_changed", "events": [step["before"], step["after"]],
                            "old_basis": old_steps[key], "new_basis": step["basis"]})

    old_review = {_review_key(item) for item in (old or {}).get("review_items", [])}
    new_review = {_review_key(item) for item in new.get("review_items", [])}
    for item in new.get("review_items", []):
        if _review_key(item) not in old_review:
            changes.append({"kind": "review_added", "item": item})
    for item in (old or {}).get("review_items", []):
        if _review_key(item) not in new_review:
            changes.append({"kind": "review_resolved", "item": item})
    return changes
