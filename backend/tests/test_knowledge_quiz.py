from __future__ import annotations

import unittest

from app.services.knowledge_quiz_service import (
    QUIZ_BANK,
    _select_questions,
    get_knowledge_quiz_bank_stats,
    start_knowledge_quiz,
    submit_knowledge_quiz,
)
from app.schemas.knowledge import SubmitKnowledgeQuizAnswer


class KnowledgeQuizTests(unittest.TestCase):
    def test_quiz_bank_has_2000_questions_with_expected_type_mix(self) -> None:
        stats = get_knowledge_quiz_bank_stats()

        self.assertEqual(stats.total, 2000)
        self.assertEqual(len(stats.by_topic), 50)
        self.assertEqual(stats.by_type["single_choice"], 1200)
        self.assertEqual(stats.by_type["true_false"], 500)
        self.assertEqual(stats.by_type["image"], 300)

    def test_start_quiz_uses_mode_type_ratios(self) -> None:
        expected = {
            "10": {"single_choice": 7, "true_false": 2, "image": 1},
            "50": {"single_choice": 32, "true_false": 13, "image": 5},
            "100": {"single_choice": 65, "true_false": 25, "image": 10},
        }

        for mode, counts in expected.items():
            with self.subTest(mode=mode):
                session = start_knowledge_quiz(mode)
                actual = {question_type: 0 for question_type in counts}
                for question in session.questions:
                    actual[question.type] += 1

                self.assertEqual(session.total, int(mode))
                self.assertEqual(actual, counts)
                self.assertTrue(session.session_id.startswith(f"knowledge-quiz:{mode}:"))

    def test_single_and_image_options_are_not_reused_as_fixed_sets(self) -> None:
        questions = [question for question in _select_questions("10", "option-diversity") if question.type != "true_false"]
        option_sets = [tuple(text for _, text in question.options) for question in questions]

        self.assertEqual(len(option_sets), len(set(option_sets)))
        for options in option_sets:
            self.assertEqual(len(options), len(set(options)))

    def test_misconception_questions_have_clear_wrong_statement_answer(self) -> None:
        misconception_questions = [question for question in QUIZ_BANK if "哪一种说法更需要避免" in question.stem]

        self.assertTrue(misconception_questions)
        for question in misconception_questions:
            correct_text = dict(question.options)[question.correct_answer]
            self.assertTrue(correct_text.startswith(("把", "认为", "觉得")))

    def test_submit_quiz_scores_reconstructed_session(self) -> None:
        session = start_knowledge_quiz("10")
        _, mode, seed = session.session_id.split(":")
        answer_key = {question.question_id: question.correct_answer for question in _select_questions(mode, seed)}

        result = submit_knowledge_quiz(
            session.session_id,
            [
                SubmitKnowledgeQuizAnswer(question_id=question.question_id, answer=answer_key[question.question_id])
                for question in session.questions
            ],
        )

        self.assertEqual(result.correct, 10)
        self.assertEqual(result.accuracy, 1)
        self.assertTrue(all(item.is_correct for item in result.review))
        self.assertEqual(result.review[0].question.question_id, result.review[0].question_id)
        self.assertTrue(result.review[0].question.stem)
        self.assertTrue(result.review[0].question.options)

    def test_100_question_titles_use_score_bands(self) -> None:
        session = start_knowledge_quiz("100")
        _, mode, seed = session.session_id.split(":")
        questions = _select_questions(mode, seed)
        correct_answers = [
            SubmitKnowledgeQuizAnswer(question_id=question.question_id, answer=question.correct_answer)
            for question in questions[:85]
        ]

        result = submit_knowledge_quiz(session.session_id, correct_answers)

        self.assertEqual(result.correct, 85)
        self.assertEqual(result.title, "稳定支持官")

    def test_submit_rejects_invalid_session(self) -> None:
        with self.assertRaises(ValueError):
            submit_knowledge_quiz("bad-session", [])


if __name__ == "__main__":
    unittest.main()
