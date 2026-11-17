# Bluetooth firmware (BCM4364B3, UART)

Status: **untested**. Bluetooth works on ROM firmware without any file here. This is an attempt to load Apple's runtime firmware.

- The kernel asks for `/lib/firmware/brcm/BCM4362A2.hcd` (the name the ROM reports), then `brcm/BCM.hcd`.
- Apple's `BCM4364B3-MiniDriver-uart.hex` is an 8 KB bootstrap. `BCM4364B3ID2-Updater.hex` and `…ID3-Updater.hex` (about 62 KB) look like the runtime image. Which ID this unit uses is unknown.
- The firmware is Apple's and is not in this repo. Extract it from your own macOS install.

`hex2hcd.py` converts Intel HEX to `.hcd` (`convert`) and checks the result (`verify`). Stdlib only.

```
./hex2hcd.py convert BCM4362A2.hcd BCM4364B3ID2-Updater.hex
./hex2hcd.py verify  BCM4362A2.hcd BCM4364B3ID2-Updater.hex
./hex2hcd.py convert --mini-launch auto BCM4362A2.hcd BCM4364B3-MiniDriver-uart.hex BCM4364B3ID2-Updater.hex
```

Guesses: the Updater has no EOF record, so a launch to `0xFFFFFFFF` is appended; the minidriver launch address `0x00100300` comes from its EOF record offset.

Try in order: Updater ID2, Updater ID3, MiniDriver + ID2, MiniDriver + ID3.

```
sudo install -m 644 BCM4362A2.hcd /lib/firmware/brcm/BCM4362A2.hcd
# reload hci_uart or reboot; success: "BCM4362A2 'brcm/BCM4362A2.hcd' Patch" in dmesg, no "Patch command ... failed"
```

Rollback: `sudo rm /lib/firmware/brcm/BCM4362A2.hcd`, then reboot. If Bluetooth stays wedged, cold power cycle (the driver logs "No reset resource").
