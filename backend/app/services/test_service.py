from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.tests import (
    CompleteAttemptResponse,
    ContinueChatContext,
    StartAttemptResponse,
    SubmitAnswerRequest,
    TestDetailResponse,
    TestHistoryItem,
    TestHistoryResponse,
    TestListItem,
    TestListResponse,
    TestOption,
    TestQuestion,
    TestResultProfile,
)

_STATE_TEST_ID = "state-check-v1"
_SIXTEEN_TYPE_TEST_ID = "sixteen-type-v1"

_TESTS: list[dict] = [
    {
        "test_id": _STATE_TEST_ID,
        "code": "daily_state",
        "title": "今日状态测试",
        "test_type": "state",
        "estimated_minutes": 3,
        "audience": "all",
        "status": "published",
        "questions": [
            {
                "index": 0,
                "text": "过去一周你的情绪状态整体如何？",
                "options": [
                    {"id": "A", "text": "大部分时间比较平稳", "score": 4},
                    {"id": "B", "text": "偶尔会低落，但还能应付", "score": 3},
                    {"id": "C", "text": "经常感到低落，影响做事", "score": 2},
                    {"id": "D", "text": "几乎每天都很难受", "score": 1},
                ],
            },
            {
                "index": 1,
                "text": "过去一周你感到焦虑或紧张的程度？",
                "options": [
                    {"id": "A", "text": "几乎没有明显焦虑", "score": 4},
                    {"id": "B", "text": "偶尔焦虑，但不影响日常", "score": 3},
                    {"id": "C", "text": "经常焦虑，开始影响睡眠或做事", "score": 2},
                    {"id": "D", "text": "大部分时间都很焦虑，难以放松", "score": 1},
                ],
            },
            {
                "index": 2,
                "text": "过去一周你对生活的整体满意度？",
                "options": [
                    {"id": "A", "text": "总体还算满意", "score": 4},
                    {"id": "B", "text": "有些方面不太满意", "score": 3},
                    {"id": "C", "text": "很多方面都不太满意", "score": 2},
                    {"id": "D", "text": "几乎没有什么让我满意的", "score": 1},
                ],
            },
        ],
    },
    {
        "test_id": _SIXTEEN_TYPE_TEST_ID,
        "code": "sixteen_type",
        "title": "16型人格测试",
        "test_type": "personality",
        "estimated_minutes": 8,
        "audience": "all",
        "status": "published",
        "questions": [
            {
                "index": 0,
                "text": "在社交场合中，你通常：",
                "options": [
                    {"id": "A", "text": "认识新朋友让你精力充沛", "score": 4},
                    {"id": "B", "text": "可以和少数熟悉的人聊很久", "score": 3},
                    {"id": "C", "text": "更喜欢安静观察", "score": 2},
                    {"id": "D", "text": "人多会让你很疲惫", "score": 1},
                ],
            },
            {
                "index": 1,
                "text": "周末你更倾向于：",
                "options": [
                    {"id": "A", "text": "和朋友聚会或参加活动", "score": 4},
                    {"id": "B", "text": "约一两个好友小聚", "score": 3},
                    {"id": "C", "text": "在家做自己的事", "score": 2},
                    {"id": "D", "text": "一个人待着恢复能量", "score": 1},
                ],
            },
            {
                "index": 2,
                "text": "你更相信：",
                "options": [
                    {"id": "A", "text": "亲眼看到的事实和具体经验", "score": 4},
                    {"id": "B", "text": "更多基于实际经验", "score": 3},
                    {"id": "C", "text": "更相信直觉和可能性", "score": 2},
                    {"id": "D", "text": "对抽象模式和未来走向很敏感", "score": 1},
                ],
            },
            {
                "index": 3,
                "text": "做决定时你更看重：",
                "options": [
                    {"id": "A", "text": "逻辑分析和对错", "score": 4},
                    {"id": "B", "text": "先看逻辑再看人际关系", "score": 3},
                    {"id": "C", "text": "先考虑对周围人的影响", "score": 2},
                    {"id": "D", "text": "价值观与人的感受最重要", "score": 1},
                ],
            },
            {
                "index": 4,
                "text": "你对日程安排的态度：",
                "options": [
                    {"id": "A", "text": "喜欢提前计划，按步骤执行", "score": 4},
                    {"id": "B", "text": "有计划但也接受调整", "score": 3},
                    {"id": "C", "text": "大概有个方向就好", "score": 2},
                    {"id": "D", "text": "跟着感觉走，不喜欢被约束", "score": 1},
                ],
            },
            {
                "index": 5,
                "text": "任务临近截止时你通常：",
                "options": [
                    {"id": "A", "text": "早就做好了", "score": 4},
                    {"id": "B", "text": "按计划推进中", "score": 3},
                    {"id": "C", "text": "刚开始着手", "score": 2},
                    {"id": "D", "text": "在最后关头冲刺", "score": 1},
                ],
            },
        ],
    },
]

_SIXTEEN_TYPE_RESULTS: dict[str, dict] = {
    "INFJ": {
        "result_code": "INFJ-like",
        "result_label": "洞察型陪伴者",
        "summary": "你对他人的情绪很敏感，容易想得很深，擅长洞察他人的需求。珍惜你的同理心和创造力，但也请记得照顾好自己的边界，学会在付出与自我之间找到平衡。",
        "traits": ["对他人的情绪很敏感", "容易想得很深", "压力下会过度消耗自己", "重视深层联结", "很有同理心"],
        "strengths": ["善于洞察他人需求", "忠诚且有耐心", "富有创造力"],
        "blind_spots": ["容易忽略自己的需求", "过度反省", "难以拒绝别人"],
        "companion_style": "先接住情绪，再轻轻拓宽视角",
    },
    "ESTP": {
        "result_code": "ESTP-like",
        "result_label": "适应型行动者",
        "summary": "你务实灵活，擅长临场应变，喜欢动手解决问题。你的行动力是你最大的优势，试着在快速行动的同时也偶尔停下来感受一下内在的情绪节奏。",
        "traits": ["务实灵活", "擅长临场应变", "喜欢动手解决问题", "能量来得快去得也快", "注重当下效果"],
        "strengths": ["行动力强", "危机时很靠谱", "善于抓住机会"],
        "blind_spots": ["容易忽略深层情绪", "有时显得不耐烦", "容易厌倦重复"],
        "companion_style": "给具体可执行的很小步骤，别讲大道理",
    },
    "INFP": {
        "result_code": "INFP-like",
        "result_label": "理想型调和者",
        "summary": "你内心世界丰富，追求意义和真实，对美和情感很敏感。你的深度共情和创造力是珍贵的礼物，记得把理想落地为小步骤，让梦想也能在日常中生长。",
        "traits": ["内心世界丰富", "追求意义和真实", "对美和情感很敏感", "灵活包容", "有时沉浸在想象中"],
        "strengths": ["深度共情", "创造性表达", "尊重个体差异"],
        "blind_spots": ["容易拖延", "有时过度理想化", "对批评很敏感"],
        "companion_style": "先肯定感受的正当性，再一起找到意义",
    },
    "ENTJ": {
        "result_code": "ENTJ-like",
        "result_label": "策略型推动者",
        "summary": "你目标导向，喜欢掌控和规划，有很强的意志力。你的领导力和抗压能力令人佩服，但也请允许自己偶尔卸下盔甲，承认疲惫并不可耻。",
        "traits": ["目标导向", "喜欢掌控和规划", "有很强的意志力", "注重效率和成果", "不习惯表达脆弱"],
        "strengths": ["有领导力", "抗压能力强", "善于统筹资源"],
        "blind_spots": ["容易忽略自己和他人的情感", "太想掌控", "累到崩溃才停下来"],
        "companion_style": "先承认压力已经很大了，再一起拆成小目标",
    },
}

_attempts: dict[str, dict] = {}
_history: list[dict] = []


def _question_to_schema(q: dict) -> TestQuestion:
    return TestQuestion(
        index=q["index"],
        text=q["text"],
        options=[TestOption(id=opt["id"], text=opt["text"], score=opt["score"]) for opt in q["options"]],
    )


def get_tests() -> TestListResponse:
    items = [
        TestListItem(
            test_id=t["test_id"],
            code=t["code"],
            title=t["title"],
            test_type=t["test_type"],
            estimated_minutes=t["estimated_minutes"],
            audience=t["audience"],
            status=t["status"],
        )
        for t in _TESTS
    ]
    return TestListResponse(items=items)


def _find_test(test_id: str) -> dict | None:
    for t in _TESTS:
        if t["test_id"] == test_id:
            return t
    return None


def get_test(test_id: str) -> TestDetailResponse | None:
    t = _find_test(test_id)
    if t is None:
        return None
    return TestDetailResponse(
        test_id=t["test_id"],
        code=t["code"],
        title=t["title"],
        questions=[_question_to_schema(q) for q in t["questions"]],
    )


def start_attempt(user_id: str, test_id: str) -> StartAttemptResponse | None:
    t = _find_test(test_id)
    if t is None:
        return None
    attempt_id = str(uuid4())
    _attempts[attempt_id] = {
        "user_id": user_id,
        "test_id": test_id,
        "answers": {},
        "status": "in_progress",
        "created_at": datetime.now(timezone.utc),
    }
    return StartAttemptResponse(
        attempt_id=attempt_id,
        test_id=test_id,
        questions=[_question_to_schema(q) for q in t["questions"]],
    )


def submit_answer(attempt_id: str, question_index: int, option_id: str) -> bool:
    attempt = _attempts.get(attempt_id)
    if attempt is None or attempt["status"] != "in_progress":
        return False
    t = _find_test(attempt["test_id"])
    if t is None:
        return False
    valid_indices = {q["index"] for q in t["questions"]}
    if question_index not in valid_indices:
        return False
    question = t["questions"][question_index]
    valid_options = {opt["id"] for opt in question["options"]}
    if option_id not in valid_options:
        return False
    attempt["answers"][question_index] = option_id
    return True


def _score_option(test: dict, question_index: int, option_id: str) -> int:
    for q in test["questions"]:
        if q["index"] == question_index:
            for opt in q["options"]:
                if opt["id"] == option_id:
                    return opt["score"]
    return 0


def _compute_state_result(test: dict, answers: dict[int, str]) -> dict:
    total = sum(_score_option(test, idx, opt_id) for idx, opt_id in answers.items())
    if total >= 9:
        return {
            "result_code": "stable",
            "result_label": "当前状态较稳定",
            "summary": "最近你的情绪状态整体比较平稳，说明你目前有较好的自我调节能力。继续保持现有的节奏，留意自己的能量边界，在平稳中积累更多内在资源。",
            "risk_note": "当前状态整体平稳，继续保持自我照顾的节奏。",
            "suggested_actions": ["记录每天一件让你感到平静的小事", "保持规律作息", "留意自己的能量变化"],
            "profile": TestResultProfile(
                traits=["情绪平稳", "自我调节良好"],
                strengths=["能维持日常节奏", "对压力有较好应对"],
                blind_spots=["可能在平稳中忽略细微的情绪变化"],
                companion_style="保持关注，温和提醒留意自己的状态",
            ),
        }
    if total >= 6:
        return {
            "result_code": "mild",
            "result_label": "有些波动，留意自我照顾",
            "summary": "最近你的情绪有一些波动，这是很正常的反应，不意味着你不够好。试着给自己多一点时间和空间，减少不必要的压力来源，优先照顾好自己的基本需求。",
            "risk_note": "情绪有一些波动，在正常范围内。留意是否持续加重，适当减负。",
            "suggested_actions": ["减少不必要的任务和压力源", "每天留出15分钟给自己放松", "和信任的人聊聊最近的状态"],
            "profile": TestResultProfile(
                traits=["情绪有波动", "尚能应对"],
                strengths=["有自我觉察", "愿意面对情绪"],
                blind_spots=["可能低估压力累积", "容易硬撑"],
                companion_style="先确认不易，再一起找一个小出口",
            ),
        }
    return {
        "result_code": "burdened",
        "result_label": "最近负担较重，优先照顾自己",
        "summary": "最近你的情绪负担比较重，这可能让你感到疲惫和无助。这不是你的错，现在最重要的事情是先照顾好自己，减少对自己的要求，并考虑联系可以信任的人。",
        "risk_note": "当前负担较重，这不是你的错。建议优先照顾自己，并考虑联系现实中的支持。如果持续影响睡眠或日常生活，可以联系专业支持。",
        "suggested_actions": ["减少对自己的要求，只做必须的事", "联系一个可信任的人", "考虑寻求专业心理支持"],
        "profile": TestResultProfile(
            traits=["情绪负担重", "需要休息"],
            strengths=["仍在寻求了解自己", "有求助的意愿"],
            blind_spots=["可能把太多责任揽在自己身上", "容易孤立自己"],
            companion_style="先共情负担的真实，再给一个极小的可做动作",
        ),
    }


def _compute_sixteen_type_result(test: dict, answers: dict[int, str]) -> dict:
    scores = {idx: _score_option(test, idx, opt_id) for idx, opt_id in answers.items()}
    ei_avg = (scores.get(0, 0) + scores.get(1, 0)) / 2
    sn = scores.get(2, 0)
    tf = scores.get(3, 0)
    jp_avg = (scores.get(4, 0) + scores.get(5, 0)) / 2

    e_or_i = "E" if ei_avg >= 2.5 else "I"
    s_or_n = "S" if sn >= 2.5 else "N"
    t_or_f = "T" if tf >= 2.5 else "F"
    j_or_p = "J" if jp_avg >= 2.5 else "P"

    candidates = [
        ("INFJ", {"I", "N", "F", "J"}),
        ("ESTP", {"E", "S", "T", "P"}),
        ("INFP", {"I", "N", "F", "P"}),
        ("ENTJ", {"E", "N", "T", "J"}),
    ]
    user_axes = {e_or_i, s_or_n, t_or_f, j_or_p}
    best_type = max(candidates, key=lambda item: len(item[1] & user_axes))[0]

    result = _SIXTEEN_TYPE_RESULTS[best_type]
    return {
        "result_code": result["result_code"],
        "result_label": result["result_label"],
        "summary": result["summary"],
        "suggested_actions": ["把这个结果当作一面镜子而非标签", "选择一个你想加强的方向开始练习", "在接下来的对话中聊聊这个发现"],
        "profile": TestResultProfile(
            sixteen_type_code=best_type,
            sixteen_type_label=result["result_label"],
            traits=result["traits"],
            strengths=result["strengths"],
            blind_spots=result["blind_spots"],
            companion_style=result["companion_style"],
        ),
    }


def complete_attempt(attempt_id: str) -> CompleteAttemptResponse | None:
    attempt = _attempts.get(attempt_id)
    if attempt is None or attempt["status"] != "in_progress":
        return None
    t = _find_test(attempt["test_id"])
    if t is None:
        return None
    expected_count = len(t["questions"])
    if len(attempt["answers"]) < expected_count:
        return None

    if t["test_id"] == _SIXTEEN_TYPE_TEST_ID:
        result_data = _compute_sixteen_type_result(t, attempt["answers"])
    else:
        result_data = _compute_state_result(t, attempt["answers"])

    attempt["status"] = "completed"
    attempt["completed_at"] = datetime.now(timezone.utc)
    attempt["result_code"] = result_data["result_code"]
    attempt["result_label"] = result_data["result_label"]

    _history.append({
        "attempt_id": attempt_id,
        "test_id": attempt["test_id"],
        "test_title": t["title"],
        "result_code": result_data["result_code"],
        "result_label": result_data["result_label"],
        "completed_at": attempt["completed_at"],
        "user_id": attempt["user_id"],
    })

    profile = result_data["profile"]
    return CompleteAttemptResponse(
        attempt_id=attempt_id,
        test_code=t["code"],
        result_code=result_data["result_code"],
        result_title=result_data["result_label"],
        summary=result_data["summary"],
        strengths=profile.strengths,
        blind_spots=profile.blind_spots,
        suggested_actions=result_data.get("suggested_actions", []),
        continue_chat_context=ContinueChatContext(mode="test", context_type="test_result"),
        profile=profile,
    )


def get_history(user_id: str) -> TestHistoryResponse:
    items = [
        TestHistoryItem(
            attempt_id=h["attempt_id"],
            test_id=h["test_id"],
            test_title=h["test_title"],
            result_code=h["result_code"],
            result_label=h["result_label"],
            completed_at=h["completed_at"],
        )
        for h in _history
        if h["user_id"] == user_id
    ]
    items.sort(key=lambda item: item.completed_at, reverse=True)
    return TestHistoryResponse(items=items)
