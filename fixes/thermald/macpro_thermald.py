#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 lvalen91
"""macpro-thermald: zone-based fan control for the 2019 Mac Pro (MacPro7,1) on Linux.

Design (see README.md):
  * Fans are driven in ZONES. Each zone has a list of fans (kept in sync, one
    shared target rpm) and a list of temperature SOURCES, each with its own
    curve. Zone target = max over its sources.
  * Sources: CPU packages (coretemp), every AMD GPU found by vendor id (never
    "card0"), and SMC keys looked up by their 4-character label.
  * Safety first: any alarm, any lost critical sensor, a write that does not
    stick, or an internal error drives the affected fans (or all fans) to max.
    On exit the fans are left at max unless --release was requested.
  * Three fan interfaces are supported (see Fan):
      "legacy"  t2linux <= 7.2 applesmc: fanN_manual / fanN_output
      "pwm"     hwmon style: pwmN_enable / fanN_target
      "target"  t2linux >= 7.3 macsmc_hwmon: fanN_target ONLY. Writing a value
                inside [fanN_min, fanN_max] switches that fan to manual; writing 0
                hands it back to the SMC; anything else is EINVAL. Writes only work
                with the module parameter macsmc_hwmon.fan_control=Y (the daemon
                sets it), and the driver swallows SMC write errors, so read-back is
                the only proof that a write took effect.
  * SMC temperatures are matched by the 4-char key in the tempN_label text:
    macsmc_hwmon labels look like "CPU Proximity Temperature (TC0P)"; applesmc
    labels are the bare key.

Exit codes: 0 clean stop, 78 no fan interface found (kernel without T2 fan support),
69 fan interface present but not controllable (fan_control cannot be enabled, writes
refused): the SMC keeps automatic control, 70 internal error at start-up.

Stdlib only, Python >= 3.11 (tomllib).
"""
import argparse
import glob
import os
import re
import signal
import socket
import sys
import time

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

ROOT = os.environ.get("MACPRO_SYSFS_ROOT", "")  # tests point this at a fake tree
CONF = "/etc/macpro-thermald.conf"
EX_UNAVAILABLE = 69    # interface exists but cannot be driven; SMC stays in charge
EX_SOFTWARE = 70
EX_CONFIG = 78         # no fan interface at all
FAN_CONTROL_PARAM = "/sys/module/macsmc_hwmon/parameters/fan_control"


def p(path):
    return ROOT + path


def log(msg):
    print(msg, flush=True)


def read(path):
    with open(path) as f:
        return f.read().strip()


def write(path, val):
    with open(path, "w") as f:
        f.write(str(val))


def interp(curve, t):
    """Piecewise-linear curve [[temp, rpm], ...] sorted by temp; clamped."""
    if t <= curve[0][0]:
        return float(curve[0][1])
    for (t0, r0), (t1, r1) in zip(curve, curve[1:]):
        if t <= t1:
            return r0 + (r1 - r0) * (t - t0) / (t1 - t0)
    return float(curve[-1][1])


# ----------------------------------------------------------------- hardware

def ensure_fan_control():
    """macsmc_hwmon refuses fanN_target writes (EOPNOTSUPP) unless fan_control=Y.
    Returns True if there is nothing to do or it is now enabled."""
    path = p(FAN_CONTROL_PARAM)
    if not os.path.exists(path):
        return True                      # other driver, no such gate
    try:
        if read(path) in ("Y", "1"):
            return True
        write(path, "Y")                 # module_param_unsafe: taints the kernel, by design
        return read(path) in ("Y", "1")
    except OSError as e:
        log(f"ERROR cannot enable {path}: {e}")
        return False


class Fan:
    """One SMC fan. `n` is the 1-based sysfs number (fan1 == SMC F0).

    kind "legacy": fanN_manual (1/0) + fanN_output
    kind "pwm":    pwmN_enable (1 manual / 2 auto) + fanN_target
    kind "target": fanN_target only (macsmc_hwmon). Manual is implicit in the first
                   in-range write; 0 releases the fan to the SMC.
    """

    def __init__(self, base, n):
        self.base, self.n = base, n
        self.input = f"{base}/fan{n}_input"
        self.min = int(float(read(f"{base}/fan{n}_min")))
        self.max = int(float(read(f"{base}/fan{n}_max")))
        self.mode_file = None
        if os.path.exists(f"{base}/fan{n}_manual"):            # t2linux <= 7.2 applesmc
            self.kind = "legacy"
            self.mode_file, self.manual_val, self.auto_val = f"{base}/fan{n}_manual", "1", "0"
            self.target_file = f"{base}/fan{n}_output"
        elif os.path.exists(f"{base}/pwm{n}_enable"):          # hwmon style
            self.kind = "pwm"
            self.mode_file, self.manual_val, self.auto_val = f"{base}/pwm{n}_enable", "1", "2"
            self.target_file = f"{base}/fan{n}_target"
        elif os.path.exists(f"{base}/fan{n}_target"):          # t2linux >= 7.3 macsmc_hwmon
            self.kind = "target"
            self.target_file = f"{base}/fan{n}_target"
        else:
            raise FileNotFoundError(f"fan{n}: no fan control files in {base}")
        self.last_set = None
        self.mismatch = 0

    def rpm(self):
        return float(read(self.input))

    def set_manual(self):
        if self.mode_file:
            write(self.mode_file, self.manual_val)
        # kind "target": nothing to do, the first command() switches to manual

    def set_auto(self):
        if self.mode_file:
            write(self.mode_file, self.auto_val)
        else:
            write(self.target_file, 0)       # 0 = release to SMC
        self.last_set = None

    def command(self, rpm):
        rpm = int(max(self.min, min(self.max, round(rpm))))
        write(self.target_file, rpm)
        self.last_set = rpm
        return rpm

    def rearm(self):
        """kind "target" only: the driver caches 'manual' and will not re-assert it
        (e.g. after the SMC reset it behind our back). Release, then write again."""
        if self.kind == "target" and self.last_set is not None:
            want = self.last_set
            write(self.target_file, 0)
            write(self.target_file, want)

    def verify(self):
        """True if mode (where readable) and target read back as we set them."""
        try:
            if self.mode_file and read(self.mode_file) != self.manual_val:
                return False
            return abs(int(float(read(self.target_file))) - self.last_set) <= 5
        except (OSError, ValueError, TypeError):
            return False


def find_applesmc():
    cands = []
    for h in sorted(glob.glob(p("/sys/class/hwmon/hwmon*"))):
        cands += [h, h + "/device"]
    cands += sorted(glob.glob(p("/sys/bus/acpi/devices/APP0001:*")))
    cands += [p("/sys/devices/platform/applesmc.768")]
    for c in cands:
        if os.path.exists(c + "/fan1_input"):
            return os.path.realpath(c)
    return None


def wait_for_applesmc(timeout_s):
    """The SMC hwmon is created by udev after the ACPI device binds, which can be
    after this unit starts; wait instead of giving up with 78 at once."""
    deadline = time.monotonic() + timeout_s
    while True:
        base = find_applesmc()
        if base or time.monotonic() >= deadline:
            return base
        time.sleep(1.0)


def hwmon_dirs():
    return sorted(glob.glob(p("/sys/class/hwmon/hwmon*")))


_KEY_IN_LABEL = re.compile(r"\(([A-Za-z0-9#!]{4})\)\s*$")


def smc_sensor_files(base):
    """SMC key -> tempN_input path. The key is the whole label (applesmc) or the
    trailing "(KEY)" of a descriptive label (macsmc_hwmon)."""
    out = {}
    for lab in glob.glob(base + "/temp*_label"):
        try:
            text = read(lab)
        except OSError:
            continue
        m = _KEY_IN_LABEL.search(text)
        out.setdefault(m.group(1) if m else text, lab.replace("_label", "_input"))
    return out


class Temp:
    """A readable temperature in degrees C with a stable name."""

    def __init__(self, name, path, scale=1000.0):
        self.name, self.path, self.scale = name, path, scale
        self.fails = 0

    def read(self):
        v = float(read(self.path)) / self.scale
        if not (-20.0 < v < 150.0):   # SMC reports -127 / garbage for absent probes
            raise ValueError(f"implausible {self.name}={v}")
        return v


def discover_cpu():
    out = []
    for h in hwmon_dirs():
        try:
            if read(h + "/name") != "coretemp":
                continue
        except OSError:
            continue
        for lab in sorted(glob.glob(h + "/temp*_label")):
            if read(lab).startswith("Package id"):
                out.append(Temp("cpu:" + read(lab), lab.replace("_label", "_input")))
    return out


def discover_gpus():
    """Every AMD GPU by vendor id: {cardname: {'edge':Temp,'junction':Temp,'mem':Temp}}."""
    gpus = {}
    for card in sorted(glob.glob(p("/sys/class/drm/card[0-9]*"))):
        dev = card + "/device"
        try:
            if read(dev + "/vendor") != "0x1002":
                continue
        except OSError:
            continue
        name = os.path.basename(card)
        for h in sorted(glob.glob(dev + "/hwmon/hwmon*")):
            for lab in sorted(glob.glob(h + "/temp*_label")):
                kind = read(lab)
                gpus.setdefault(name, {})[kind] = Temp(f"{name}:{kind}", lab.replace("_label", "_input"))
    return gpus


# ------------------------------------------------------------------- config

DEFAULT_CONF = {
    "general": {"poll_s": 2.0, "verify_settle_s": 1.5, "down_rpm_per_s": 25.0,
                "sensor_fail_limit": 3, "mismatch_limit": 5},
}


def load_conf(path):
    if tomllib is None:
        raise SystemExit("Python >= 3.11 needed (tomllib)")
    with open(path, "rb") as f:
        conf = tomllib.load(f)
    g = dict(DEFAULT_CONF["general"])
    g.update(conf.get("general", {}))
    conf["general"] = g
    return conf


def build_sources(conf, smc_labels):
    """Resolve config 'sources' into (zone, name, [Temp...], curve, alarm_C, critical)."""
    cpus, gpus = discover_cpu(), discover_gpus()
    resolved = []
    for zname, z in conf["zones"].items():
        for s in z["sources"]:
            kind = s["kind"]
            temps = []
            if kind == "cpu":
                temps = cpus
            elif kind == "gpu":
                for g in gpus.values():
                    if s.get("sensor", "junction") in g:
                        temps.append(g[s.get("sensor", "junction")])
            elif kind == "smc":
                for key in s["keys"]:
                    if key in smc_labels:
                        temps.append(Temp("smc:" + key, smc_labels[key]))
            else:
                raise SystemExit(f"unknown source kind {kind}")
            resolved.append({
                "zone": zname, "name": s.get("name", kind), "temps": temps,
                "curve": [list(map(float, pt)) for pt in s["curve"]],
                "alarm": float(s["alarm"]), "critical": bool(s.get("critical", True)),
                "expect": int(s.get("expect", 1)), "fails": 0, "short": 0,
            })
            if not temps:
                log(f"WARN: source '{s.get('name', kind)}' in zone {zname} matched no sensors")
    return resolved


# --------------------------------------------------------------- watchdog

class Notify:
    def __init__(self):
        self.addr = os.environ.get("NOTIFY_SOCKET")
        self.sock = None
        if self.addr:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            if self.addr[0] == "@":
                self.addr = "\0" + self.addr[1:]

    def send(self, msg):
        if self.sock:
            try:
                self.sock.sendto(msg.encode(), self.addr)
            except OSError:
                pass


# ------------------------------------------------------------------- daemon

class Daemon:
    def __init__(self, conf, base):
        self.conf, self.g = conf, conf["general"]
        self.fans = {}
        for zname, z in conf["zones"].items():
            for n in z["fans"]:
                if n not in self.fans:
                    self.fans[n] = Fan(base, n)
        self.zone_fans = {zn: [self.fans[n] for n in z["fans"]] for zn, z in conf["zones"].items()}
        self.floor = {zn: float(z.get("floor_rpm", 0)) for zn, z in conf["zones"].items()}
        self.sources = build_sources(conf, smc_sensor_files(base))
        self.target = {zn: self.floor[zn] for zn in conf["zones"]}
        self.notify = Notify()
        self.stop = False
        self.release_on_exit = False

    def all_max(self, why):
        """Drive every fan to max. Returns how many fans accepted it. If none did,
        the last resort is to hand the fans back to the SMC (its own curve)."""
        log(f"FAILSAFE: all fans to max ({why})")
        for zn, fl in self.zone_fans.items():
            self.target[zn] = float(max(f.max for f in fl))   # recover by ramping down
        ok = 0
        for f in self.fans.values():
            try:
                f.set_manual()
                f.command(f.max)
                ok += 1
            except OSError as e:
                log(f"ERROR setting fan{f.n} to max: {e}")
        if ok == 0 and self.fans:
            log("ERROR: no fan accepted max; releasing to SMC automatic control")
            for f in self.fans.values():
                try:
                    f.set_auto()
                except OSError:
                    pass
        return ok

    def zone_demand(self):
        """Return (demand per zone, alarm reason or None)."""
        demand = {zn: self.floor[zn] for zn in self.conf["zones"]}
        for s in self.sources:
            vals = []
            if s["critical"] and len(s["temps"]) < s["expect"]:
                s["short"] += 1          # e.g. one GPU not found: treat like a lost sensor
                if s["short"] >= self.g["sensor_fail_limit"]:
                    return demand, f"{s['name']}: found {len(s['temps'])} sensors, expected {s['expect']}"
            for t in s["temps"]:
                try:
                    vals.append(t.read())
                    t.fails = 0
                except (OSError, ValueError) as e:
                    t.fails += 1
                    log(f"sensor fault {t.name}: {e}")
                    if s["critical"] and t.fails >= self.g["sensor_fail_limit"]:
                        return demand, f"{t.name} unreadable {t.fails}x"
            if not vals:
                s["fails"] += 1
                if s["critical"] and s["fails"] >= self.g["sensor_fail_limit"]:
                    return demand, f"{s['name']} lost all sensors"
                continue
            s["fails"] = 0
            hot = max(vals)
            if hot >= s["alarm"]:
                return demand, f"{s['name']} {hot:.1f}C >= alarm {s['alarm']}"
            demand[s["zone"]] = max(demand[s["zone"]], interp(s["curve"], hot))
        return demand, None

    def step(self, dt):
        demand, alarm = self.zone_demand()
        if alarm:
            self.all_max(alarm)
            return
        for zn, want in demand.items():
            cur = self.target[zn]
            if want >= cur:
                new = want                                  # ramp up at once
            else:
                new = max(want, cur - self.g["down_rpm_per_s"] * dt)  # ramp down slowly
            self.target[zn] = new
            for f in self.zone_fans[zn]:
                f.set_manual()
                f.command(new)

    def verify(self):
        bad = 0
        for f in self.fans.values():
            if f.last_set is None:
                continue
            if f.verify():
                f.mismatch = 0
            else:
                f.mismatch += 1
                try:
                    f.rearm()
                except OSError:
                    pass
                if f.mismatch >= self.g["mismatch_limit"]:
                    bad += 1
        return bad

    def run(self):
        if self.all_max("start-up") == 0:     # start safe, never from an unknown state
            raise SystemExit(EX_UNAVAILABLE)
        log(f"macpro-thermald: {len(self.fans)} fans, {len(self.sources)} sources")
        self.notify.send("READY=1")
        last = time.monotonic()
        last_verify = last
        while not self.stop:
            time.sleep(self.g["poll_s"])
            now = time.monotonic()
            try:
                # Verify BEFORE writing again: the SMC target reads back stale for
                # ~0.2 s after a write (measured on the Mac Pro 7,1), so check what
                # the previous cycle wrote, a full poll interval ago.
                if now - last_verify >= self.g["verify_settle_s"]:
                    if self.verify():
                        self.all_max("fan writes are not sticking (another writer?)")
                    last_verify = now
                self.step(now - last)
            except Exception as e:   # any bug => safe, not silent
                self.all_max(f"internal error: {e!r}")
            last = now
            self.notify.send("WATCHDOG=1")
        self.shutdown()

    def shutdown(self):
        if self.release_on_exit:
            log("releasing fans to automatic control")
            for f in self.fans.values():
                try:
                    f.set_auto()
                except OSError:
                    pass
        else:
            self.all_max("daemon stopping")


def max_now(base):
    """Fallback used by ExecStopPost: needs no config, tolerates per-fan failures.
    Returns an exit code."""
    if not ensure_fan_control():
        log("WARN: fan_control could not be enabled; trying the writes anyway")
    ok = bad = 0
    for n in range(1, 17):
        if not os.path.exists(f"{base}/fan{n}_input"):
            continue
        try:
            f = Fan(base, n)
            f.set_manual()
            f.command(f.max)
            ok += 1
        except (OSError, ValueError) as e:
            bad += 1
            log(f"ERROR fan{n}: {e}")
    log(f"max-now: {ok} fans set to max, {bad} failed")
    if bad or ok == 0:
        return EX_UNAVAILABLE
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conf", default=CONF)
    ap.add_argument("--release", action="store_true", help="on exit hand fans back to the SMC")
    ap.add_argument("--max-now", action="store_true", help="set all fans to max and exit (fallback unit)")
    ap.add_argument("--status", action="store_true", help="print sensors and fans once and exit (read-only)")
    ap.add_argument("--wait", type=float, default=0.0,
                    help="seconds to wait for the SMC hwmon to appear before exiting 78")
    a = ap.parse_args()

    base = wait_for_applesmc(a.wait) if a.wait > 0 else find_applesmc()
    if base is None:
        log("no SMC hwmon with fan1_input found (kernel without T2 fan support?)")
        sys.exit(EX_CONFIG)
    if a.max_now:
        sys.exit(max_now(base))
    try:
        conf = load_conf(a.conf)
        if not a.status and not ensure_fan_control():
            log("fan_control is off and cannot be enabled: leaving fans to the SMC")
            sys.exit(EX_UNAVAILABLE)
        d = Daemon(conf, base)
    except (OSError, ValueError, KeyError) as e:
        log(f"start-up error: {e!r}")
        if not a.status:
            max_now(base)
        sys.exit(EX_SOFTWARE)
    d.release_on_exit = a.release
    if a.status:
        for n, f in sorted(d.fans.items()):
            print(f"fan{n} [{f.kind}]: {f.rpm():.0f} rpm (min {f.min}, max {f.max})")
        for s in d.sources:
            vals = []
            for t in s["temps"]:
                try:
                    vals.append(f"{t.name}={t.read():.1f}")
                except (OSError, ValueError) as e:
                    vals.append(f"{t.name}=ERR({e})")
            print(f"{s['zone']}/{s['name']}: " + ", ".join(vals))
        return
    signal.signal(signal.SIGTERM, lambda *_: setattr(d, "stop", True))
    signal.signal(signal.SIGINT, lambda *_: setattr(d, "stop", True))
    d.run()


if __name__ == "__main__":
    main()
