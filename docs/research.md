# Research

Hardware: Mac Pro 7,1, Xeon W-3265, Radeon Pro 580X + W6900X, T2. Fedora 45, t2linux kernel 7.3.x.

| Problem | Cause | Fix | Status |
|---|---|---|---|
| T2 panics (`PRP_DDR_ERR`) on boot | Built-in `iommu=pt` from the t2linux cmdline breaks ANS2 | `iommu=nopt` | Required on every entry |
| ~30 s of boot in ACPI EC timeouts | DSDT/ECDT declare a legacy EC (`PNP0C09`, ports 0x62/0x66) used only by macOS-path AML; real SMC is `APP0001` | `acpi.ec_delay=10`; kernel patch 0101 | Kernel phase 31.7 s to 2.3 s, boot 95.6 s to 53.7 s |
| ~52 s udev stall at boot | `applesmc` (legacy port 0x300 SMC) probes with -5 on a T2 MMIO SMC | Blacklist `applesmc` | Verified |
| No Bluetooth | BCM4364B3 on UART; ACPI reports BCM2E7C absent | linux-t2-patches 9003 | Works on 7.3.3-310 via livepatch + rebuilt modules; built in with 7.3.4 build |
| GPU overheats under compute (W6900X junction 96 C, 580X 94 C at 500-600 rpm) | SMC's GPU fan loop works on Linux but integrates too slowly; `t2fanrd` has no GPU zones | `macpro-thermald` | Passed 10 min combined load: front fans ~2340 rpm, 580X 80 C, CPU 65 C, W6900X junction <= 78 C |
| Power-on after shutdown unreliable | Titan Ridge functions armed as wake sources (t2linux/wiki#748) | udev rule `power/wakeup=disabled` | Applied, power-on test pending |
| APFS mount oops | NULL deref in `apfs_inode_trim_overallocation` (linux-apfs-rw#138) | Block the module | Open |
| S3 resume hangs | Probably legacy-EC ACPI paths | Suspend masked | Open |
| Power-off when switching macOS/Linux | Failure inside macOS boot.efi FileVault unlock; SMC watchdog armed by systemd suspected | `90-macpro-no-watchdog.conf` | Untested |

## Fans

- Map: F0 rear blower (RAM, PSU, flash); F1 W6900X; F2 580X; F3 CPU.
- F1-F3 (front) always share one target. F0 is separate.
- `macsmc_hwmon` writes need `fan_control=Y`. A write in `[fanN_min, fanN_max]` sets manual; `0` releases to the SMC. Success is reported even if the SMC write fails: verify by read-back, which is stale for about 0.2 s.
- Apple's firmware raised no fan up to 73 C in a macOS load test, so the curves in `macpro-thermald.conf` are our own.
- Raw SMC keys are readable through `/dev/smc`.

## Kernel notes

- Built-in cmdline is `intel_iommu=on iommu=nopt pm_async=off`; the later entry value wins on conflicts.
- Do not use `acpi_osi=!Darwin`. Do not read EC debugfs.
- `set_memory.c` W^X warning is the ITS mitigation thunk on Cascade Lake; leave ITS enabled.
