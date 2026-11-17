# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 lvalen91
"""Fake-sysfs tests: python3 -m unittest -v tests/test_thermald.py"""
import importlib
import os
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

CONF = textwrap.dedent("""
    [general]
    poll_s = 0.0
    down_rpm_per_s = 100.0
    sensor_fail_limit = 2
    mismatch_limit = 2

    [zones.front]
    fans = [2, 3, 4]
    floor_rpm = 500
    [[zones.front.sources]]
    name = "cpu"
    kind = "cpu"
    curve = [[40, 500], [80, 2500]]
    alarm = 95
    [[zones.front.sources]]
    name = "gpu"
    kind = "gpu"
    sensor = "junction"
    curve = [[50, 500], [90, 2500]]
    alarm = 105

    [zones.side]
    fans = [1]
    floor_rpm = 500
    [[zones.side.sources]]
    name = "dimm"
    kind = "smc"
    keys = ["TM0P", "TM1P"]
    curve = [[40, 500], [80, 1200]]
    alarm = 90
    critical = false
""")


def w(path, val):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(str(val))


def rd(path):
    with open(path) as f:
        return f.read().strip()


class FakeMac:
    def __init__(self, layout="t2"):
        self.d = tempfile.mkdtemp()
        smc = f"{self.d}/sys/class/hwmon/hwmon0"
        w(smc + "/name", "applesmc")
        for n in range(1, 5):
            lo, hi = (500, 1200) if n == 1 else (500, 2500)
            w(f"{smc}/fan{n}_input", 500)
            w(f"{smc}/fan{n}_min", lo)
            w(f"{smc}/fan{n}_max", hi)
            if layout == "t2":
                w(f"{smc}/fan{n}_manual", 0)
                w(f"{smc}/fan{n}_output", 0)
            elif layout == "target":      # t2linux 7.3 macsmc_hwmon: fanN_target only
                w(f"{smc}/fan{n}_target", 600)
            else:
                w(f"{smc}/pwm{n}_enable", 2)
                w(f"{smc}/fan{n}_target", 0)
        if layout == "target":
            w(f"{self.d}/sys/module/macsmc_hwmon/parameters/fan_control", "N")
        for i, (key, c) in enumerate([("TM0P", 30), ("TM1P", 31)], 1):
            # macsmc_hwmon labels are descriptive with the key in parentheses
            w(f"{smc}/temp{i}_label", f"DIMM {i} Proximity Cooked Temperature ({key})" if layout == "target" else key)
            w(f"{smc}/temp{i}_input", c * 1000)
        self.smc = smc
        ct = f"{self.d}/sys/class/hwmon/hwmon1"
        w(ct + "/name", "coretemp")
        w(ct + "/temp1_label", "Package id 0")
        w(ct + "/temp1_input", 40000)
        for i, (vendor, name) in enumerate([("0x1002", "card0"), ("0x1002", "card1"), ("0x10de", "card2")]):
            dev = f"{self.d}/sys/class/drm/{name}/device"
            w(dev + "/vendor", vendor)
            hm = dev + "/hwmon/hwmon9"
            w(hm + "/temp1_label", "edge")
            w(hm + "/temp1_input", 40000)
            w(hm + "/temp2_label", "junction")
            w(hm + "/temp2_input", 40000)
        self.conf = f"{self.d}/conf.toml"
        with open(self.conf, "w") as f:
            f.write(CONF)

    def set_cpu(self, c): w(f"{self.d}/sys/class/hwmon/hwmon1/temp1_input", int(c * 1000))
    def set_gpu(self, card, c): w(f"{self.d}/sys/class/drm/{card}/device/hwmon/hwmon9/temp2_input", int(c * 1000))
    def set_smc(self, i, c): w(f"{self.smc}/temp{i}_input", int(c * 1000))
    def out(self, n, layout="t2"): return int(rd(f"{self.smc}/fan{n}_" + ("output" if layout == "t2" else "target")))
    def files(self): return sorted(os.listdir(self.smc))


def make(layout="t2"):
    mac = FakeMac(layout)
    os.environ["MACPRO_SYSFS_ROOT"] = mac.d
    import macpro_thermald
    importlib.reload(macpro_thermald)
    base = macpro_thermald.find_applesmc()
    conf = macpro_thermald.load_conf(mac.conf)
    macpro_thermald.ensure_fan_control()
    return mac, macpro_thermald, macpro_thermald.Daemon(conf, base)


class T(unittest.TestCase):
    def test_discovers_both_amd_gpus_not_nvidia(self):
        mac, m, d = make()
        gpu = [s for s in d.sources if s["name"] == "gpu"][0]
        self.assertEqual(sorted(t.name for t in gpu["temps"]), ["card0:junction", "card1:junction"])

    def test_front_fans_tied_and_side_independent(self):
        mac, m, d = make()
        mac.set_gpu("card1", 70)          # second GPU hot, first cool
        d.step(1.0)
        want = 500 + (2500 - 500) * (70 - 50) / (90 - 50)   # 1500
        self.assertEqual({mac.out(2), mac.out(3), mac.out(4)}, {1500})
        self.assertEqual(mac.out(1), 500)                   # side unaffected
        mac.set_smc(2, 60)                                  # DIMM hot
        d.step(1.0)
        self.assertEqual(mac.out(1), 500 + (1200 - 500) * (60 - 40) / 40)  # 850
        self.assertEqual({mac.out(2), mac.out(3), mac.out(4)}, {1500})

    def test_hottest_source_wins_and_rampdown_is_slow(self):
        mac, m, d = make()
        mac.set_cpu(80)
        d.step(1.0)
        self.assertEqual(mac.out(2), 2500)
        mac.set_cpu(40)
        d.step(1.0)
        self.assertEqual(mac.out(2), 2400)   # 100 rpm/s down limit
        self.assertEqual(rd(f"{mac.smc}/fan2_manual"), "1")

    def test_alarm_sends_all_fans_to_max(self):
        mac, m, d = make()
        mac.set_gpu("card0", 106)
        d.step(1.0)
        self.assertEqual([mac.out(n) for n in (1, 2, 3, 4)], [1200, 2500, 2500, 2500])

    def test_lost_critical_sensor_failsafe_after_limit(self):
        mac, m, d = make()
        os.remove(f"{mac.d}/sys/class/hwmon/hwmon1/temp1_input")   # CPU sensor vanishes
        d.step(1.0)
        self.assertNotEqual(mac.out(2), 2500)      # one miss tolerated
        d.step(1.0)
        self.assertEqual(mac.out(2), 2500)         # limit (2) reached

    def test_one_of_two_gpus_losing_its_sensor_is_a_failsafe(self):
        mac, m, d = make()
        os.remove(f"{mac.d}/sys/class/drm/card1/device/hwmon/hwmon9/temp2_input")
        d.step(1.0)
        self.assertNotEqual(mac.out(2), 2500)
        d.step(1.0)
        self.assertEqual(mac.out(2), 2500)

    def test_missing_gpu_vs_expected_count_is_a_failsafe(self):
        mac, m, d = make()
        gpu = [s for s in d.sources if s["name"] == "gpu"][0]
        gpu["expect"] = 3                  # config says 3 GPUs, only 2 present
        d.step(1.0); d.step(1.0)
        self.assertEqual(mac.out(2), 2500)

    def test_noncritical_sensor_loss_does_not_alarm(self):
        mac, m, d = make()
        os.remove(f"{mac.smc}/temp1_input"); os.remove(f"{mac.smc}/temp2_input")
        for _ in range(5):
            d.step(1.0)
        self.assertEqual(mac.out(1), 500)

    def test_garbage_probe_value_ignored_not_alarming(self):
        mac, m, d = make()
        mac.set_smc(1, -127)               # absent probe reads -127
        d.step(1.0)
        self.assertEqual(mac.out(1), 500)

    def test_foreign_writer_detected(self):
        mac, m, d = make()
        d.step(1.0)
        w(f"{mac.smc}/fan3_output", 700)   # something else overwrote the target
        self.assertEqual(d.verify(), 0)    # first mismatch tolerated
        self.assertEqual(d.verify(), 1)    # limit (2) reached
        d.all_max("test")
        self.assertEqual(mac.out(3), 2500)

    def test_mainline_73_layout(self):
        mac, m, d = make("hwmon")
        mac.set_cpu(80)
        d.step(1.0)
        self.assertEqual(mac.out(2, "hwmon"), 2500)
        self.assertEqual(rd(f"{mac.smc}/pwm2_enable"), "1")
        d.release_on_exit = True
        d.shutdown()
        self.assertEqual(rd(f"{mac.smc}/pwm2_enable"), "2")

    def test_target_only_layout_macsmc_hwmon(self):
        """7.3: no pwmN_enable/fanN_manual. The daemon must write only fanN_target
        (the old code tried pwm1_enable -> EACCES on the real sysfs) and must flip
        the fan_control module parameter, without which the driver returns EOPNOTSUPP."""
        mac, m, d = make("target")
        self.assertTrue(all(f.kind == "target" for f in d.fans.values()))
        self.assertEqual(rd(f"{mac.d}{m.FAN_CONTROL_PARAM}"), "Y")
        before = mac.files()
        mac.set_cpu(80)
        d.step(1.0)
        self.assertEqual({mac.out(n, "hwmon") for n in (2, 3, 4)}, {2500})
        self.assertEqual(mac.files(), before)                  # nothing but existing files touched
        self.assertFalse([f for f in mac.files() if f.startswith("pwm") or "manual" in f])
        d.release_on_exit = True
        d.shutdown()
        self.assertEqual([mac.out(n, "hwmon") for n in (1, 2, 3, 4)], [0, 0, 0, 0])   # 0 = back to SMC

    def test_descriptive_labels_resolve_to_keys(self):
        mac, m, d = make("target")
        dimm = [s for s in d.sources if s["name"] == "dimm"][0]
        self.assertEqual(sorted(t.name for t in dimm["temps"]), ["smc:TM0P", "smc:TM1P"])
        mac.set_smc(2, 70)
        d.step(1.0)
        self.assertEqual(mac.out(1, "hwmon"), 500 + (1200 - 500) * (70 - 40) / 40)

    def test_target_only_foreign_write_is_rearmed(self):
        mac, m, d = make("target")
        d.step(1.0)
        want = mac.out(3, "hwmon")
        w(f"{mac.smc}/fan3_target", 700)      # SMC took the fan back / another writer
        d.verify()
        self.assertEqual(mac.out(3, "hwmon"), want)   # release (0) then re-write put it back

    def test_fan_control_cannot_be_enabled(self):
        mac = FakeMac("target")
        os.environ["MACPRO_SYSFS_ROOT"] = mac.d
        import macpro_thermald as m
        importlib.reload(m)
        os.remove(f"{mac.d}{m.FAN_CONTROL_PARAM}")
        os.makedirs(f"{mac.d}{m.FAN_CONTROL_PARAM}")      # open() for write now fails
        self.assertFalse(m.ensure_fan_control())

    def test_all_max_survives_unwritable_fans(self):
        mac, m, d = make("target")
        for n in (1, 2, 3, 4):                         # writes now raise IsADirectoryError
            os.remove(f"{mac.smc}/fan{n}_target")
            os.makedirs(f"{mac.smc}/fan{n}_target")
        self.assertEqual(d.all_max("test"), 0)         # no exception, reports zero successes

    def test_max_now_exit_codes(self):
        mac, m, d = make("target")
        base = m.find_applesmc()
        self.assertEqual(m.max_now(base), 0)
        self.assertEqual([mac.out(n, "hwmon") for n in (1, 2, 3, 4)], [1200, 2500, 2500, 2500])
        os.remove(f"{mac.smc}/fan2_target")
        os.makedirs(f"{mac.smc}/fan2_target")
        self.assertEqual(m.max_now(base), m.EX_UNAVAILABLE)
        self.assertEqual(mac.out(3, "hwmon"), 2500)    # other fans still got max

    def test_no_fan_interface_exits_78(self):
        d = tempfile.mkdtemp()
        os.environ["MACPRO_SYSFS_ROOT"] = d
        import macpro_thermald as m
        importlib.reload(m)
        old = sys.argv
        sys.argv = ["x", "--max-now"]
        try:
            with self.assertRaises(SystemExit) as cm:
                m.main()
        finally:
            sys.argv = old
        self.assertEqual(cm.exception.code, 78)

    def test_shutdown_default_leaves_fans_max(self):
        mac, m, d = make()
        d.step(1.0)
        d.shutdown()
        self.assertEqual([mac.out(n) for n in (1, 2, 3, 4)], [1200, 2500, 2500, 2500])

    def test_internal_error_path_is_safe(self):
        mac, m, d = make()
        d.sources[0]["curve"] = []          # corrupt state => IndexError in interp
        try:
            d.step(1.0)
        except Exception:
            d.all_max("internal error")
        self.assertEqual(mac.out(2), 2500)


class RealConfig(unittest.TestCase):
    """The shipped config must parse and be self-consistent."""

    def test_shipped_conf(self):
        import tomllib
        with open(os.path.join(os.path.dirname(HERE), "macpro-thermald.conf"), "rb") as f:
            c = tomllib.load(f)
        fans = [n for z in c["zones"].values() for n in z["fans"]]
        self.assertEqual(sorted(fans), [1, 2, 3, 4])            # every fan owned by exactly one zone
        limits = {1: 1200, 2: 2500, 3: 2500, 4: 2500}
        for zn, z in c["zones"].items():
            top = min(limits[n] for n in z["fans"])
            for s in z["sources"]:
                cv = s["curve"]
                self.assertEqual(cv, sorted(cv), f"{zn}/{s['name']} curve not sorted")
                self.assertTrue(all(r1 >= r0 for (_, r0), (_, r1) in zip(cv, cv[1:])), "rpm must not fall")
                self.assertLessEqual(cv[-1][1], top, f"{zn}/{s['name']} asks more than the fan can do")
                self.assertGreaterEqual(s["alarm"], cv[-1][0], f"{zn}/{s['name']} alarm below curve top")
                self.assertGreaterEqual(cv[0][1], z["floor_rpm"] - 0)

    def test_real_conf_runs_against_fake_mac(self):
        mac = FakeMac()
        # give the fake mac the extra sensors the real config expects
        w(f"{mac.d}/sys/class/drm/card1/device/hwmon/hwmon9/temp3_label", "mem")
        w(f"{mac.d}/sys/class/drm/card1/device/hwmon/hwmon9/temp3_input", 50000)
        os.environ["MACPRO_SYSFS_ROOT"] = mac.d
        import macpro_thermald as m
        importlib.reload(m)
        d = m.Daemon(m.load_conf(os.path.join(os.path.dirname(HERE), "macpro-thermald.conf")), m.find_applesmc())
        d.step(1.0)
        # card0 has no junction-vs-edge difference in the fake; card0 'edge' and both 'junction' exist
        self.assertEqual({mac.out(2), mac.out(3), mac.out(4)}, {550})
        self.assertEqual(mac.out(1), 500)


if __name__ == "__main__":
    unittest.main()
