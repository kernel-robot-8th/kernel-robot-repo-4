import glob
import os

AUTO = "auto"
BAUDRATE = 1_000_000
PROTOCOL_VERSION = 2.0
# First motor ID of each arm (follower 11-16, leader 1-6)
PROBE_IDS = {"follower": 11, "leader": 1}
NAMES = {"follower": "팔로워", "leader": "리더"}


def _candidates() -> list[str]:
    """Serial ports, as stable /dev/serial/by-id paths when available."""
    by_id = sorted(glob.glob("/dev/serial/by-id/*"))
    seen = {os.path.realpath(p) for p in by_id}
    raw = sorted(p for p in glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*") if os.path.realpath(p) not in seen)
    return by_id + raw


def _ping(port: str, motor_ids) -> set[int]:
    import dynamixel_sdk as dxl

    ph = dxl.PortHandler(port)
    try:
        if not ph.openPort() or not ph.setBaudRate(BAUDRATE):
            return set()
        pk = dxl.PacketHandler(PROTOCOL_VERSION)
        found = set()
        for mid in motor_ids:
            _, comm, _ = pk.ping(ph, mid)
            if comm == dxl.COMM_SUCCESS:
                found.add(mid)
        return found
    except Exception:  # noqa: BLE001
        return set()
    finally:
        ph.closePort()


def port_has_arm(port: str, role: str) -> bool:
    return bool(port) and port != AUTO and os.path.exists(port) and PROBE_IDS[role] in _ping(port, [PROBE_IDS[role]])


def find_arm_ports() -> dict[str, str]:
    """Return {'follower': port, 'leader': port} for every arm found by pinging its first motor ID."""
    found = {}
    for port in _candidates():
        ids = _ping(port, PROBE_IDS.values())
        for role, mid in PROBE_IDS.items():
            if mid in ids and role not in found:
                found[role] = port
    return found


def resolve_arm_ports(follower_port: str, leader_port: str) -> tuple[dict[str, str], list[str]]:
    """Keep a configured port only if that arm answers on it; otherwise detect the board automatically.

    Boards change between computers and when arms are swapped, so a saved port is never trusted blindly.
    """
    want = {"follower": follower_port, "leader": leader_port}
    ports, notes = {}, []
    for role, port in want.items():
        if port_has_arm(port, role):
            ports[role] = port
    missing = [r for r in want if r not in ports]
    if missing:
        detected = find_arm_ports()
        for role in missing:
            if role in detected and detected[role] not in ports.values():
                ports[role] = detected[role]
                if want[role] not in ("", AUTO):
                    notes.append(f"{NAMES[role]} 설정 포트({want[role]})에서 응답 없음 → 자동 감지")
    return ports, notes
