# 测试中心题库

本目录管理测试中心所有测试的题目数据、评分规则和评分算法。

---

## 目录结构

```
data/tests/
├── {category}/
│   └── {test-id}/
│       ├── *_title*.json       # 题目数据（必需）
│       ├── *_score*.json       # 评分规则（必需）
│       └── scorer.py           # 评分算法模块（必需）
```

### 当前测试

| 分类 | 测试 ID | 状态 | 说明 |
|------|---------|------|------|
| `state` | `state-check-v1` | ✅ published | 今日状态测试（3题） |
| `personality` | `mbti-sixteen-type` | ✅ published | MBTI 16型人格（80题） |
| `anime` | `anime-match-v1` | 🏗️ draft | 动漫角色测试（未完成） |

---

## 文件规范

### title.json — 题目数据

文件名必须包含 `title` 子串（如 `state_check_v1_title.json`），所有测试的 title JSON **统一采用以下格式**：

```json
{
  "test_id": "state-check-v1",
  "code": "daily_state",
  "title": "今日状态测试",
  "test_type": "state",
  "estimated_minutes": 3,
  "audience": "all",
  "status": "published",
  "questions": [
    {
      "id": "state-q-0",
      "index": 0,
      "text": "题目正文",
      "options": [
        {"id": "A", "text": "选项文本"},
        {"id": "B", "text": "选项文本"}
      ]
    }
  ]
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `test_id` | string | 测试唯一 ID，**必须与文件夹名一致** |
| `code` | string | 英文代码，用于前端路由 |
| `title` | string | 测试标题 |
| `test_type` | string | 分类：`state` / `personality` / `anime` |
| `estimated_minutes` | int | 预估完成分钟数 |
| `audience` | string | 受众：通常为 `"all"` |
| `status` | string | `"published"`（发布）或 `"draft"`（草稿） |
| `questions` | array | 题目列表 |

**questions 元素**：

| 字段 | 说明 |
|------|------|
| `id` | **稳定唯一标识**（如 `"mbti-q-000"`、`"state-q-0"`），题目打乱后此 ID 不变，用于关联答案 |
| `index` | 当前题序（从 0 开始），打乱后改变 |
| `text` | 题目正文（**所有题型均需提供**） |
| `options` | 选项列表，每项含 `id`（如 `"A"`）和 `text`（**所有题型均需提供**） |
| `metadata` | 可选，附加富文本数据（如 MBTI 的完整 `content`、`category`、`label` 等），scorer.py 自行读取 |

> **score 不在 title.json 中**：选项的计分值统一放在 score.json 的 `scoring` 字段中，保持题目数据与评分规则分离。当前 API 仍返回 `TestOption.score`，当题目 JSON 未提供该字段时会回填 `0` 以兼容旧前端。

### score.json — 评分规则

文件名必须包含 `score` 子串（如 `state_check_v1_score.json`），所有测试的 score JSON **统一采用以下两层结构**：

```json
{
  "test_id": "state-check-v1",
  "scoring_method": "sum",
  "results": {
    "stable": {
      "result_code": "stable",
      "result_label": "当前状态较稳定",
      "summary": "...",
      "suggested_actions": ["..."],
      "risk_note": "...",
      "traits": ["..."],
      "strengths": ["..."],
      "blind_spots": ["..."],
      "companion_style": "..."
    },
    "mild": { ... }
  },
  "default_result": { ... },
  "scoring": {
    "option_scores": {
      "0": {"A": 4, "B": 3, "C": 2, "D": 1},
      "1": {"A": 4, "B": 3, "C": 2, "D": 1}
    },
    "thresholds": [
      {"min_total": 9, "result_code": "stable", ...},
      {"min_total": 6, "result_code": "mild", ...}
    ]
  }
}
```

**顶层字段**：

| 字段 | 说明 |
|------|------|
| `test_id` | 测试 ID |
| `scoring_method` | 评分方法描述 |
| `results` | **结果解释映射**：`{result_code: {描述字典}}`，统一字段包括 `result_code`、`result_label`、`summary`、`suggested_actions`、`risk_note`、`traits`、`strengths`、`blind_spots`、`companion_style` |
| `default_result` | 可选，兜底结果 |
| `scoring` | **评分规则**（测试特定格式），scorer.py 从本字段读取具体计分逻辑 |

**MBTI 参考**：`scoring` 字段包含 `traditional_dimensions`、`cognitive_stacks`、`cross_validation_rules`；`results` 字段包含各类型/维度的解释文本。

### scorer.py — 评分算法

必须导出 `compute(test, answers) -> dict` 函数：

```python
from typing import Dict

def compute(test: dict, answers: dict[int, str]) -> dict:
    """评分函数。

    参数:
        test: 来自 title.json 的完整测试 dict（含 questions）
        answers: {question_index: option_id}，如 {0: "A", 1: "B", ...}。
                 若答案来自 JSON 存储，调用方应先把 key 规范化为 int 再传入 scorer。

    返回 dict 必须包含:
        result_code       — 结果代码（如 "stable", "INFJ-like"）
        result_label      — 结果标签（如 "当前状态较稳定", "洞察型陪伴者"）
        summary           — 结果摘要文本
        suggested_actions — 建议行动列表 (list[str])
        traits            — 特征列表 (list[str])
        strengths         — 优势列表 (list[str])
        blind_spots       — 盲点列表 (list[str])
        companion_style   — 陪伴方式描述 (str)

    personality 类型可额外返回:
        sixteen_type_code  — MBTI 四字母代码（如 "INFJ"）
        sixteen_type_label — MBTI 类型标签
    """
    ...
```

**规则**：
- 每个测试一个独立的 scorer.py，互不干扰
- scorer.py 可 import 标准库和同目录 JSON 文件
- 推荐通过 `Path(__file__).resolve().parent` 定位同目录文件

---

## 加载机制

`test_service.py`（`app/services/test_service.py`）通过以下方式自动发现测试：

```python
_TESTS_DIR = BASE_DIR / "data" / "tests"
_TEST_CATEGORIES = ["state", "personality", "anime"]
```

| 函数 | 作用 |
|------|------|
| `_load_all_tests()` | 遍历 `_TEST_CATEGORIES` 下所有子文件夹，查找 `*title*.json` 文件，返回完整测试列表 |
| `_load_test(test_id)` | 根据 `{category}/{test_id}/*title*.json` 路径加载单个测试 |
| `_load_scorer(type, test_id)` | 通过 `importlib.import_module(f"data.tests.{type}.{test_id}.scorer")` 动态加载评分模块 |

**关键特性**：
- 系统首次遍历子文件夹下所有 `*title*.json` 文件来发现测试
- 修改 title.json / score.json / scorer.py 后**无需重启服务**（每次请求实时读取）
- 新增测试 = 创建文件夹 + 放入三件套，零代码改动

---

## CRUD 操作指南

### CREATE — 创建测试

```bash
# 1. 创建测试文件夹
mkdir -p data/tests/state/new-test-v1/

# 2. 创建 title.json
cat > data/tests/state/new-test-v1/new_test_title.json << 'EOF'
{
  "test_id": "new-test-v1",
  "code": "new_test",
  "title": "新测试",
  "test_type": "state",
  "estimated_minutes": 3,
  "audience": "all",
  "status": "draft",
  "questions": [...] 
}
EOF

# 3. 创建 score.json
# 4. 创建 scorer.py（导出 compute 函数）
```

### READ — 读取测试

通过 `GET /api/v1/tests`（列表）和 `GET /api/v1/tests/{test_id}`（详情）由前端调用。直接读取文件可通过 Python：

```python
from app.services.test_service import _load_test, _load_all_tests

tests = _load_all_tests()       # 所有测试列表
test = _load_test("new-test-v1")  # 单个测试详情
```

### UPDATE — 修改测试

直接编辑对应目录下的文件：

| 修改需求 | 操作文件 | 说明 |
|---------|---------|------|
| 题目标题/选项 | `*title*.json` | 实时生效 |
| 评分分值/阈值 | `*score*.json` | 实时生效 |
| 评分算法/逻辑 | `scorer.py` | 需重启服务（Python 模块缓存） |
| 发布/下架 | `*title*.json` 中 `status` 字段 | 实时生效 |

### DELETE — 删除测试

```bash
# 删除整个测试文件夹
rm -rf data/tests/state/old-test-v1/

# 或删除后恢复为 draft（保留数据但不可测试）
# 编辑 title.json 设置 "status": "draft"
```

> 删除测试文件夹不影响数据库中已有的 `test_attempts` 和 `test_history` 记录，但历史结果页无法再重新计算（`get_attempt_result()` 会因找不到 scorer 而返回 404）。

---

## 注意事项

1. **test_id 一致性**：文件夹名、title.json 中的 `test_id`、score.json 中的 `test_id` 三者必须保持一致
2. **JSON 编码**：所有 JSON 文件必须使用 **UTF-8 without BOM** 编码，否则 Python `json.loads()` 会抛出 `Unexpected UTF-8 BOM` 错误
3. **scorer 健壮性**：`scorer.py` 应处理 `answers` 中缺失某题答案的情况（`dict.get()` 或 `KeyError` 保护）
4. **性能**：每次请求实时读取 JSON 文件（轻量，无缓存），单个测试文件建议控制在 500KB 以内
5. **Python 模块路径**：`scorer.py` 通过 `data.tests.{category}.{test_id}.scorer` 加载。虽然 `-` 不是标准 Python 标识符的一部分，但这里通过 `importlib.import_module()` 按文件系统路径加载，包含 `-` 的测试文件夹名仍可正常导入。
