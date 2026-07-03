import unittest

from services.vessel_context import vessel_context_block
from services.vessel_scanner import VesselProfile, identify_hardware_tool_gaps


def _profile(capabilities, devices=None):
    return VesselProfile(
        schema_version="vessel_profile.v1",
        vessel_id="unit-vessel",
        generated_at="2026-06-03T00:00:00+00:00",
        active_probe=False,
        platform={"system": "UnitOS", "machine": "test"},
        hardware={"cpu_count": 4, "ram_bytes": 1024, "gpu_count": 0},
        devices=devices or [],
        capabilities=capabilities,
        tool_expectations=[],
        warnings=[],
    )


class VesselScannerContractTests(unittest.TestCase):
    def test_serial_capability_creates_motor_control_gap(self):
        profile = _profile(
            ["compute.local_cpu", "bus.serial", "actuator.motor_control_candidate"],
            devices=[{"kind": "serial", "name": "COM7", "path": "COM7"}],
        )

        gaps = identify_hardware_tool_gaps(profile, tool_names=["capture_screenshot"])

        serial_gaps = [g for g in gaps if g["hardware_capability"] == "bus.serial"]
        self.assertEqual(len(serial_gaps), 1)
        self.assertEqual(serial_gaps[0]["type"], "hardware_gap")
        self.assertEqual(serial_gaps[0]["suggested_name"], "move_servo")
        self.assertTrue(serial_gaps[0]["commissioning_required"])
        self.assertIn("COM7", serial_gaps[0]["evidence"])

    def test_existing_screen_tools_satisfy_screen_expectations(self):
        profile = _profile(["compute.local_cpu", "sensor.screen"])

        gaps = identify_hardware_tool_gaps(
            profile,
            tool_names=["capture_screenshot", "ocr_read_screen"],
        )

        self.assertFalse([g for g in gaps if g["hardware_capability"] == "sensor.screen"])

    def test_vessel_context_block_is_prompt_safe_and_mentions_boundaries(self):
        block = vessel_context_block(
            _profile(
                ["compute.local_cpu", "sensor.screen"],
                devices=[
                    {"kind": "camera", "name": "Unit Camera"},
                    {"kind": "audio_input", "name": "Unit Mic"},
                ],
            )
        )

        self.assertIn("VESSEL PROFILE / Runtime Hardware Identity", block)
        self.assertIn("unit-vessel", block)
        self.assertIn("current_location: none_saved", block)
        self.assertIn("devices_sample_by_kind:", block)
        self.assertIn("- camera: Unit Camera", block)
        self.assertIn("- audio_input: Unit Mic", block)
        self.assertIn("hardware detection is evidence, not permission", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
