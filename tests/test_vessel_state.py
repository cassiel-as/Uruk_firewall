import tempfile
import unittest
from pathlib import Path

from services.vessel_state import (
    add_calendar_event,
    add_note,
    context_summary,
    delete_note,
    list_calendar_events,
    load_state,
    set_location,
)


class VesselStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_location_is_validated_and_persisted(self):
        state = set_location(
            lat=22.3,
            lon=114.1,
            label="lab",
            source="unit",
            confidence=0.8,
            data_dir=self.data_dir,
        )

        self.assertEqual(state["location"]["label"], "lab")
        self.assertEqual(state["location"]["lat"], 22.3)
        self.assertEqual(state["location_history"][0]["source"], "unit")
        self.assertEqual(load_state(self.data_dir)["location"]["lon"], 114.1)

    def test_location_rejects_invalid_latitude(self):
        with self.assertRaises(ValueError):
            set_location(lat=100, lon=0, data_dir=self.data_dir)

    def test_notes_can_be_added_and_deleted(self):
        state = add_note(
            title="Camera commissioned",
            body="capture test passed",
            source="unit",
            data_dir=self.data_dir,
        )
        note_id = state["notes"][0]["id"]

        self.assertEqual(state["notes"][0]["title"], "Camera commissioned")
        self.assertEqual(state["notes"][0]["source"], "unit")

        state = delete_note(note_id, data_dir=self.data_dir)

        self.assertEqual(state["notes"], [])

    def test_calendar_events_are_sorted_and_summarized(self):
        add_calendar_event(title="Later", start="2026-06-04T10:00", source="unit", data_dir=self.data_dir)
        add_calendar_event(title="Sooner", start="2026-06-03T10:00", location="lab", data_dir=self.data_dir)

        events = list_calendar_events(data_dir=self.data_dir)
        summary = context_summary(self.data_dir)

        self.assertEqual([e["title"] for e in events], ["Sooner", "Later"])
        self.assertEqual(summary["upcoming_events"][0]["title"], "Sooner")
        self.assertEqual(summary["upcoming_events"][0]["location"], "lab")


if __name__ == "__main__":
    unittest.main(verbosity=2)
