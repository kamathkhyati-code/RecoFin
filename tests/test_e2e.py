import os
import tempfile

from recon_platform.e2e import run_e2e_smoke_test


def test_e2e_stub_traversal_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "e2e_checkpoints.db")
        output_dir = os.path.join(tmp, "eval_reports")

        summary = run_e2e_smoke_test(db_path, output_dir)

        assert summary["paused_before_resolution"] is True
        assert summary["review_item_registered"] is True
        assert summary["run_completed"] is True
        assert summary["review_item_resolved"] is True
        assert summary["resumable"] is True
        assert summary["checkpoint_history_length"] > 1

        assert os.path.exists(summary["eval_json_report"])
        assert os.path.exists(summary["eval_md_report"])
