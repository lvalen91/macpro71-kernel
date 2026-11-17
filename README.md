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
  - `0101` ACPI EC: 10 ms transaction timeout on MacPro7,1 (DMI quirk, skipped if `acpi.ec_delay` is set). Verified
  - `0102` hwmon macsmc: return fan write errors (they were turned into success); fan control on by default on x86
  - `0103` PCI: Titan Ridge NHI/xHCI not wake-capable on MacPro7,1
  - `0104` (opt-in skip of the legacy EC) dropped in macpro3: the DSDT needs the EC region (see `docs/research.md`)
- Config (`kernel/config`), from the Fedora t2linux 7.3.3-310 config:
  - Built-in cmdline `intel_iommu=on iommu=nopt pm_async=off no_console_suspend`; `LOCALVERSION=-macpro3`
  - `X86_NATIVE_CPU=y`, `NR_CPUS=64`, Intel CPU support only
  - Off: `SENSORS_APPLESMC`, `APFS_FS`, `MACSMC_WDT`, Xen, Hyper-V, TDX (guest and host), VMware/VirtualBox guests, AMD-CPU drivers, laptop-vendor platform drivers, `SND_SOC`
  - Built in: `XFS_FS`, `AQTION` (AQC107), `NETCONSOLE`
  - Kept: all USB, Thunderbolt, PCI, storage, network, filesystem and GPU drivers (plug-in hardware)
  - `DRM_PANIC_SCREEN=kmsg`
  - S3 debug options: see `docs/s3-debug.md`
- Output: `kernel-7.3.4_macpro3-N.fc45.x86_64.rpm`
- Status: macpro3 boots and runs all hardware on the Mac Pro 7,1 and is the installed default (2026-11-16); results in `docs/research.md`. `netconsole=` must name the NIC by MAC (built-in netconsole starts before interface renaming)

```
./kernel/build.sh
sudo dnf install build/linux-7.3.4/rpmbuild/RPMS/x86_64/kernel-7.3.4_macpro3-*.rpm
```

Check before rebooting: the new loader entry has `iommu=nopt`, and the initramfs contains what the root needs. The build uses `-march=native`: build on the machine that runs it.

## Fixes

| File | Purpose |
|---|---|
| `fixes/thermald/` | Zone fan control through `macsmc_hwmon` (`python3 -I tests/test_thermald.py -v`) |
| `fixes/system/kernel-cmdline` | `iommu=nopt` (patch 0101 sets the EC delay) |
| `fixes/system/10-macpro-enp3s0-mac.link` | Give `enp3s0` the macOS MAC (firmware passes it to macOS only) so DHCP sees one device |
| `fixes/system/91-enp3s0-no-assume.conf` | NetworkManager drop-in: run DHCP on `enp3s0` even though netconsole has already brought it up |
| `fixes/system/modprobe.d/` | Fedora's autoload blacklists (`rds`, `l2tp_*`, `batman-adv`, `floppy`). They come with `kernel-modules-extra`, which this kernel's RPM does not replace |
| `fixes/system/console-loglevel.service` | `dmesg -n 7` after plymouth, so netconsole gets more than `KERN_EMERG` |
| `fixes/bluetooth/` | Hex to `.hcd` converter for Apple's BCM4364B3 firmware (untested) |

7.3.3-era workarounds (`applesmc`/`apfs` blacklists, Titan Ridge udev rule, watchdog drop-in, `netconsole-late.service`, Bluetooth livepatch) are retired: the `macpro2` config and patches replace them. They are in git history before commit c3e7659. After removing files that the initramfs copies (`/etc/modprobe.d`, `/etc/udev/rules.d`, `/etc/systemd/system.conf.d`), run `sudo dracut -f`, or the initramfs keeps applying them.

Install paths: the daemon as `/usr/libexec/macpro-thermald`, its config as `/etc/macpro-thermald.conf`, the unit in `/usr/lib/systemd/system/`.

## Docs

- `docs/research.md`: problem, cause, fix, status; macOS/Linux switching fix; first-boot results
- `docs/iommu-ans2.md`: why `iommu=pt` panics the T2, and safe ways to investigate
- `docs/s3-debug.md`: suspend debug setup and procedure

## Not included

Apple firmware (Wi-Fi/Bluetooth) is not redistributable. Extract it from macOS with the t2linux firmware script.

## License

Original work: GPL-2.0-only. Kernel patches keep the licenses of the files they touch (GPL-2.0, MIT, BSD-3-Clause, ISC). See `NOTICE.md`.
