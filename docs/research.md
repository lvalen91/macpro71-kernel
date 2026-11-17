# Research

Hardware: Mac Pro 7,1, Xeon W-3265, Radeon Pro 580X + W6900X, T2. Fedora 45, t2linux kernel 7.3.x.

| Problem | Cause | Fix | Status |
|---|---|---|---|
| T2 panics (`PRP_DDR_ERR`) on boot | Built-in `iommu=pt` from the t2linux cmdline breaks ANS2; cause unproven (see `iommu-ans2.md`) | `iommu=nopt` | Required on every entry |
| ~30 s of boot in ACPI EC timeouts | DSDT/ECDT declare a legacy EC (`PNP0C09`, ports 0x62/0x66) used only by macOS-path AML; real SMC is `APP0001` | `acpi.ec_delay=10`; kernel patch 0101; 0104 (opt-in `acpi.ec_skip_macpro71=1`) dropped | `ec_delay=10`: kernel phase 31.7 s to 2.3 s, boot 95.6 s to 53.7 s. 0101 verified 2026-11-16 (`ec_delay` reads 10 with no cmdline parameter); cmdline parameter dropped. 0104 failed (below) |
| ~52 s udev stall at boot | `applesmc` (legacy port 0x300 SMC) probes with -5 on a T2 MMIO SMC | `SENSORS_APPLESMC` off (7.3.3 used a blacklist) | Verified |
| No Bluetooth | BCM4364B3 on UART; ACPI reports BCM2E7C absent | linux-t2-patches 9003 | Works on 7.3.3-310 via livepatch; works on 7.3.4-macpro2 with 9003 built in, no livepatch. Runs on ROM firmware, placeholder address; Apple firmware conversion in `fixes/bluetooth/`, untested |
| `macsmc_hwmon` fan writes look successful when the SMC write failed | `return write_key(...) > 0` turns negative errors into 0 | Kernel patch 0102 | `fan_control=Y` by default verified; error path not exercised |
| GPU overheats under compute (W6900X junction 96 C, 580X 94 C at 500-600 rpm) | SMC's GPU fan loop works on Linux but integrates too slowly; `t2fanrd` has no GPU zones | `macpro-thermald` | Passed 10 min combined load: front fans ~2340 rpm, 580X 80 C, CPU 65 C, W6900X junction <= 78 C |
| Power-on after shutdown unreliable | Titan Ridge functions armed as wake sources (t2linux/wiki#748) | Kernel patch 0103 (7.3.3 used a udev rule) | 0103 verified: NHI/xHCI have no `power/wakeup`, bridges `disabled`. Power-on-after-shutdown test pending. Side effect: breaks hotplug (see macpro3 hotplug below) |
| Linux Ethernet gets a different MAC than macOS (new DHCP device/address) | Firmware returns the system MAC via `XGBE._DSM` `local-mac-address` only when `OSDW()` (Darwin); `atlantic` uses the AQC107 OTP address | `fixes/system/10-macpro-enp3s0-mac.link` | Verified, live and at boot: DHCP reservation address returned |
| APFS mount oops | NULL deref in `apfs_inode_trim_overallocation` (linux-apfs-rw#138) | `APFS_FS` off | Open |
| S3 resume hangs | Probably legacy-EC ACPI paths | Suspend masked | Open |
| Power-off when switching macOS/Linux | Firmware tried a stale `\EFI\fedora\shimx64.efi` boot entry, then fell back to macOS boot.efi, whose FileVault unlock failed and reset the machine | Boot config fix, see below | Fixed 2026-11-16: macOS -> restart -> Linux boots, no power loss |

## macOS / Linux switching

Fixed 2026-11-16 from macOS. Resulting state, checked from Linux:

| Item | Value |
|---|---|
| `BootOrder` | `0000` Linux Boot Manager (`\EFI\systemd\systemd-bootx64.efi`, ESP) first, then macOS |
| Stale entry | `\EFI\fedora\shimx64.efi` removed; no GRUB/shim on the ESP |
| Startup disk (`efi-boot-device`) | ESP, `\EFI\systemd\systemd-bootx64.efi` |
| `BridgeVersion.bin` | Copied into `\EFI\systemd\` (identical to `\EFI\BOOT\`) |
| `\EFI\systemd\drivers\apfs_x64.efi` | systemd-boot drop-in so the menu sees macOS (firmware side; Linux APFS stays off) |
| `.disk_label*` | Boot picker label |

Result: macOS -> restart -> Linux boots cleanly, no power loss. Linux -> macOS not retested.

The systemd watchdog drop-in (`RebootWatchdogSec=off` etc.) was removed with 7.3.3: macpro2 has no watchdog device (`MACSMC_WDT` off; `iTCO_wdt` has no `lpc_ich` cell to bind).

## 7.3.4-macpro2 first boot (2026-11-16)

| Check | Result |
|---|---|
| Boot time | kernel 2.75 s, initrd 6.9 s, userspace 10.7 s (7.3.3: 53.7 s total) |
| Warnings | Same set as 7.3.3, no regressions; taint `C` (t2bce staging) + `W` (amdgpu `dc_helper.c:53`, upstream) |
| Hardware | CPU 48 threads, 235 GB, EDAC; both GPUs (amdgpu); both AQC107; Wi-Fi BCM4364 (brcmfmac); Bluetooth; NVMe (SMART pass, XFS root); T2 bce/vhci/audio/NCM; macsmc hwmon/power/rtc; 4x Titan Ridge; 11 USB buses |
| Fans | `macpro-thermald` active, front fans on one target |
| `apfs`, `applesmc`, SMC watchdog | Absent, as configured |
| netconsole | Failed: built in, it starts at 2.7 s while the NIC is still `eth0` (renamed at 10.6 s). Fixed by naming the local NIC by MAC in `netconsole=` (unverified) |
| udev `90-titan-ridge-no-wakeup.rules` | 16 harmless errors on macpro2 (0103 removes `power/wakeup`); rule retired |
| `DRM_PANIC_SCREEN="qr_code"` | Falls back to `user` (QR code needs Rust); set `kmsg` in the next config |

## 7.3.4-macpro2 second boot (2026-11-16, no `acpi.ec_delay`)

| Check | Result |
|---|---|
| Patch 0101 | `/sys/module/acpi/parameters/ec_delay` = 10 with no cmdline parameter. Pass |
| Boot time | kernel 7.2 s, initrd 6.8 s, userspace 10.3 s. The extra kernel time is netconsole waiting for carrier (2.7 s to 7.1 s, then `timeout waiting for carrier`; AQC107 link up at 8.4 s), not the EC. The first boot was faster because netconsole failed at once |
| `10-macpro-enp3s0-mac.link` | Applied at boot: `enp3s0` has the macOS MAC and the reserved address |
| netconsole | Works at boot (NIC named by MAC). Receiver gets messages from ~19 s: the link is down until 8.4 s and plymouth holds the console loglevel at 1 until `console-loglevel.service` |
| Console loglevel | 7 after `console-loglevel.service` |
| Kernel warnings | Same set as the first boot and 7.3.3 (EC `AE_TIME` x11 at 10 ms each, AER `UnsupReq` burst from DSDT probes, amdgpu `dc_helper.c:53`, Thunderbolt device links, BCM4364 P2P -52). Only change: netconsole no longer fails |
| No IPv4 until 41 s | Regression from working netconsole: it brings `enp3s0` up at 2.7 s, NetworkManager assumes the existing state (IPv6 SLAAC only) and does not run DHCP. Fix: `fixes/system/91-enp3s0-no-assume.conf` (`keep-configuration=no`). Verify next boot |
| Retired workarounds still active in initrd | Initramfs was built before they were removed (Titan Ridge rule errors at 8.3 s). Rebuilt with `dracut -f` |
| Fedora module blacklists missing | They left with 7.3.3's `kernel-modules-extra`; `rds`, `l2tp_*`, `batman-adv`, `floppy` are built and were autoloadable. Restored (`fixes/system/modprobe.d/`) |

## 7.3.4-macpro2 V11: `acpi.ec_skip_macpro71=1` (2026-11-16). Fail

| Step | Result |
|---|---|
| EC skipped | DSDT region `ECOR` has no handler: `_PSW` fails on ARPT, both XGBE, XHC2-7 (`AE_NOT_EXIST`) |
| Bluetooth | `BTPU`/`BTPD` use `ECOR` and fail; `hci_uart_bcm` then oopses (NULL deref in `regulator_bulk_disable` from `bcm_gpio_set_power`, `bcm_open`) in an async probe worker |
| Boot | `/boot/efi` (vfat, module) mount hangs 45 s, probably on the dead async worker; `local-fs.target` fails; emergency shell. Shutdown also hangs (~2.5 min, forced) |
| Result | The legacy EC must stay. 0104 dropped in macpro3. The `hci_uart_bcm` error-path oops is a separate upstream bug |

Third boot (macpro2, defaults): DHCP on `enp3s0` at 17.5 s (`91-enp3s0-no-assume.conf` works). `early-dmesg` sent empty files: `dmesg` runs as `dmesg_t` and may not write to the service's socket (silent dontaudit); fix is to pipe through `cat`.

## 7.3.4-macpro3 first boot (2026-11-16). Pass

| Check | Result |
|---|---|
| `ec_delay` | 10 with no cmdline parameter (0101) |
| `ec_skip` | Absent (0104 dropped) |
| DRM panic | `kmsg`; `qr_code` fallback message gone |
| Network, Bluetooth, fans | DHCP on `enp3s0`; hci0 powered; `macpro-thermald` running, `/dev/smc` present |
| Boot | `/boot/efi` mounted; no oops; no failed units. Kernel 7.2 s (netconsole carrier wait), userspace 12.7 s |
| Warnings | Same set as macpro2: EC `_PSW`/`_REG` `AE_TIME` at probe, amdgpu `dc_helper.c:53`, one DMAR fault, early W^X (ITS thunk) |

macpro3 is now the default and only installed kernel; macpro2 removed.

## macpro3: USB-C hotplug and slow boot (2026-11-16)

| Issue | Cause | Fix | Status |
|---|---|---|---|
| Device plugged into a Thunderbolt port not detected | 0103 `device_set_wakeup_capable(false)` on `15ec` also disables runtime PME (`pci_dev_run_wake` needs `device_can_wakeup`). Controller in D3 with PME pending, never resumed | `fixes/system/90-titan-ridge-xhci-runtime-on.rules`. Proper fix: drop 0103, keep wake capable, set `power/wakeup=disabled` from a udev rule on `bind`; retest power-on after shutdown | Writing `power/control=on` enumerated the hub at once. Rule verified via `udevadm trigger`; boot unverified |
| Userspace 86 s with a USB-C hub attached | Card reader LUN stuck in `sd` spin-up; `lvm2-monitor` (scans all block devices) waited 74 s until the hub was unplugged | `fixes/system/lvm-global-filter.conf` | `pvs` skips `sd*`; `vgchange --monitor y` 0.05 s. Boot unverified |

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
