"""Tests for voice_parser."""

import unittest
from datetime import date

import voice_parser as vp


class VoiceParserTests(unittest.TestCase):
    TODAY = date(2026, 6, 11)  # Thursday

    def test_full_phrase(self) -> None:
        result = vp.process_voice(
            "Urgent call the dentist tomorrow",
            today=self.TODAY,
        )
        self.assertEqual(result["draft"]["title"], "call the dentist")
        self.assertEqual(result["draft"]["priority"], "urgent")
        self.assertEqual(result["draft"]["due_date"], "2026-06-12")
        self.assertTrue(result["ready"])

    def test_remind_me_strips_prefix(self) -> None:
        result = vp.process_voice(
            "Remind me to buy milk",
            today=self.TODAY,
        )
        self.assertEqual(result["draft"]["title"], "buy milk")
        self.assertEqual(result["pending_field"], "due_date")

    def test_backlog_status(self) -> None:
        result = vp.process_voice(
            "Someday learn Rust",
            today=self.TODAY,
        )
        self.assertEqual(result["draft"]["status"], "backlog")

    def test_follow_up_due_date(self) -> None:
        first = vp.process_voice("Finish quarterly report", today=self.TODAY)
        state = vp.state_from_response(first)
        second = vp.process_voice(
            "Friday",
            draft=state,
            pending_field=first["pending_field"],
            today=self.TODAY,
        )
        self.assertEqual(second["draft"]["due_date"], "2026-06-12")

    def test_follow_up_no_due_date(self) -> None:
        first = vp.process_voice("Walk the dog", today=self.TODAY)
        state = vp.state_from_response(first)
        second = vp.process_voice(
            "No due date",
            draft=state,
            pending_field="due_date",
            today=self.TODAY,
        )
        self.assertIsNone(second["draft"]["due_date"])
        self.assertNotEqual(second["pending_field"], "due_date")

    def test_priority_follow_up(self) -> None:
        draft = vp._normalize_draft({"title": "Email client", "due_date_declined": True, "due_date_asked": True})
        result = vp.process_voice(
            "High",
            draft=draft,
            pending_field="priority",
            today=self.TODAY,
        )
        self.assertEqual(result["draft"]["priority"], "high")


if __name__ == "__main__":
    unittest.main()
