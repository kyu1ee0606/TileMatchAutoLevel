"""Common resource guard for bot measurement runners (2026-10-27, replaces the swap-free<500MB rule).

This machine runs with swap total 0 MB, so "swap free" is always 0 and is no longer a usable signal.
Run only while ALL hold:
  - kernel memory pressure level is not critical (sysctl kern.memorystatus_vm_pressure_level != 4;
    1 normal, 2 warn, 4 critical — the level memory_pressure(1) reports)
  - available memory >= 1.5 GB, available = (free + inactive + speculative + purgeable) pages x page size (vm_stat)
  - disk free >= 10 GiB on the backend volume
On failure: safe stop point (callers check BEFORE starting a row, so no partial row is written), then wait for
recovery printing status every <= 30 s; give up after max_wait seconds (caller then exits cleanly, resumable).
"""
import re, shutil, subprocess, time
from pathlib import Path

MIN_AVAIL_GB = 1.5
MIN_DISK_GIB = 10
CRITICAL = 4


def status(path=None):
    level = int(subprocess.check_output(['sysctl', '-n', 'kern.memorystatus_vm_pressure_level'], text=True).strip())
    vm = subprocess.check_output(['vm_stat'], text=True)
    page = int(re.search(r'page size of (\d+) bytes', vm)[1])
    pages = lambda k: int(re.search(rf'{k}:\s+(\d+)\.', vm)[1])
    avail = (pages('Pages free') + pages('Pages inactive') + pages('Pages speculative') + pages('Pages purgeable')) * page / 1e9
    disk = shutil.disk_usage(path or Path(__file__).resolve().parents[1]).free / 1024 ** 3
    reasons = []
    if level == CRITICAL: reasons.append('pressure_critical')
    if avail < MIN_AVAIL_GB: reasons.append(f'avail<{MIN_AVAIL_GB}GB')
    if disk < MIN_DISK_GIB: reasons.append(f'disk<{MIN_DISK_GIB}GiB')
    return dict(ok=not reasons, level=level, avail_gb=round(avail, 2), disk_gib=round(disk, 1), reasons=reasons)


def wait_ok(log=print, max_wait=3600, poll=30):
    """True when resources are fine (immediately or after recovery); False after max_wait seconds."""
    s = status()
    if s['ok']: return True
    t0 = time.time()
    while time.time() - t0 < max_wait:
        log(f"GUARD_WAIT {s}")
        time.sleep(poll)
        s = status()
        if s['ok']:
            log(f"GUARD_RECOVERED {s}"); return True
    log(f"GUARD_STOP {s}"); return False


if __name__ == '__main__':
    print(status())
