"""프로세스와 장비의 자원 사용량을 /proc 에서 읽는다. 표준 라이브러리만 쓴다."""
import glob
import os
import threading
import time

CLK_TCK = os.sysconf("SC_CLK_TCK")
SAMPLE_SEC = 2.0


def parse_task_stat(text):
    """/proc/.../stat 한 줄에서 (utime + stime) 틱을 돌려준다. comm 에는 공백과 괄호가 올 수 있다."""
    fields = text[text.rindex(")") + 2:].split()
    return int(fields[11]) + int(fields[12])


def read_task_ticks(root="/proc/self/task"):
    """스레드 번호별 누적 CPU 틱을 돌려준다. 읽는 사이 끝난 스레드는 건너뛴다."""
    ticks = {}
    for tid in os.listdir(root):
        try:
            with open(os.path.join(root, tid, "stat"), encoding="utf-8", errors="replace") as f:
                ticks[int(tid)] = parse_task_stat(f.read())
        except (OSError, ValueError):
            continue
    return ticks


def group_of(name):
    """파이썬 스레드 이름을 표시용 묶음으로 바꾼다."""
    if name.startswith("capture-") or name == "inference":
        return name
    if name == "MainThread" or name == "resources":
        return "manager"
    return "http"


def cpu_by_group(before, after, seconds, names):
    """스레드 틱 차이를 묶음별 CPU %로 바꾼다. 100 은 논리 코어 하나를 다 쓴 값이다.

    이름 없는 스레드는 파이썬 밖 스레드다. OpenVINO, OpenCV, FFmpeg 가 섞여 있어 나눌 수 없다.
    """
    groups = {}
    if seconds <= 0:
        return groups
    for tid, tick in after.items():
        delta = tick - before.get(tid, tick)
        group = group_of(names[tid]) if tid in names else "native"
        groups[group] = groups.get(group, 0.0) + delta / CLK_TCK / seconds * 100.0
    return {group: round(value, 1) for group, value in sorted(groups.items())}


def read_process_ticks(path="/proc/self/stat"):
    """프로세스 누적 CPU 틱을 돌려준다. 끝난 스레드 몫까지 들어 있다."""
    with open(path, encoding="utf-8", errors="replace") as f:
        return parse_task_stat(f.read())


def read_rss_mb(path="/proc/self/status"):
    """프로세스 실제 메모리를 MB 로 읽는다."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024.0, 1)
    return None


def read_mem_available_mb(path="/proc/meminfo"):
    """장비 여유 메모리를 MB 로 읽는다."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return round(int(line.split()[1]) / 1024.0, 1)
    return None


def read_system_ticks(path="/proc/stat"):
    """장비 전체의 (사용 틱, 전체 틱)을 돌려준다."""
    with open(path, encoding="utf-8") as f:
        values = [int(v) for v in f.readline().split()[1:9]]  # guest 는 user 에 이미 들어 있다.
    idle = values[3] + values[4]
    return sum(values) - idle, sum(values)


def read_cpu_temp_c(root="/sys/class/hwmon"):
    """CPU 패키지 온도를 읽는다. 없으면 None 이다."""
    try:
        for name_path in glob.glob(os.path.join(root, "hwmon*", "name")):
            with open(name_path, encoding="utf-8") as f:
                if f.read().strip() != "coretemp":
                    continue
            with open(os.path.join(os.path.dirname(name_path), "temp1_input"), encoding="utf-8") as f:
                return round(int(f.read()) / 1000.0, 1)
    except (OSError, ValueError):
        pass
    return None


def read_cpu_mhz(pattern="/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"):
    """코어 평균 클럭을 읽는다. 온도 제한이 걸리면 내려간다."""
    values = []
    try:
        for path in glob.glob(pattern):
            with open(path, encoding="utf-8") as f:
                values.append(int(f.read()) / 1000.0)
    except (OSError, ValueError):
        return None
    return round(sum(values) / len(values)) if values else None


class ResourceMonitor(threading.Thread):
    """주기적으로 자원을 재서 최근 값 하나를 들고 있는다."""

    def __init__(self, period_sec=SAMPLE_SEC):
        super().__init__(daemon=True, name="resources")
        self.period_sec = period_sec
        self.halt = threading.Event()
        self.lock = threading.Lock()
        self.latest = {}

    def sample(self, last):
        ticks, system, process = read_task_ticks(), read_system_ticks(), read_process_ticks()
        now = time.monotonic()
        names = {t.native_id: t.name for t in threading.enumerate() if t.native_id}
        result = {"process_rss_mb": read_rss_mb(), "mem_available_mb": read_mem_available_mb(),
                  "load_avg": [float(v) for v in open("/proc/loadavg", encoding="utf-8").read().split()[:3]],
                  "cpu_temp_c": read_cpu_temp_c(), "cpu_mhz": read_cpu_mhz(), "logical_cpus": os.cpu_count(),
                  "threads": len(ticks)}
        if last:
            seconds = now - last["time"]
            groups = cpu_by_group(last["ticks"], ticks, seconds, names)
            used, total = system[0] - last["system"][0], system[1] - last["system"][1]
            result.update(cpu_groups=groups, process_cpu_pct=round((process - last["process"]) / CLK_TCK / seconds * 100.0, 1),
                          system_cpu_pct=round(100.0 * used / total, 1) if total else None)
        return result, {"time": now, "ticks": ticks, "system": system, "process": process}

    def run(self):
        last = None
        while not self.halt.is_set():
            try:
                result, last = self.sample(last)
                with self.lock:
                    self.latest = result
            except (OSError, ValueError) as e:
                with self.lock:
                    self.latest = {"error": str(e)}
            self.halt.wait(self.period_sec)

    def snapshot(self):
        with self.lock:
            return dict(self.latest)
