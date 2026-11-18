import json
from pathlib import Path

SECTIONS = ("events", "clues", "versions", "handouts")


def empty_state():
    return {section: [] for section in SECTIONS}


class TimelineStore:
    """时间线状态的本地 JSON 持久化：事件、时间依据历史、版本与课堂引用。"""

    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return empty_state()
        if not isinstance(value, dict) or any(not isinstance(value.get(key), list) for key in SECTIONS):
            raise ValueError("时间线存储格式无效")
        return {key: value[key] for key in SECTIONS}

    def replace(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
