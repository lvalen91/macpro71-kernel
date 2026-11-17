# Licenses

This repo mixes original work with third-party kernel patches. Each part keeps its own license; nothing is relicensed.

## Original work: GPL-2.0-only

Copyright (C) 2026 lvalen91. Text in `LICENSE` and `LICENSES/GPL-2.0-only.txt`.

- `fixes/` (thermald, system config, Bluetooth converter, `bt-livepatch`)
- `kernel/build.sh`
- `docs/`, `README.md`, this file

## Kernel patches (`kernel/patches/`)

A patch is licensed as the kernel file it adds or modifies. The patches here add or touch files under:

| License | Where it appears |
|---|---|
| GPL-2.0-only, GPL-2.0-or-later | Most of the kernel; the T2 BCE, macsmc, trackpad and HID code |
| GPL-2.0 OR MIT, GPL-2.0-only OR MIT | macsmc, SMS, keyboard-backlight and trackpad drivers (Asahi-derived) |
| MIT | amdgpu, i915 and DRM files (some without an SPDX tag; the license is in the file header) |
| BSD-3-Clause | Parts of the APFS driver (`8001`) |
| ISC | brcmfmac Wi-Fi driver (`9003-PATCH-wireless…`, `9005`, `9006`, `9007`) |

The kernel as a whole, and any binary built from it, is GPL-2.0-only.

- `patches/t2/`: copied unmodified from [t2linux/linux-t2-patches](https://github.com/t2linux/linux-t2-patches) @ `dd9b845`. Authors are in each patch header.
- `patches/local/`: each patch takes the license of the file it modifies: `0101`, `0104` `drivers/acpi/ec.c` (GPL-2.0-or-later); `0102` `drivers/hwmon/macsmc-hwmon.c` (GPL-2.0-only OR MIT); `0103` `drivers/pci/quirks.c` (GPL-2.0).
- `kernel/config`: derived from the Fedora t2linux kernel config (GPL-2.0-only).

## Not included

Apple Wi-Fi and Bluetooth firmware is proprietary and not redistributable. Extract it from your own macOS install.

## Texts

`LICENSES/` holds the full text of each license above (GPL-2.0-only, MIT, BSD-3-Clause, ISC).
