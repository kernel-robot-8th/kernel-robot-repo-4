"""Box-number input for models trained with a box one-hot in observation.state (lerobot 0.4.4 lerobot-record).

omx_1031 models "box": the state ends with a one-hot of the box to unload (boxes 1-4 of the column,
numbered from the top; tools/add_box_state.py). The robot reports only its own state, so the box
number is given when the policy is started and appended to every observation:

  BOX=3 ./infer.sh <n>        (N_BOX=4 by default)

install() patches lerobot.scripts.lerobot_record.predict_action; call it before lerobot-record's main().
"""

import numpy as np


def install(box, n_box=4):
    import lerobot.scripts.lerobot_record as rec

    if not 1 <= box <= n_box:
        raise SystemExit(f"BOX must be 1..{n_box}, got {box}")
    one_hot = np.eye(n_box, dtype=np.float32)[box - 1]
    original = rec.predict_action

    def predict_action(observation, *args, **kwargs):
        observation = dict(observation)
        observation["observation.state"] = np.concatenate(
            [np.asarray(observation["observation.state"], dtype=np.float32), one_hot])
        return original(observation, *args, **kwargs)

    rec.predict_action = predict_action
    print(f"[box] box {box}/{n_box}: one-hot {one_hot.astype(int).tolist()} appended to observation.state", flush=True)
