from dataclasses import dataclass, asdict, field
from datetime import date

KIND_EXPLICIT = "explicit"  # 原文明确日期
KIND_RELATIVE = "relative"  # 上下文推断的相对时间

STATUS_ACTIVE = "active"
STATUS_WITHDRAWN = "withdrawn"


def _clean(value):
    return str(value).strip() if value is not None else ""


@dataclass(frozen=True)
class Participant:
    person: str
    role: str = "参与"

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("参与者必须是对象")
        participant = cls(person=_clean(value.get("person")), role=_clean(value.get("role")) or "参与")
        if not participant.person:
            raise ValueError("参与者缺少人物姓名")
        return participant


@dataclass(frozen=True)
class Event:
    event_id: str
    summary: str
    chapter: str
    revision: int
    participants: tuple = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("事件必须是对象")
        raw_participants = value.get("participants") or []
        if not isinstance(raw_participants, list):
            raise ValueError("事件参与者必须是列表")
        event = cls(
            event_id=_clean(value.get("event_id")),
            summary=_clean(value.get("summary")),
            chapter=_clean(value.get("chapter")),
            revision=int(value.get("revision", 0)),
            participants=tuple(Participant.from_dict(item) for item in raw_participants),
        )
        if not event.event_id or not event.summary or not event.chapter:
            raise ValueError("事件缺少身份、摘要或所属篇章")
        if event.revision < 1:
            raise ValueError("事件缺少有效修订号")
        return event

    def to_dict(self):
        value = asdict(self)
        value["participants"] = [asdict(item) for item in self.participants]
        return value


@dataclass(frozen=True)
class TimeClue:
    clue_id: str
    event_id: str
    kind: str
    expression: str
    chapter: str
    revision: int
    date: str = ""
    anchor_event_id: str = ""
    offset_days: int = 0
    source_record: str = ""
    status: str = STATUS_ACTIVE

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("时间依据必须是对象")
        clue = cls(
            clue_id=_clean(value.get("clue_id")),
            event_id=_clean(value.get("event_id")),
            kind=_clean(value.get("kind")),
            expression=_clean(value.get("expression")),
            chapter=_clean(value.get("chapter")),
            revision=int(value.get("revision", 0)),
            date=_clean(value.get("date")),
            anchor_event_id=_clean(value.get("anchor_event_id")),
            offset_days=int(value.get("offset_days", 0) or 0),
            source_record=_clean(value.get("source_record")),
            status=_clean(value.get("status")) or STATUS_ACTIVE,
        )
        if not clue.clue_id or not clue.event_id or not clue.expression or not clue.chapter:
            raise ValueError("时间依据缺少身份、所属事件、原文表达或篇章")
        if clue.revision < 1:
            raise ValueError("时间依据缺少有效修订号")
        if clue.status not in (STATUS_ACTIVE, STATUS_WITHDRAWN):
            raise ValueError("时间依据状态无效")
        if clue.kind == KIND_EXPLICIT:
            if not clue.date:
                raise ValueError("明示时间依据缺少日期")
            date.fromisoformat(clue.date)
        elif clue.kind == KIND_RELATIVE:
            if not clue.anchor_event_id:
                raise ValueError("相对时间依据缺少锚点事件")
        else:
            raise ValueError("时间依据类型必须是 explicit 或 relative")
        return clue

    def to_dict(self):
        return asdict(self)
