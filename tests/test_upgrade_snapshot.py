from pathlib import Path
import json

from services.upgrade_snapshot import build_upgrade_snapshot, create_upgrade_snapshot, diff_upgrade_snapshot


def test_upgrade_snapshot_diff_detects_changed_added_removed_files(tmp_path):
    root = Path(tmp_path)
    watched = root / "watched"
    watched.mkdir()
    changed = watched / "changed.txt"
    removed = watched / "removed.txt"
    changed.write_text("before\n", encoding="utf-8")
    removed.write_text("delete me\n", encoding="utf-8")

    snapshot = build_upgrade_snapshot(
        plan_id="unit",
        root=root,
        tracked_paths=["watched"],
    )

    changed.write_text("after\n", encoding="utf-8")
    removed.unlink()
    (watched / "added.txt").write_text("new\n", encoding="utf-8")

    diff = diff_upgrade_snapshot(snapshot, root=root)

    assert diff["changed"] == ["watched/changed.txt"]
    assert diff["added"] == ["watched/added.txt"]
    assert diff["removed"] == ["watched/removed.txt"]
    assert diff["changed_count"] == 1
    assert diff["added_count"] == 1
    assert diff["removed_count"] == 1
    assert diff["clean"] is False


def test_create_upgrade_snapshot_writes_manifest(tmp_path):
    root = Path(tmp_path)
    (root / "app.py").write_text("print('ok')\n", encoding="utf-8")
    out = root / "snapshots"

    snapshot = create_upgrade_snapshot(
        plan_id="unit-plan",
        root=root,
        output_dir=out,
        tracked_paths=["app.py"],
    )

    path = Path(snapshot["path"])
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["path"] == str(path)
    assert snapshot["file_count"] == 1
    assert len(snapshot["aggregate_sha256"]) == 64


def test_upgrade_snapshot_diff_clean_when_files_unchanged(tmp_path):
    root = Path(tmp_path)
    (root / "app.py").write_text("print('ok')\n", encoding="utf-8")
    snapshot = build_upgrade_snapshot(
        plan_id="unit-clean",
        root=root,
        tracked_paths=["app.py"],
    )

    diff = diff_upgrade_snapshot(snapshot, root=root)

    assert diff["clean"] is True
    assert diff["changed_count"] == 0
    assert diff["added_count"] == 0
    assert diff["removed_count"] == 0
