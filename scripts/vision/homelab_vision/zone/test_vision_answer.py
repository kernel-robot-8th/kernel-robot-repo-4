#!/usr/bin/env python3
"""vision_answer.py tests. The team checks are copied from c9374ec so the answer is judged the way the fleet judges it.

    python test_vision_answer.py     # last line [answer_test] N/N PASS, exit 0
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vision_answer as va  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))


def team_receive(result, order, route):
    """scenario_runtime.ScenarioRuntime.receive, the checks that decide whether a result is consumed (c9374ec)."""
    if (result.get("request_id") != order["request_id"] or result.get("robot_id") != order["robot_id"]
            or result.get("stage") != order["stage"]):
        return False
    if result.get("source") != route.get("vision", "vision"):
        return False
    if result.get("measured") is not True or result.get("finished") is not True:
        return False
    if not isinstance(result.get("data", {}), dict) or not isinstance(result.get("success"), bool):
        raise ValueError("success bool, data dict")
    return True


def team_accept(stage, data):
    """scenario_nodes.VerifyCargo.accept, copied as is (c9374ec scenario_nodes.py:159)."""
    fields = (("load_present", "arm_safe") if stage == "VERIFY_LOAD" else ("placed", "arm_safe", "load_absent"))
    return all(data.get(key) is True for key in fields)


ROUTE = {"pickup": "ZA", "dropoff": "ZC", "pickup_arm": "omx1", "dropoff_arm": "omx2", "lane": "main"}


def request(stage="VERIFY_LOAD", action="verify_load", **kw):
    r = {"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": stage, "target": "vision", "action": action,
         "sku": "S1", "quantity": 1, "attempt": 1, "route": dict(ROUTE), "timeout_sec": 300.0, "session_id": "s", "seq": 3,
         "issued_at": 100.0, "ttl_sec": 5.0}
    r.update(kw)
    return r


def report(states, at=101.0, stale=False):
    return {"at": at, "marker_state": "OK", "stale": stale, "zones": {z: {"state": s} for z, s in states.items()}}


def main():
    order = {"request_id": "r1", "robot_id": "pinky1", "stage": "VERIFY_LOAD"}
    res, why = va.build_answer(request(), report({"ZA": "BOX"}), True, 101.5)
    check("box and safe arm answers", res is not None, why)
    check("fleet consumes the answer", res is not None and team_receive(res, order, ROUTE))
    check("VerifyCargo accepts it", res is not None and team_accept("VERIFY_LOAD", res["data"]))
    check("fields are JSON true, not strings", res is not None and json.loads(json.dumps(res))["data"]["load_present"] is True)
    check("answer has no retry_safe", res is not None and "retry_safe" not in res["data"])
    check("answer is small", res is not None and len(json.dumps(res).encode()) < 16384)
    check("empty zone waits by default", va.build_answer(request(), report({"ZA": "EMPTY"}), True, 101.5)[0] is None)
    neg, _ = va.build_answer(request(), report({"ZA": "EMPTY"}), True, 101.5, negative="report")
    check("report mode sends success false", neg is not None and neg["success"] is False and not team_accept("VERIFY_LOAD", neg["data"]))
    check("problem zone waits", va.build_answer(request(), report({"ZA": "PROBLEM"}), True, 101.5)[0] is None)
    for s in ("UNKNOWN", "FILLING", "MIXED"):
        check(f"{s} gets no answer", va.build_answer(request(), report({"ZA": s}), True, 101.5)[0] is None)
        check(f"{s} never stops the robot", va.build_answer(request(), report({"ZA": s}), True, 101.5, negative="report")[0] is None)
    check("unknown arm gets no answer", va.build_answer(request(), report({"ZA": "BOX"}), None, 101.5)[0] is None)
    check("arm not safe waits", va.build_answer(request(), report({"ZA": "BOX"}), False, 101.5)[0] is None)
    check("string arm_safe is not trusted", va.build_answer(request(), report({"ZA": "BOX"}), "true", 101.5)[0] is None)
    check("string arm_safe never stops the robot", va.build_answer(request(), report({"ZA": "BOX"}), "true", 101.5, negative="report")[0] is None)
    check("request that arrived late gets no answer", va.build_answer(request(), report({"ZA": "BOX"}, at=105.5), True, 105.5 + 0.1)[0] is None)
    late, why_late = va.build_answer(request(), report({"ZA": "BOX"}, at=108.0), True, 108.2, received_at=100.2)
    check("evidence that settles after ttl still answers (sim C2b)", late is not None and team_accept("VERIFY_LOAD", late["data"]), why_late)
    check("answer after the step deadline is refused", va.build_answer(request(), report({"ZA": "BOX"}, at=400.5), True, 400.6, received_at=100.2)[0] is None)
    check("arrival after ttl is refused even with fresh evidence", va.build_answer(request(), report({"ZA": "BOX"}, at=108.0), True, 108.2, received_at=105.3)[0] is None)
    check("old evidence gets no answer", va.build_answer(request(), report({"ZA": "BOX"}, at=97.0), True, 101.5)[0] is None)
    check("evidence from the future is refused", va.build_answer(request(), report({"ZA": "BOX"}, at=103.0), True, 101.5)[0] is None)
    check("stale flag gets no answer", va.build_answer(request(), report({"ZA": "BOX"}, stale=True), True, 101.5)[0] is None)
    check("other zone does not count", va.build_answer(request(), report({"ZB": "BOX"}), True, 101.5)[0] is None)
    zb = request(route=dict(ROUTE, pickup="ZB"))
    check("route ZB looks at ZB", va.build_answer(zb, report({"ZB": "BOX", "ZA": "EMPTY"}), True, 101.5)[0] is not None)
    check("arm action is not ours", va.build_answer(request(stage="LOAD", action="load", target="omx1"), report({"ZA": "BOX"}), True, 101.5)[0] is None)
    check("stage and action must agree", va.build_answer(request(stage="VERIFY_UNLOAD"), report({"ZA": "BOX"}), True, 101.5)[0] is None)
    check("other target is not ours", va.build_answer(request(target="cam2"), report({"ZA": "BOX"}), True, 101.5)[0] is None)
    cam = request(target="cam2", route=dict(ROUTE, vision="cam2"))
    res2, _ = va.build_answer(cam, report({"ZA": "BOX"}), True, 101.5)
    check("a named vision source is copied", res2 is not None and res2["source"] == "cam2" and team_receive(res2, order, cam["route"]))
    check("missing request id gets no answer", va.build_answer(request(request_id=""), report({"ZA": "BOX"}), True, 101.5)[0] is None)
    un = request(stage="VERIFY_UNLOAD", action="verify_unload")
    ok_u, why_u = va.build_answer(un, report({"ZC": "EMPTY", "ZC_TABLE": "BOX"}), True, 101.5, placed_zones={"ZC": "ZC_TABLE"})
    check("unload: empty tray and box on table answers", ok_u is not None and team_accept("VERIFY_UNLOAD", ok_u["data"]), why_u)
    check("unload without a table zone gets no answer", va.build_answer(un, report({"ZC": "EMPTY"}), True, 101.5)[0] is None)
    check("unload with a problem on the tray waits", va.build_answer(un, report({"ZC": "PROBLEM", "ZC_TABLE": "BOX"}), True, 101.5, placed_zones={"ZC": "ZC_TABLE"})[0] is None)
    check("unload with box still on tray waits", va.build_answer(un, report({"ZC": "BOX", "ZC_TABLE": "BOX"}), True, 101.5, placed_zones={"ZC": "ZC_TABLE"})[0] is None)
    try:
        va.build_answer(request(), report({"ZA": "BOX"}), True, 101.5, negative="push")
        check("bad policy refused", False)
    except ValueError:
        check("bad policy refused", True)
    print(f"[answer_test] {sum(results)}/{len(results)} {'PASS' if all(results) else 'FAIL'}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
