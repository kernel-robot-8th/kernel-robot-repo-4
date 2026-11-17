import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import trainer  # noqa: E402

OMX_DIR = Path(__file__).resolve().parents[2] / "omx_train"


class TrainScriptTest(unittest.TestCase):
    """Reads the real omx_train scripts, so the dashboard notices when train.sh changes shape."""

    def test_defaults_come_from_train_sh(self):
        act = trainer.script_defaults(trainer.train_script(OMX_DIR, "act"))
        self.assertEqual(set(act), set(trainer.PARAMS))
        self.assertEqual(act["batch_size"], 16)
        smol = trainer.script_defaults(trainer.train_script(OMX_DIR, "smolvla"))
        self.assertEqual(smol["batch_size"], 64)

    def test_commented_options_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            sh = Path(d) / "train.sh"
            sh.write_text("ARGS=(\n  # --steps=5\n  --steps=7   # note\n  --batch_size=3\n  --log_freq=x\n)\n")
            self.assertEqual(trainer.script_defaults(sh), {"steps": 7, "batch_size": 3})

    def test_image_name(self):
        self.assertEqual(trainer.image_name(OMX_DIR, "act"), "omx-act:0.6.1")
        self.assertEqual(trainer.image_name(OMX_DIR, "smolvla"), "omx-smolvla:0.6.1")


class BuildCommandTest(unittest.TestCase):
    def test_new_run(self):
        args = trainer.overrides({"steps": 20, "batch_size": 4}, image_aug=True, wandb=False) + ["--seed=7"]
        argv, env = trainer.build_train(OMX_DIR, "act", 1, Path("/d/shoe/success"), "shoe_act_1", [0, 2], args)
        self.assertEqual(argv[:3], ["bash", str(OMX_DIR / "ACT" / "train.sh"), "1"])
        self.assertEqual(
            argv[3:],
            ["--steps=20", "--batch_size=4", "--dataset.image_transforms.enable=true", "--wandb.enable=false", "--seed=7"],
        )
        self.assertEqual(env["DATA_DIR"], "/d/shoe")
        self.assertEqual(env["DATASET"], "success")
        self.assertEqual(env["JOB_NAME"], "shoe_act_1")
        self.assertEqual(env["EPISODES"], "[0,2]")
        self.assertEqual(env["DETACH"], "1")
        self.assertEqual(env["KEEP_STEPS"], "")

    def test_every_episode_is_empty(self):
        _, env = trainer.build_train(OMX_DIR, "smolvla", 0, Path("/d/x"), "j", None, [])
        # empty, not unset: SmolVLA's train.sh otherwise falls back to its box_merged holdout list
        self.assertEqual(env["EPISODES"], "")

    def test_resume_restores_dataset_from_meta(self):
        with tempfile.TemporaryDirectory() as d:
            omx = Path(d)
            run = trainer.outputs_dir(omx, "act") / "job1"
            run.mkdir(parents=True)
            trainer.run_meta_path(omx, "act", "job1").write_text(json.dumps({"dataset_root": "/rec/shoe/success"}))
            argv, env = trainer.build_resume(omx, "act", 0, run, ["--steps=50"])
            self.assertEqual(argv[-1], "--steps=50")
            self.assertEqual(env["RESUME"], "1")
            self.assertEqual((env["DATA_DIR"], env["DATASET"], env["JOB_NAME"]), ("/rec/shoe", "success", "job1"))

    def test_resume_cli_run_uses_saved_config(self):
        with tempfile.TemporaryDirectory() as d:
            omx = Path(d)
            run = trainer.outputs_dir(omx, "act") / "act_box"
            cfg = trainer.resume_config(run)
            cfg.parent.mkdir(parents=True)
            cfg.write_text(json.dumps({"dataset": {"root": "/data/box_merged"}, "steps": 100}))
            _, env = trainer.build_resume(omx, "act", 0, run, [])
            self.assertEqual(env["DATASET"], "box_merged")
            self.assertNotIn("DATA_DIR", env)  # train.sh's own default

    def test_shell_line_is_reproducible(self):
        argv, env = trainer.build_train(OMX_DIR, "act", 0, Path("/d/my task/success"), "j", None, ["--steps=5"])
        line = trainer.shell_line(argv, env, OMX_DIR)
        self.assertIn("DATA_DIR='/d/my task'", line)
        self.assertIn("ACT/train.sh 0 --steps=5", line)
        self.assertNotIn("DETACH", line)

    def test_last_override(self):
        self.assertEqual(trainer.last_override(["--steps=5", "--seed=1", "--steps=9"], "steps"), "9")
        self.assertIsNone(trainer.last_override(["--seed=1"], "steps"))


class NamesTest(unittest.TestCase):
    def test_job_and_container(self):
        job = trainer.job_name("shoe box/1", "act", now=0)
        self.assertRegex(job, r"^shoe_box_1_act_\d{8}_\d{6}$")
        self.assertEqual(trainer.container_name(job), "omx-train-" + job)

    def test_runs_and_find_job(self):
        with tempfile.TemporaryDirectory() as d:
            omx = Path(d)
            self.assertEqual(trainer.list_runs(omx, "act"), [])
            run = trainer.outputs_dir(omx, "smolvla") / "j1"
            run.mkdir(parents=True)
            self.assertEqual(trainer.list_runs(omx, "smolvla"), [])  # no checkpoint yet
            cfg = trainer.resume_config(run)
            cfg.parent.mkdir(parents=True)
            cfg.write_text("{}")
            self.assertEqual(trainer.list_runs(omx, "smolvla"), [run])
            self.assertEqual(trainer.find_job(omx, "j1"), "smolvla")
            self.assertIsNone(trainer.find_job(omx, "other"))

    def test_started_at(self):
        self.assertEqual(trainer.parse_started_at("1970-01-01T00:01:40.123456789Z"), 100.0)
        self.assertIsNone(trainer.parse_started_at("0001-01-01T00:00:00Z"))


class TrainOptionsTest(unittest.TestCase):
    def test_parse_episode_list(self):
        self.assertEqual(trainer.parse_episode_list("", 10), [])
        self.assertEqual(trainer.parse_episode_list(" 9, 5 ,5", 10), [5, 9])
        self.assertEqual(trainer.parse_episode_list("3-5,8", 10), [3, 4, 5, 8])
        for bad in ("10", "a", "5-3", "1;2", "-1"):
            with self.assertRaises(ValueError):
                trainer.parse_episode_list(bad, 10)

    def test_split_extra_args(self):
        self.assertEqual(trainer.split_extra_args(""), [])
        self.assertEqual(
            trainer.split_extra_args("--seed=7 --rename_map='{\"a\": \"b c\"}'"),
            ["--seed=7", '--rename_map={"a": "b c"}'],
        )
        for bad in ("--seed='7", "seed=7"):
            with self.assertRaises(ValueError):
                trainer.split_extra_args(bad)

    def test_steps_per_epoch(self):
        self.assertEqual(trainer.steps_per_epoch(10787, 16), 675)
        self.assertEqual(trainer.steps_per_epoch(160, 16), 10)
        self.assertEqual(trainer.steps_per_epoch(0, 16), 0)

    def test_episode_lengths_across_files(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as d:
            ep = Path(d) / "meta" / "episodes" / "chunk-000"
            ep.mkdir(parents=True)
            pq.write_table(pa.table({"episode_index": [0, 1], "length": [40, 41], "x": [1, 2]}), ep / "file-000.parquet")
            pq.write_table(pa.table({"episode_index": [2], "length": [42], "x": [3]}), ep / "file-001.parquet")
            self.assertEqual(trainer.episode_lengths(Path(d)), {0: 40, 1: 41, 2: 42})
            self.assertEqual(trainer.episode_lengths(Path(d) / "none"), {})


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
        t = trainer.Trainer(OMX_DIR)
        t._emit_line("Training:  25%|##5       | 5/20 [00:01<00:03,  4.10step/s]")
        t._emit_line("INFO step:5 smpl:20 ep:1 epch:0.25 loss:1.5")
        kinds = [t.events.get_nowait()[0] for _ in range(t.events.qsize())]
        self.assertEqual(kinds, ["train_tqdm", "train_log", "train_progress"])

    def test_metrics_glued_to_tqdm(self):
        t = trainer.Trainer(OMX_DIR)
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
            (root / "meta" / "info.json").write_text(json.dumps({"total_episodes": 7}))
            self.assertEqual(trainer.episode_count(root), 7)


if __name__ == "__main__":
    unittest.main()
