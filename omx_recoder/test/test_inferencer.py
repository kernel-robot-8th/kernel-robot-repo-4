import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import inferencer  # noqa: E402

OMX_DIR = Path(__file__).resolve().parents[2] / "omx_train"


class InferenceScriptTest(unittest.TestCase):
    """Reads the real omx_train scripts, so the dashboard notices when inference.sh changes shape."""

    def test_defaults_come_from_inference_sh(self):
        act = inferencer.script_defaults(inferencer.inference_script(OMX_DIR, "act"))
        self.assertEqual(act["policy.device"], "cpu")
        self.assertEqual(act["policy.path"], "$MODEL")
        self.assertTrue(act["duration"].isdigit())
        smol = inferencer.script_defaults(inferencer.inference_script(OMX_DIR, "smolvla"))
        self.assertEqual(smol["policy.device"], "cuda")

    def test_script_reads_the_env_the_dashboard_sets(self):
        for policy in ("act", "smolvla"):
            text = inferencer.inference_script(OMX_DIR, policy).read_text()
            for var in ("MODEL", "ROBOT_PORT", "TOP_CAM", "WRIST_CAM"):
                self.assertIn(f'{var}="${{{var}:-', text, f"{policy}: {var}")
            self.assertIn('"$@"', text)  # dashboard overrides go last

    def test_commented_options_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            sh = Path(d) / "inference.sh"
            sh.write_text('ARGS=(\n  # --fps=5\n  --fps=30   # note\n  --task="두 단어"   # x\n)\n')
            self.assertEqual(inferencer.script_defaults(sh), {"fps": "30", "task": "두 단어"})


class BuildRolloutTest(unittest.TestCase):
    def test_argv_and_env(self):
        cams = {"top": "/dev/cam_top", "wrist": "/dev/video2"}
        argv, env = inferencer.build_rollout(
            OMX_DIR, "act", Path("/m/pretrained_model"), "/dev/ttyACM0", cams, "omx_follower_arm",
            "상자 옮기기", 45, "cuda", (5, 0.01), ["--fps=15"],
        )
        self.assertEqual(argv[:2], ["bash", str(OMX_DIR / "ACT" / "inference.sh")])
        self.assertEqual(
            argv[2:],
            ["--robot.id=omx_follower_arm", "--duration=45", "--policy.device=cuda", "--task=상자 옮기기", "--fps=15"],
        )
        self.assertEqual(env["MODEL"], "/m/pretrained_model")
        self.assertEqual((env["ROBOT_PORT"], env["TOP_CAM"], env["WRIST_CAM"]), ("/dev/ttyACM0", "/dev/cam_top", "/dev/video2"))
        self.assertEqual((env["ACT_ENSEMBLE_K"], env["ACT_ENSEMBLE_M"]), ("5", "0.01"))
        self.assertTrue(env["PATH"].startswith(str(Path(sys.executable).parent) + os.pathsep))

    def test_empty_task_and_smolvla_skip_extras(self):
        argv, env = inferencer.build_rollout(
            OMX_DIR, "smolvla", Path("/m"), "/dev/ttyACM0", {"top": "a", "wrist": "b"}, "f", "", 0, "cuda", (5, 0.01), [],
        )
        self.assertFalse(any(a.startswith("--task=") for a in argv))
        self.assertIn("--duration=0", argv)
        self.assertNotIn("ACT_ENSEMBLE_K", env)

    def test_shell_line_hides_path(self):
        argv, env = inferencer.build_rollout(
            OMX_DIR, "act", Path("/m"), "/dev/ttyACM0", {"top": "a", "wrist": "b"}, "f", "x y", 10, "cpu", None, [],
        )
        line = inferencer.shell_line(argv, env, OMX_DIR)
        self.assertTrue(line.startswith("MODEL=/m ROBOT_PORT=/dev/ttyACM0 TOP_CAM=a WRIST_CAM=b ACT/inference.sh "))
        self.assertIn("'--task=x y'", line)
        self.assertNotIn("PATH=", line)


class DatasetForModelTest(unittest.TestCase):
    @staticmethod
    def _dataset(path: Path) -> Path:
        (path / "meta").mkdir(parents=True)
        (path / "meta" / "info.json").write_text("{}")
        return path

    @staticmethod
    def _model(omx: Path, job: str, dataset_root: str) -> Path:
        model = omx / "ACT" / "outputs" / "train" / job / "checkpoints" / "last" / "pretrained_model"
        model.mkdir(parents=True)
        (model / "train_config.json").write_text(json.dumps({"dataset": {"root": dataset_root}}))
        return model

    def test_run_json_first_then_train_sh_data_dir(self):
        with tempfile.TemporaryDirectory() as d:
            omx = Path(d)
            dash = self._dataset(omx / "elsewhere" / "shoe")
            cli = self._dataset(omx / "ACT" / "data" / "box")
            model = self._model(omx, "dash_run", "/data/shoe")
            (model.parents[3] / "dash_run.run.json").write_text(json.dumps({"dataset_root": str(dash)}))
            self.assertEqual(inferencer.dataset_for_model(model), dash)
            # Command-line run: only the container path, mapped to train.sh's default DATA_DIR.
            self.assertEqual(inferencer.dataset_for_model(self._model(omx, "cli_run", "/data/box")), cli)
            self.assertIsNone(inferencer.dataset_for_model(self._model(omx, "gone", "/data/missing")))
            self.assertIsNone(inferencer.dataset_for_model(omx / "no_such_model"))


class ListModelsTest(unittest.TestCase):
    def test_newest_run_first_last_checkpoint_first(self):
        with tempfile.TemporaryDirectory() as d:
            omx = Path(d)
            out = omx / "ACT" / "outputs" / "train"
            for run, ckpts in (("old", ["last", "000100"]), ("new", ["000200", "last", "000400"])):
                for c in ckpts:
                    (out / run / "checkpoints" / c / "pretrained_model").mkdir(parents=True)
            (out / "new" / "checkpoints" / "000300").mkdir()  # no pretrained_model: skipped
            (out / "data_act.run.json").write_text("{}")
            os.utime(out / "old", (1, 1))
            got = [str(p.relative_to(out)) for p in inferencer.list_models(omx, "act")]
            self.assertEqual(
                got,
                [
                    "new/checkpoints/last/pretrained_model",
                    "new/checkpoints/000400/pretrained_model",
                    "new/checkpoints/000200/pretrained_model",
                    "old/checkpoints/last/pretrained_model",
                    "old/checkpoints/000100/pretrained_model",
                ],
            )
            self.assertEqual(inferencer.list_models(omx, "smolvla"), [])


if __name__ == "__main__":
    unittest.main()
