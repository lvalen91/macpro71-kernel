# macpro71-kernel

Custom Linux kernel and fixes for the Mac Pro 7,1 (2019, T2) on Fedora 45.

| Path | Contents |
|---|---|
| `kernel/` | Build script, config, patch series |
| `fixes/` | Daemon and system config derived from on-device testing |
| `docs/research.md` | Findings: cause, fix, status |

## Kernel

- Base: kernel.org 7.3.4
- Patches: [t2linux/linux-t2-patches](https://github.com/t2linux/linux-t2-patches) @ `dd9b845` (`kernel/patches/t2/`, in `series` order), including 9003 (MacPro7,1 Bluetooth)
- Local patches (`kernel/patches/local/`):
  - `0101` ACPI EC: 10 ms transaction timeout on MacPro7,1 (DMI quirk, skipped if `acpi.ec_delay` is set)
- Config (`kernel/config`): Fedora t2linux 7.3.3-310 config; built-in cmdline `intel_iommu=on iommu=nopt pm_async=off`; `LOCALVERSION=-macpro1`
- Output: `kernel-7.3.4_macpro1-N.fc45.x86_64.rpm` (about 185 MB)

```
./kernel/build.sh
sudo dnf install build/linux-7.3.4/rpmbuild/RPMS/x86_64/kernel-7.3.4_macpro1-*.rpm
```

Check before rebooting: the new loader entry has `iommu=nopt`, and the initramfs contains xfs if root is XFS.

## Fixes

| File | Purpose |
|---|---|
| `fixes/thermald/` | Zone fan control through `macsmc_hwmon` (`python3 -I tests/test_thermald.py -v`) |
| `fixes/system/kernel-cmdline` | `iommu=nopt acpi.ec_delay=10` |
| `fixes/system/90-no-applesmc.conf` | Blacklist `applesmc` |
| `fixes/system/90-no-apfs.conf` | Block `apfs` (oopsed on 7.3.3) |
| `fixes/system/90-titan-ridge-no-wakeup.rules` | Disable PCI wakeup on Titan Ridge |
| `fixes/system/90-macpro-no-watchdog.conf` | Disable systemd's SMC watchdog arming |
| `fixes/legacy/bt-livepatch/` | Bluetooth livepatch for 7.3.3-310, obsolete with patch 9003 built in |

Install paths: `.conf` files in `/etc/modprobe.d/`, the rule in `/etc/udev/rules.d/`, the watchdog file in `/etc/systemd/system.conf.d/`, the daemon as `/usr/libexec/macpro-thermald`, its config as `/etc/macpro-thermald.conf`.

## Not included

Apple firmware (Wi-Fi/Bluetooth) is not redistributable. Extract it from macOS with the t2linux firmware script.

## License

Original work: GPL-2.0-only. Kernel patches keep the licenses of the files they touch (GPL-2.0, MIT, BSD-3-Clause, ISC). See `NOTICE.md`.
