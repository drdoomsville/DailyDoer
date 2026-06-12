"""Tests for voice_edit command parsing."""

import unittest
from datetime import date

import voice_edit as ve

SAMPLE_TODOS = [
    {"id": 1, "title": "Call dentist", "status": "backlog", "priority": "normal", "due_date": None},
    {"id": 3, "title": "Buy milk", "status": "todo", "priority": "normal", "due_date": "2026-06-10"},
]


class VoiceEditTests(unittest.TestCase):
    def test_start_edit_finds_task(self) -> None:
        result = ve.process_edit_command("edit buy milk", SAMPLE_TODOS)
        self.assertTrue(result["ok"])
        self.assertEqual(result["edit_session"]["todo"]["id"], 3)
        self.assertIn("Editing", result["message"])

    def test_set_priority(self) -> None:
        start = ve.process_edit_command("edit buy milk", SAMPLE_TODOS)
        session = start["edit_session"]
        result = ve.process_edit_command(
            "set priority to urgent",
            SAMPLE_TODOS,
            edit_session=session,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["edit_session"]["changes"]["priority"], "urgent")

    def test_set_due_date(self) -> None:
        start = ve.process_edit_command("edit buy milk", SAMPLE_TODOS)
        session = start["edit_session"]
        result = ve.process_edit_command(
            "set due date to tomorrow",
            SAMPLE_TODOS,
            edit_session=session,
            today=date(2026, 6, 11),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["edit_session"]["changes"]["due_date"], "2026-06-12")

    def test_save_needs_confirm(self) -> None:
        start = ve.process_edit_command("edit buy milk", SAMPLE_TODOS)
        session = start["edit_session"]
        session = ve.process_edit_command(
            "set priority to high",
            SAMPLE_TODOS,
            edit_session=session,
        )["edit_session"]
        result = ve.process_edit_command("save", SAMPLE_TODOS, edit_session=session)
        self.assertTrue(result["needs_save_confirm"])
        self.assertIn("Say yes or no", result["message"])

    def test_yes_on_save_confirm(self) -> None:
        start = ve.process_edit_command("edit buy milk", SAMPLE_TODOS)
        session = start["edit_session"]
        session = ve.process_edit_command(
            "set status to urgent",
            SAMPLE_TODOS,
            edit_session=session,
        )["edit_session"]
        pending = ve.process_edit_command("save", SAMPLE_TODOS, edit_session=session)
        result = ve.process_edit_command(
            "yes",
            SAMPLE_TODOS,
            awaiting_save=pending["awaiting_save"],
        )
        self.assertTrue(result["save"])
        self.assertEqual(result["fields"]["priority"], "urgent")

    def test_not_found(self) -> None:
        result = ve.process_edit_command("edit walk the dog", SAMPLE_TODOS)
        self.assertEqual(result["error"], "not_found")


if __name__ == "__main__":
    unittest.main()
