# 课文事件时间线

课文事件时间线用于处理本地合成教研文本，保存来源版本、文本片段和处理记录，供校内复核使用。

在此之上，系统维护历史课文的事件时间线：事件（摘要、所属篇章、参与者）与时间依据（原文时间表达）分开保存，通过推导把时间依据连成排序版本，供课堂材料引用。

## 环境

需要 Python 3.11 或更新版本。应用运行不依赖第三方包；运行测试和构建前，安装固定版本的开发工具：`python -m pip install -r requirements-dev.txt`。

## 运行

执行 `PYTHONPATH=src python -m nlp_lesson_event_timeline.cli ingest fixtures/records.json` 导入演练记录，再执行 `PYTHONPATH=src python -m nlp_lesson_event_timeline.cli list` 查看当前文本处理结果。运行数据保存在 `var/records.json`。

## 事件时间线

概念：

- **事件**：摘要、所属篇章、参与人物及其角色；事件独立于时间依据存在，删除线索不会让事件“没有发生”。
- **时间依据**：原文时间表达，分两类——`explicit`（原文明示日期）与 `relative`（上下文推断的相对时间，如“翌日”）。相对时间只在同一篇章内沿锚点事件传递，不同篇章的“翌日”不会串联，违规线索进入复核队列。线索只能修订（递增修订号）或撤回，历史全部保留。
- **时间线版本**：每次登记或修订都会重新推导排序。相邻事件的先后依据标注为 `explicit`（双方明示）、`inferred`（含推断）或 `ambiguous`（同日等歧义）；无法确认先后的同篇章事件对留待复核（`review`）。
- **课堂材料**：按版本号引用时间线。更正时间后当前查询立即反映新排序，已发放材料仍固定在旧版本，版本间差异（`diff`）说明排序变化依据。

常用命令（时间线数据保存在 `var/timeline.json`，可用 `--timeline` 改路径）：

```sh
PYTHONPATH=src python -m nlp_lesson_event_timeline.cli ingest-timeline fixtures/timeline.json  # 原子导入事件与时间依据
PYTHONPATH=src python -m nlp_lesson_event_timeline.cli timeline [--chapter 第一章] [--version 2]  # 查看当前或历史版本
PYTHONPATH=src python -m nlp_lesson_event_timeline.cli clue 更正.json      # 修订一条时间依据（递增修订号）
PYTHONPATH=src python -m nlp_lesson_event_timeline.cli withdraw clue-id --revision 2           # 撤回线索，事件保留为“时间未定”
PYTHONPATH=src python -m nlp_lesson_event_timeline.cli review              # 待复核的先后关系
PYTHONPATH=src python -m nlp_lesson_event_timeline.cli handout "课时标题" --id lesson-1        # 按当前版本生成课堂引用
PYTHONPATH=src python -m nlp_lesson_event_timeline.cli handout-show lesson-1                   # 查看材料引用的历史版本
PYTHONPATH=src python -m nlp_lesson_event_timeline.cli diff 1 2            # 两个版本间的排序变化依据
```

## 测试

执行 `python -m pytest -q` 检查文本规范化、记录处理、状态读取、本地持久化，以及事件时间线的推导、版本保留、篇章隔离与复核队列。
