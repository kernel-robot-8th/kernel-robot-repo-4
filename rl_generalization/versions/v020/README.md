# v020: robot-facing hinged lid

This is a separate structural variant of v018. The reference video shows the
lid initially open toward the OMX. Accordingly, the hinge is placed on the
negative-x edge of the box, the edge facing the OMX in the workcell frame. The
hinge axis is local +y. The sign convention is:

- `0 rad`: closed;
- `-pi/2`: lid vertical;
- `-pi`: lid flat toward the robot (negative x).

The XML joint range is `-pi .. 0`, but the builder does not set a nonzero
initial joint position: MuJoCo's default `qpos` for `lid_hinge` is `0 rad`
(closed). `check.py` temporarily assigns `-pi/2` and `-pi` to verify the
geometry; it is not an open-state initializer. An initial open `qpos=-pi`
and the subsequent close stage are **not implemented**. No controller yet
opens the lid, inserts the shoes, or closes it before the load/transport step.

Build and validate:

```bash
.venvs/omx_sim/bin/python versions/v020/code/build_robot_facing_hinge.py \
  .local/finger_proxy_v018 .local/robot_facing_hinge_v020
.venvs/omx_sim/bin/python versions/v020/code/check.py
.venvs/omx_sim/bin/python versions/v020/code/open_state.py --angle -3.14159265359
```

The builder preserves the v018 detached-lid closed world pose. Hinge direction,
clearance, cardboard compliance, and real hardware behavior remain provisional
until measured on the physical box.

The actual staged controller must initialize the hinge qpos to `-pi` before
shoe placement and command it to `0` only after both shoes are inside. That
open→insert→close controller is not implemented yet; `open_state.py` is the
state convention and geometry check for the next RL environment.

`evidence/compile_check.json` (SHA-256
`5b4bbcfcca041af88ce9499d329eedad6a2c834fbd1bb77d75ebe0a5e2ce3616`)
compiled with `nq=29`, preserved all closed-lid geom positions with maximum
error `0 m`, and confirmed that the two hypothetical open poses move upward
and toward negative x. This is a geometry check only; it is not evidence that
the video sequence or a robot-facing open/close policy works.
