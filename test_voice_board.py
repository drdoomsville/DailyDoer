"""Tests for voice_board command parsing."""

import unittest

import voice_board as vb


SAMPLE_TODOS = [
    {"id": 1, "title": "Call dentist", "status": "backlog", "priority": "normal", "due_date": None},
    {"id": 2, "title": "Call dentist office", "status": "todo", "priority": "high", "due_date": None},
    {"id": 3, "title": "Buy milk", "status": "todo", "priority": "normal", "due_date": None},
    {"id": 4, "title": "Finish quarterly report", "status": "in_progress", "priority": "urgent", "due_date": None},
]


class VoiceBoardTests(unittest.TestCase):
    def test_move_needs_confirm(self) -> None:
        result = vb.process_board_command("Move call dentist to in progress", SAMPLE_TODOS)
        self.assertTrue(result["ok"])
        self.assertTrue(result["needs_confirm"])
        self.assertEqual(result["confirm"]["todo"]["id"], 1)
        self.assertIn("Say yes or no", result["message"])

    def test_delete_needs_confirm(self) -> None:
        result = vb.process_board_command("Delete buy milk", SAMPLE_TODOS)
        self.assertTrue(result["needs_confirm"])
        self.assertEqual(result["confirm"]["action"], "delete")

    def test_delete_a_task_phrasing(self) -> None:
        result = vb.process_board_command("Delete a task buy milk", SAMPLE_TODOS)
        self.assertTrue(result["needs_confirm"])
        self.assertEqual(result["confirm"]["todo"]["id"], 3)

    def test_yes_executes(self) -> None:
        first = vb.process_board_command("Delete buy milk", SAMPLE_TODOS)
        second = vb.process_board_command(
            "yes",
            SAMPLE_TODOS,
            awaiting_confirm=first["confirm"],
        )
        self.assertTrue(second["executed"])
        self.assertEqual(second["action"], "delete")

    def test_no_cancels(self) -> None:
        first = vb.process_board_command("Delete buy milk", SAMPLE_TODOS)
        second = vb.process_board_command(
            "no",
            SAMPLE_TODOS,
            awaiting_confirm=first["confirm"],
        )
        self.assertTrue(second["cancelled"])

    def test_ambiguous(self) -> None:
        result = vb.process_board_command("Move dentist to backlog", SAMPLE_TODOS)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "ambiguous")

    def test_not_found(self) -> None:
        result = vb.process_board_command("Move walk the dog to todo", SAMPLE_TODOS)
        self.assertEqual(result["error"], "not_found")


if __name__ == "__main__":
    unittest.main()
