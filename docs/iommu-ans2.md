# ANS2 and `iommu=pt`

`iommu=nopt` is proven. Keep it on every entry. Do not boot with `iommu=pt` to test.

## Evidence

- 2026-10-06, `intel_iommu=on iommu=pt`: about 5 min after boot the T2 panicked and cut power. bridgeOS log: `ANS2 Recoverable Panic - assert failed: PRP_DDR_ERR ... OP 2` (a read). It is an assert in ANS2 firmware on a PRP (host data pointer) fault. No host-side error was captured.
- Same day, `iommu=nopt`: 1 h 50 min of SSD reads under load (stress-ng on 48 CPUs, memtester 210 GB), no panic.
- The t2linux wiki added `iommu=pt` for the MacBook microphone, not for storage.
- The Mac Pro has 235 GB of RAM at physical addresses up to 38 bits. `nopt` makes the kernel give ANS2 bus addresses below 4 GiB first. `pt` gives raw physical addresses.
- The T2's bridge driver sets a 37-bit DMA mask. Nothing else suggests an address limit.
- ANS2 and the three other T2 functions share IOMMU group 72, behind root port 00:1b.0. Every group is `DMA-FQ` now.

## Hypotheses (guesses, n = 1)

1. ANS2 or the T2's PCIe path cannot address all of host RAM (above 4 GiB, perhaps above 36-37 bits).
2. ANS2 needs addresses in a specific window.
3. Passthrough for group 72 breaks something else the T2 does with bus addresses. Weak: the assert is on a PRP.
4. Intel passthrough quirk on this platform. Low: the other 130+ groups work under `pt`.
5. Coincidence.

## Tests

| Safe | Risky (can reproduce the panic and power loss) |
|---|---|
| Read-only inspection, offline log analysis | Any boot with `iommu=pt` |
| QEMU with `-device intel-iommu` and an emulated NVMe with id 106b:2005: checks that the domain selection below yields `DMA`; says nothing about ANS2 | `echo DMA > /sys/kernel/iommu_groups/72/type` |
| Building a patched kernel without installing it | `iommu.forcedac=1` |

## Quirk (not applied; not in this build)

Keep group 72 translated while the rest gets passthrough, so `iommu=nopt` is no longer needed globally. In `drivers/iommu/intel/iommu.c`, `device_def_domain_type()`:

```c
if (pdev->vendor == PCI_VENDOR_ID_APPLE &&
    (pdev->device == 0x2005 || pdev->device == 0x1801 ||
     pdev->device == 0x1802 || pdev->device == 0x1803))
	return IOMMU_DOMAIN_DMA;
```

The core prefers a non-zero driver answer over the global default. Intel IOMMU only; needs `intel_iommu=on`. It only helps if hypothesis 1 or 2 is right.

First hardware step, if pursued: boot the patched kernel with `modprobe.blacklist=nvme` and check `/sys/kernel/iommu_groups/72/type`, with the internal SSD not mounted.
