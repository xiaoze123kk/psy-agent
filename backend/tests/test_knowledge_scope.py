from __future__ import annotations

import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, KnowledgeGap
from app.services import knowledge_service


class NoDatabaseAccess:
    def __getattr__(self, name: str):
        raise AssertionError(f"knowledge DB should not be accessed for this path: {name}")


class KnowledgeScopeTests(unittest.IsolatedAsyncioTestCase):
    def test_classifier_rejects_non_psychology_questions(self) -> None:
        for question in ("打飞机啥意思", "帮我写代码", "今天股票怎么样"):
            with self.subTest(question=question):
                self.assertEqual(knowledge_service._classify_knowledge_scope(question), "out_of_scope")

    def test_classifier_accepts_psychology_context(self) -> None:
        for question in (
            "我因为频繁自慰很焦虑怎么办",
            "最近总是焦虑怎么办",
            "睡前脑子停不下来",
            "PTSD是啥",
            "创伤后应激障碍是什么",
            "OCD是什么",
            "CBT有用吗",
            "ADHD是啥",
        ):
            with self.subTest(question=question):
                self.assertEqual(knowledge_service._classify_knowledge_scope(question), "in_scope")

    async def test_out_of_scope_response_does_not_record_gap(self) -> None:
        for question in ("打飞机啥意思", "帮我写代码", "今天股票怎么样"):
            with self.subTest(question=question):
                response = await knowledge_service.ask_knowledge(
                    NoDatabaseAccess(),
                    question=question,
                    use_my_context=False,
                    thread_id="thread-1",
                )

                self.assertEqual(response.scope_status, "out_of_scope")
                self.assertEqual(response.coverage_status, "not_applicable")
                self.assertIsNone(response.gap_id)
                self.assertEqual(response.related_articles, [])
                self.assertEqual(response.source_refs, [])

    async def test_distress_context_keeps_sexual_term_in_scope(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        original_api_key = knowledge_service.deepseek_client.api_key
        knowledge_service.deepseek_client.api_key = None

        try:
            with Session() as db:
                response = await knowledge_service.ask_knowledge(
                    db,
                    question="我因为频繁自慰很焦虑怎么办",
                    use_my_context=False,
                    thread_id="thread-1",
                )
        finally:
            knowledge_service.deepseek_client.api_key = original_api_key

        self.assertEqual(response.scope_status, "in_scope")

    async def test_crisis_risk_overrides_scope_rejection(self) -> None:
        response = await knowledge_service.ask_knowledge(
            NoDatabaseAccess(),
            question="帮我写代码，我今晚想自杀",
            use_my_context=False,
            thread_id="thread-1",
        )

        self.assertEqual(response.risk_level, "L3")
        self.assertEqual(response.scope_status, "in_scope")
        self.assertEqual(response.continue_chat_payload.context_type, "safety_escalation")

    async def test_in_scope_insufficient_coverage_records_gap(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

        with Session() as db:
            response = await knowledge_service.ask_knowledge(
                db,
                question="我对蓝色杯子有奇怪恐惧怎么办",
                use_my_context=False,
                thread_id="thread-1",
            )
            gaps = list(db.scalars(select(KnowledgeGap)))

        self.assertEqual(response.scope_status, "in_scope")
        self.assertEqual(response.coverage_status, "insufficient")
        self.assertIsNotNone(response.gap_id)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].question, "我对蓝色杯子有奇怪恐惧怎么办")

    async def test_ptsd_question_has_knowledge_answer(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        original_api_key = knowledge_service.deepseek_client.api_key
        knowledge_service.deepseek_client.api_key = None

        try:
            with Session() as db:
                response = await knowledge_service.ask_knowledge(
                    db,
                    question="PTSD是啥",
                    use_my_context=False,
                    thread_id="thread-1",
                )
                gaps = list(db.scalars(select(KnowledgeGap)))
        finally:
            knowledge_service.deepseek_client.api_key = original_api_key

        self.assertEqual(response.scope_status, "in_scope")
        self.assertEqual(response.coverage_status, "sufficient")
        self.assertIsNone(response.gap_id)
        self.assertEqual(gaps, [])
        self.assertTrue(any(item.slug == "ptsd-basics" for item in response.related_articles))

    def test_synonym_queries_hit_expected_articles(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

        cases = {
            "睡不着怎么办": "sleep-rumination",
            "失眠怎么办": "sleep-rumination",
            "心慌怎么办": "panic-attack-basics",
            "惊恐怎么办": "panic-attack-basics",
            "内耗怎么办": "rumination-loop",
            "反刍怎么办": "rumination-loop",
        }
        with Session() as db:
            for question, expected_slug in cases.items():
                with self.subTest(question=question):
                    hits = knowledge_service._search_chunk_hits(db, query=question, limit=3)

                    self.assertTrue(hits)
                    self.assertEqual(hits[0].article.slug, expected_slug)

    async def test_model_boundary_override_updates_response_scope(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        original_api_key = knowledge_service.deepseek_client.api_key
        original_chat = knowledge_service.deepseek_client.chat
        captured_system_prompt = ""

        async def fake_chat(messages, **kwargs):
            nonlocal captured_system_prompt
            captured_system_prompt = messages[0]["content"]
            return """
            {
              "scope_status": "out_of_scope",
              "summary_30s": "抱歉，这个问题不属于心理健康知识问答范围。",
              "explanation_3min": "这里主要回答情绪、压力、睡眠、关系、自我理解和求助边界相关的问题。如果这个词或场景让你感到困扰，可以描述你的具体感受，我可以从心理支持角度陪你整理。",
              "actions": [],
              "seek_help_when": []
            }
            """

        knowledge_service.deepseek_client.api_key = "test-key"
        knowledge_service.deepseek_client.chat = fake_chat

        try:
            with Session() as db:
                response = await knowledge_service.ask_knowledge(
                    db,
                    question="焦虑是什么",
                    use_my_context=False,
                    thread_id="thread-1",
                )
                gaps = list(db.scalars(select(KnowledgeGap)))
        finally:
            knowledge_service.deepseek_client.api_key = original_api_key
            knowledge_service.deepseek_client.chat = original_chat

        self.assertIn("不要回答泛百科", captured_system_prompt)
        self.assertIn("scope_status", captured_system_prompt)
        self.assertEqual(response.scope_status, "out_of_scope")
        self.assertEqual(response.coverage_status, "not_applicable")
        self.assertIsNone(response.gap_id)
        self.assertEqual(response.related_articles, [])
        self.assertEqual(response.source_refs, [])
        self.assertEqual(gaps, [])


if __name__ == "__main__":
    unittest.main()
