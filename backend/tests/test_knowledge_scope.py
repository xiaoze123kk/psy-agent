from __future__ import annotations

import unittest
from dataclasses import replace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, KnowledgeArticle, KnowledgeGap
from app.services import knowledge_service
from app.services.knowledge_seed_expansion import BULK_COMMON_TOPIC_ARTICLES


class NoDatabaseAccess:
    def __getattr__(self, name: str):
        raise AssertionError(f"knowledge DB should not be accessed for this path: {name}")


class KnowledgeScopeTests(unittest.IsolatedAsyncioTestCase):
    def test_bulk_common_topic_articles_import_exactly_100(self) -> None:
        bulk_slugs = {str(article["slug"]) for article in BULK_COMMON_TOPIC_ARTICLES}

        self.assertEqual(len(BULK_COMMON_TOPIC_ARTICLES), 100)
        self.assertEqual(len(bulk_slugs), 100)
        self.assertIn("bulk-depression-anhedonia", bulk_slugs)
        self.assertIn("bulk-eating-cooccurring", bulk_slugs)
        self.assertNotIn("bulk-psychosis-basics", bulk_slugs)

    def test_bulk_common_topic_articles_seed_into_database(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        expected_slugs = {str(article["slug"]) for article in BULK_COMMON_TOPIC_ARTICLES}

        with Session() as db:
            knowledge_service.ensure_seed_articles(db)
            seeded_slugs = set(
                db.scalars(select(KnowledgeArticle.slug).where(KnowledgeArticle.slug.in_(expected_slugs)))
            )

        self.assertEqual(seeded_slugs, expected_slugs)

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
            "怒火是怎么形成的",
            "愤怒怎么办",
            "控制不住发脾气怎么办",
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

    async def test_known_typo_question_is_answered_with_guess(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        original_api_key = knowledge_service.deepseek_client.api_key
        knowledge_service.deepseek_client.api_key = None

        try:
            with Session() as db:
                response = await knowledge_service.ask_knowledge(
                    db,
                    question="焦绿怎么办",
                    use_my_context=False,
                    thread_id="thread-1",
                )
                gaps = list(db.scalars(select(KnowledgeGap)))
        finally:
            knowledge_service.deepseek_client.api_key = original_api_key

        self.assertEqual(response.scope_status, "in_scope")
        self.assertEqual(response.coverage_status, "sufficient")
        self.assertIsNotNone(response.question_suggestion)
        self.assertEqual(response.question_suggestion.guessed_question, "焦虑怎么办")
        self.assertEqual(response.question_suggestion.matched_term, "焦虑")
        self.assertEqual(gaps, [])

    async def test_fuzzy_typo_question_uses_guessed_knowledge_topic(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        original_api_key = knowledge_service.deepseek_client.api_key
        knowledge_service.deepseek_client.api_key = None

        try:
            with Session() as db:
                response = await knowledge_service.ask_knowledge(
                    db,
                    question="社交娇虑怎么办",
                    use_my_context=False,
                    thread_id="thread-1",
                )
                gaps = list(db.scalars(select(KnowledgeGap)))
        finally:
            knowledge_service.deepseek_client.api_key = original_api_key

        self.assertEqual(response.scope_status, "in_scope")
        self.assertEqual(response.coverage_status, "sufficient")
        self.assertIsNotNone(response.question_suggestion)
        self.assertEqual(response.question_suggestion.guessed_question, "社交焦虑怎么办")
        self.assertEqual(response.question_suggestion.matched_term, "社交焦虑")
        self.assertEqual(response.related_articles[0].slug, "social-anxiety")
        self.assertEqual(gaps, [])

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
                question="自尊和梦境颜色有关吗",
                use_my_context=False,
                thread_id="thread-1",
            )
            gaps = list(db.scalars(select(KnowledgeGap)))

        self.assertEqual(response.scope_status, "in_scope")
        self.assertEqual(response.coverage_status, "insufficient")
        self.assertIsNotNone(response.gap_id)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].question, "自尊和梦境颜色有关吗")

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
            "睡不着怎么办": "medlineplus-insomnia-basics",
            "失眠怎么办": "medlineplus-insomnia-basics",
            "心慌怎么办": "panic-attack-basics",
            "惊恐怎么办": "panic-attack-basics",
            "内耗怎么办": "rumination-loop",
            "反刍怎么办": "rumination-loop",
        }
        with Session() as db:
            for question, expected_slug in cases.items():
                with self.subTest(question=question):
                    hits = knowledge_service._search_chunk_hits(db, query=question, limit=3)
                    hit_slugs = [hit.article.slug for hit in hits]

                    self.assertTrue(hits)
                    self.assertIn(expected_slug, hit_slugs)

    def test_bulk_common_topic_queries_hit_expected_articles(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

        cases = {
            "对什么都没兴趣": "bulk-depression-anhedonia",
            "总是担心很多事": "bulk-anxiety-gad-worry",
            "社交后反复复盘": "bulk-social-anxiety-after-review",
            "反复检查门锁": "bulk-ocd-checking",
            "ADHD 时间感差": "bulk-adhd-time-blindness",
            "睡眠卫生": "bulk-sleep-hygiene",
            "暴食发作": "bulk-eating-binge",
            "怒火是怎么形成的": "bulk-bpd-anger",
            "控制不住发脾气怎么办": "bulk-bpd-anger",
        }
        with Session() as db:
            for question, expected_slug in cases.items():
                with self.subTest(question=question):
                    hits = knowledge_service._search_chunk_hits(db, query=question, limit=5)
                    hit_slugs = [hit.article.slug for hit in hits]

        self.assertIn(expected_slug, hit_slugs)

    async def test_high_confidence_answer_skips_model_by_default(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        original_api_key = knowledge_service.deepseek_client.api_key
        original_chat = knowledge_service.deepseek_client.chat

        async def fail_if_called(messages, **kwargs):
            raise AssertionError("knowledge answer should use fast deterministic path by default")

        knowledge_service.deepseek_client.api_key = "test-key"
        knowledge_service.deepseek_client.chat = fail_if_called

        try:
            with Session() as db:
                response = await knowledge_service.ask_knowledge(
                    db,
                    question="什么是边界感",
                    use_my_context=False,
                    thread_id="thread-1",
                )
        finally:
            knowledge_service.deepseek_client.api_key = original_api_key
            knowledge_service.deepseek_client.chat = original_chat

        self.assertEqual(response.scope_status, "in_scope")
        self.assertEqual(response.coverage_status, "sufficient")
        self.assertEqual(response.confidence, "high")

    async def test_model_boundary_override_updates_response_scope(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        original_settings = knowledge_service.settings
        original_api_key = knowledge_service.deepseek_client.api_key
        original_chat = knowledge_service.deepseek_client.chat
        captured_system_prompt = ""
        captured_kwargs: dict[str, object] = {}

        async def fake_chat(messages, **kwargs):
            nonlocal captured_system_prompt, captured_kwargs
            captured_system_prompt = messages[0]["content"]
            captured_kwargs = kwargs
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
        knowledge_service.settings = replace(original_settings, knowledge_llm_answers_enabled=True)

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
            knowledge_service.settings = original_settings
            knowledge_service.deepseek_client.api_key = original_api_key
            knowledge_service.deepseek_client.chat = original_chat

        self.assertIn("不要回答泛百科", captured_system_prompt)
        self.assertIn("scope_status", captured_system_prompt)
        self.assertEqual(captured_kwargs["model"], "deepseek-v4-pro")
        self.assertEqual(captured_kwargs["temperature"], original_settings.deepseek_knowledge_temperature)
        self.assertEqual(captured_kwargs["max_tokens"], original_settings.deepseek_knowledge_max_tokens)
        self.assertEqual(response.scope_status, "out_of_scope")
        self.assertEqual(response.coverage_status, "not_applicable")
        self.assertIsNone(response.gap_id)
        self.assertEqual(response.related_articles, [])
        self.assertEqual(response.source_refs, [])
        self.assertEqual(gaps, [])


if __name__ == "__main__":
    unittest.main()
