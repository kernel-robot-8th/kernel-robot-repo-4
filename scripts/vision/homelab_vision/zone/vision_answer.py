#!/usr/bin/env python3
"""Camera zone evidence -> the team's /fleet/work_result answer for VERIFY_LOAD and VERIFY_UNLOAD (2026-11-08).

Built for the simulation debug run the user asked for. Pure Python: no ROS, no network, no files. A node that subscribes
/fleet/work_request and publishes /fleet/work_result wraps build_answer(); the caller owns session and seq checks.

Team contract read at c9374ec (origin/refactor/control-server-bt-mqtt-db, 11-07 20:14):
  request  (fleet_control_node.work, scenario_runtime.dispatch): request_id, order_id, robot_id, stage, target, action, sku,
           quantity, attempt, route{pickup, dropoff, pickup_arm, dropoff_arm, lane}, timeout_sec, session_id, seq, issued_at, ttl_sec
  result   (scenario_runtime.receive): request_id, robot_id, stage must match the order; source must be route.get('vision', 'vision');
           measured is True and finished is True or the result is dropped; success must be bool, data a dict
  accept   (scenario_nodes.VerifyCargo:159): VERIFY_LOAD needs data load_present and arm_safe, VERIFY_UNLOAD placed, arm_safe and
           load_absent, each `is True`. A missing field keeps the step waiting; the same request_id may answer again.
  failure  (scenario_nodes.DeviceStep.poll): success False without data.retry_safe True -> order UNKNOWN, robot emergency stop,
           arm hold (scenario_safety.interrupt). This module never sets retry_safe.

Time (changed 2026-11-08 after the simulator run C2b): ttl_sec is the request's arrival window, as the team's manual adapter
uses it (it marks a request EXPIRED when it arrives after issued_at + ttl_sec). After a timely arrival the fleet still accepts an
answer until the step deadline: the simulator saw a VERIFY_UNLOAD answer accepted 25 s after the request. So the camera may answer
until issued_at + timeout_sec. The first version refused answers after ttl, and evidence that settled 8 s late ended in a stop.
The caller keeps the first arrival time per request_id and passes it as received_at.

Policy, because a wrong answer moves or stops real machines:
  - Answer only from fresh, usable evidence. Undecided zone states (UNKNOWN, FILLING, MIXED, and NO_ROBOT, MULTI from the
    Pinky state model) get no answer.
  - arm_safe comes from the caller (arm side or the simulator). The camera has no evidence for it. None -> no answer.
  - A negative reading (no box, problem class, arm not safe) gets no answer by default: the team step then times out after
    step_timeout_sec. negative='report' sends success False instead, which stops the robot and holds the arms at once. Use it
    only to test that path in the simulator.
  - Evidence must start after the request: a zone window whose first frame predates issued_at gets no answer (11-09).
  - EMPTY is weak evidence: the real model misses tray boxes. load_absent from EMPTY is for the simulator, not the field.
"""

ACTIONS = {
    "verify_load": ("VERIFY_LOAD", ("load_present", "arm_safe")),
    "verify_unload": ("VERIFY_UNLOAD", ("placed", "arm_safe", "load_absent")),
}
UNDECIDED = {"UNKNOWN", "FILLING", "MIXED", "NO_ROBOT", "MULTI"}   # NO_ROBOT, MULTI: pinky_evidence.py (11-09); no robot seen is never "absent"


def target_zone(request):
    """Tray zone the camera must look at: pickup zone for loading, dropoff zone for unloading."""
    route = request.get("route") or {}
    key = "pickup" if request.get("stage") == "VERIFY_LOAD" else "dropoff"
    zone = route.get(key)
    return zone if isinstance(zone, str) and zone else None


def build_answer(request, report, arm_safe, now, placed_zones=None, max_age_sec=3.0, negative="wait", camera_id="", model="",
                 received_at=None):
    """-> (result dict or None, reason). report = LoadEvidence.update() output. placed_zones = {"ZC": "ZC_TABLE"} for unloading.

    received_at: when this request first arrived (default now). Checked against ttl_sec. The answer itself may come until timeout_sec.

    None means: send nothing. The reason says why, for the log.
    """
    if negative not in ("wait", "report"):
        raise ValueError("negative must be 'wait' or 'report'")
    action = request.get("action")
    if action not in ACTIONS:
        return None, "not a verify action"
    stage, fields = ACTIONS[action]
    if request.get("stage") != stage:
        return None, f"stage {request.get('stage')} does not match action {action}"
    route = request.get("route") or {}
    if request.get("target") != route.get("vision", "vision"):
        return None, "not addressed to vision"
    for key in ("request_id", "order_id", "robot_id"):
        if not isinstance(request.get(key), str) or not request[key]:
            return None, f"request has no {key}"
    issued, ttl, limit = request.get("issued_at"), request.get("ttl_sec"), request.get("timeout_sec")
    arrived = now if received_at is None else received_at
    if isinstance(issued, (int, float)) and isinstance(ttl, (int, float)) and arrived > issued + ttl:
        return None, "request expired on arrival"
    if isinstance(issued, (int, float)) and isinstance(limit, (int, float)) and now > issued + limit:
        return None, "step deadline passed"
    zone = target_zone(request)
    if zone is None:
        return None, "route has no zone for this stage"
    if not isinstance(report, dict) or not isinstance(report.get("zones"), dict):
        return None, "no evidence report"
    age = now - report.get("at", -1e18)
    if report.get("stale") or not 0 <= age <= max_age_sec:
        return None, "evidence is stale"
    tray = report["zones"].get(zone)
    if not isinstance(tray, dict):
        return None, f"zone {zone} is not watched"
    state = tray.get("state")
    if state in UNDECIDED:
        return None, f"zone {zone} is {state}"
    # 11-09: a window that began before the request may describe the previous robot or step. Wait until it is all newer.
    first = tray.get("first_frame_time")
    if isinstance(issued, (int, float)) and isinstance(first, (int, float)) and first < issued:
        return None, "evidence predates request"
    if arm_safe is not True and arm_safe is not False:
        return None, "arm_safe unknown"
    data = {"arm_safe": arm_safe}
    if stage == "VERIFY_LOAD":
        data["load_present"] = state == "BOX"
    else:
        table = (placed_zones or {}).get(zone)
        table_state = (report["zones"].get(table) or {}).get("state") if table else None
        if table_state is None or table_state in UNDECIDED:
            return None, f"placed zone {table} undecided"
        data["placed"] = table_state == "BOX"
        data["load_absent"] = state == "EMPTY"
    success = all(data[k] is True for k in fields)
    if not success and negative == "wait":
        return None, "negative reading, waiting: " + ", ".join(k for k in fields if data[k] is not True)
    data.update(zone=zone, zone_state=state, evidence_age_sec=round(age, 2), marker_state=report.get("marker_state"),
                camera_id=camera_id, model=model)
    result = {"request_id": request["request_id"], "order_id": request["order_id"], "robot_id": request["robot_id"],
              "stage": stage, "source": route.get("vision", "vision"), "measured": True, "finished": True, "success": success,
              "detail": "camera zone " + zone + " " + state, "data": data}
    return result, "answer"
