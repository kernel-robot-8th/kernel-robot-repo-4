import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import trainer  # noqa: E402
from core.config import DEFAULTS  # noqa: E402


class BuildCommandTest(unittest.TestCase):
    def test_new_run(self):
        cmd = trainer.build_command(DEFAULTS["train"], Path("/d/success"), "local/t_success", Path("/o/act_1"))
        self.assertEqual(cmd[1:3], ["-m", "lerobot.scripts.lerobot_train"])
        for arg in (
            "--dataset.repo_id=local/t_success",
            "--dataset.root=/d/success",
            "--policy.type=act",
            "--policy.device=cuda",
            "--policy.push_to_hub=false",
            "--output_dir=/o/act_1",
            "--job_name=act_1",
            "--steps=100000",
            "--batch_size=8",
            "--wandb.enable=false",
        ):
            self.assertIn(arg, cmd)

    def test_resume(self):
        cmd = trainer.build_command(DEFAULTS["train"], None, "", Path("/o/act_1"), resume_from=Path("/o/act_1"))
        self.assertEqual(
            cmd[3:],
            ["--config_path=/o/act_1/checkpoints/last/pretrained_model/train_config.json", "--resume=true"],
        )


class ParseLogLineTest(unittest.TestCase):
    def test_metrics_line(self):
        line = "INFO 2026-10-26 12:00:00 ot_train.py:435 step:1K smpl:8K ep:20 epch:0.50 loss:0.123 grdn:1.2 lr:1.0e-05"
        self.assertEqual(trainer.parse_log_line(line), {"step": 1000, "loss": 0.123, "epoch": 0.5})

    def test_suffix_and_plain(self):
        self.assertEqual(trainer.parse_log_line("step:2.5M smpl:1 loss:1e-03")["step"], 2_500_000)
        self.assertEqual(trainer.parse_log_line("step:200 smpl:1K loss:0.5")["step"], 200)

    def test_unrelated_lines(self):
        self.assertIsNone(trainer.parse_log_line("cfg.steps=100000 (100K)"))
        self.assertIsNone(trainer.parse_log_line("Checkpoint policy after step 200"))


class EmitLineTest(unittest.TestCase):
    def test_tqdm_kept_out_of_log(self):
        t = trainer.Trainer(Path("."))
        t._emit_line("Training:  25%|##5       | 5/20 [00:01<00:03,  4.10step/s]")
        t._emit_line("INFO step:5 smpl:20 ep:1 epch:0.25 loss:1.5")
        kinds = [t.events.get_nowait()[0] for _ in range(t.events.qsize())]
        self.assertEqual(kinds, ["train_tqdm", "train_log", "train_progress"])

    def test_metrics_glued_to_tqdm(self):
        t = trainer.Trainer(Path("."))
        bar = "Training:  50%|#####     | 5/10 [00:01<00:00,  6.14step/s]"
        t._emit_line(bar + "INFO ot_train.py:435 step:5 smpl:20 epch:0.25 loss:50.148")
        events = [t.events.get_nowait() for _ in range(t.events.qsize())]
        self.assertEqual(events[0], ("train_tqdm", bar))
        self.assertTrue(events[1][1].startswith("INFO"))
        self.assertEqual(events[2], ("train_progress", {"step": 5, "loss": 50.148, "epoch": 0.25}))


class DatasetTest(unittest.TestCase):
    def test_episode_count(self):
        with tempfile.TemporaryDirectory() as d:
            root = trainer.dataset_root(Path(d))
            self.assertEqual(trainer.episode_count(root), 0)
            (root / "meta").mkdir(parents=True)
            (root / "meta" / "info.json").write_text(json.dumps({"total_episodes": 0}))
            self.assertEqual(trainer.episode_count(root), 0)
            (root / "meta" / "info.json").write_text(json.dumps({"total_episodes": 7}))
            self.assertEqual(trainer.episode_count(root), 7)

    def test_latest_run_needs_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(trainer.latest_run(Path(d)))
            data = Path(d) / "success"
            self.assertIsNone(trainer.latest_run(data))
            run = trainer.train_dir_for(data) / "act_1"
            run.mkdir(parents=True)
            self.assertIsNone(trainer.latest_run(data))
            cfg = trainer.resume_config(run)
            cfg.parent.mkdir(parents=True)
            cfg.write_text("{}")
            self.assertEqual(trainer.latest_run(data), run)

    def test_paths_follow_dataset(self):
        data = Path("/data/shoe box/success")
        self.assertEqual(trainer.train_dir_for(data), Path("/data/shoe box/train"))
        self.assertEqual(trainer.run_dir(data, "act").parent, Path("/data/shoe box/train"))
        self.assertEqual(trainer.default_repo_id(data), "local/shoe_box_success")


if __name__ == "__main__":
    unittest.main()
