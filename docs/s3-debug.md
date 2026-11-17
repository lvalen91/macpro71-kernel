# S3 resume hang: debug setup

Suspend is masked (`sleep.target`, `suspend.target`). Resume hangs; the journal ends at `Successfully froze unit 'user.slice'`. Probable cause: legacy-EC ACPI paths. Unconfirmed.

## Built into the kernel for this

| Setting | Purpose |
|---|---|
| `no_console_suspend` (built-in cmdline) | Console keeps printing during suspend |
| `NETCONSOLE=y`, `NETCONSOLE_DYNAMIC=y`, `AQTION=y` | Log over the network from early boot, through suspend |
| `PM_SLEEP_DEBUG`, `PM_ADVANCED_DEBUG`, `PM_DEBUG` | `pm_test`, `pm_print_times`, `pm_debug_messages` |
| `DPM_WATCHDOG` (120 s) | Dumps the stack of a device whose suspend or resume callback hangs |
| `DYNAMIC_DEBUG`, `ACPI_DEBUG` | Per-file debug prints |
| `acpi.ec_skip_macpro71=1` (opt-in) | Test without the legacy EC |

## Netconsole

Replaces `netconsole-late.service`, which does `modprobe netconsole` and fails when it is built in. Disable that service on this kernel. Add to the loader entry (use your own addresses):

```
netconsole=+6665@<local-ip>/<dev>,6666@<receiver-ip>/<receiver-mac>
```

Receiver: `nc -u -l 6666`. Set `dmesg -n 8` before testing.

## Procedure

`pm_test` runs part of the suspend path and resumes after 5 s, without entering S3. Go one level at a time, and stop at the first hang.

```
sudo systemctl unmask sleep.target suspend.target
echo 1 | sudo tee /sys/power/pm_print_times /sys/power/pm_debug_messages
for lvl in freezer devices platform processors core; do
  echo $lvl | sudo tee /sys/power/pm_test
  echo mem  | sudo tee /sys/power/state     # returns after ~5 s
done
echo none | sudo tee /sys/power/pm_test     # real S3, last
```

1. `freezer`, `devices`: user space and device callbacks. A hang here names a driver in the netconsole log (`PM: calling ...` with `pm_print_times`, or the `DPM_WATCHDOG` stack).
2. `platform`, `processors`, `core`: ACPI firmware and CPU offline. A hang here points at the EC or ACPI.
3. `none`: real S3.

Then repeat with `acpi.ec_skip_macpro71=1` on a one-shot entry.

## Recovery

A hung machine needs a power-button hold (T2 force-off). After a boot loop with `t2bce_vhci: Possible desync`, unplug mains for 60 s.

Re-mask when done: `sudo systemctl mask sleep.target suspend.target`.
