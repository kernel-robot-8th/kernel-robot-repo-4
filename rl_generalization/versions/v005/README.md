# v005 — OMX physical-model audit and preview (not RL training)

Official model: https://github.com/ROBOTIS-GIT/robotis_mujoco_menagerie/tree/d8344c0dbe7a00208d0301111523dde65efc174a/robotis_omx
License: model directory LICENSE (Apache-2.0). Upstream files kept unchanged under .local/sim_sources. Hashes recorded in evidence/model_audit.json. CURRENT remains v004 for existing toy run.sh; v005 uses standalone scripts, not a drop-in new training backend.

## Verified locally

MuJoCo3.3.7 in separate .venvs/omx_sim. Official scene loads with 7 qpos (5 arm + driven finger + mimic finger), 6 position actuators. All five link origins and joint axes exactly match the old recorder FK constants. Official home stepped500 times /1 simulation second, finite state, zero MuJoCo warnings. Two candidate arm init poses are within model joint ranges and have no generated contacts at the inspected static poses with model gripper0. These are not real collision clearance guarantees.

Candidate mapping uses calibration -> integer tick -> (tick-2048)*2pi/4096, signs+1 offsets0. This has NOT been validated against real joint zero/direction. Gripper range in XML is 0..1.745329 radians; opposing finger is coupled by equality q_mimic=-q_gripper. Real gripper normalized0..100 is a motor full-range scale, not 0..100 degrees or aperture percentage. No real gripper mapping implemented. Preview gripper0 is explicitly a model parameter, not inferred from recorded59.68/58.93.

Do not treat copied model actuator force limits/gains as measured motor limits: XML common position actuator forcerange±3.5 and comment stall0.52 are not matched to the heterogeneous real motor list. Contact uses mesh geometry; contact shape/convex handling, friction and real shoe deformation require validation before grasp claims.

## Preview on local noma-pc

```bash
cd ~/dev_ws/Project2/rl_generalization
.venvs/omx_sim/bin/python versions/v005/code/preview_model.py --pose arrange
# Close window, then compare the loading pose:
.venvs/omx_sim/bin/python versions/v005/code/preview_model.py --pose load
```

Static viewer; no physics stepping, hardware driver or network control. Mouse changes viewpoint. --gripper-rad is a simulator-only parameter. Existing image evidence/arrange_candidate.png has been rendered with EGL and visually inspected. It is not an image of hardware.

Reproduce on a new machine after cloning the pinned source and copying the metadata archive:

```bash
python3 -m venv .venvs/omx_sim
.venvs/omx_sim/bin/python -m pip install -r versions/v005/requirements-sim.txt
.venvs/omx_sim/bin/python versions/v005/code/audit_model.py --out /tmp/new_model_audit.json
```

Existing output files are never overwritten by these scripts. Installed package versions are recorded in evidence/requirements.resolved.txt.

## Gate before learning

1. Compare arm preview with the real initial pose, establish base orientation/zero/direction from known robot model or measured poses. Camera perspective alone is not metric calibration.
2. Determine real gripper open/closed readings and jaw gap, relate to simulator finger angle; do not use a generic percentage mapping.
3. Validate position actuator tracking and control period, collisions and controller constraints in simulator.
4. Add tabletop and a simple grasp object, scripted contact/lift test; later shoe geometry/material. No object or grasp environment currently implemented.
5. Only then connect Gymnasium/SAC with observations/rewards from physical object states. Toy v004 policy is incompatible and should not be deployed.
