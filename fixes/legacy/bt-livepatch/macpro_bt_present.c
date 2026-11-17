// SPDX-License-Identifier: GPL-2.0
/*
 * Livepatch stand-in for the drivers/acpi/x86/utils.c hunk of
 * linux-t2-patches 9003 ("Bluetooth: enable internal controller on
 * MacPro7,1"). The MacPro7,1 firmware reports BCM2E7C (UID 1) as not
 * present under the Darwin OSI; force it present.
 *
 * On MacPro7,1 (Skylake-X family CPU) no other entry of the stock
 * override_status_ids[] table can match, so returning false for every
 * other device is identical to the original function. The module
 * refuses to load on any other machine.
 *
 * Only for 7.3.3-310.t2.fc45; kernels carrying 9003 do not need it.
 */
#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>
#include <linux/acpi.h>
#include <linux/dmi.h>
#include <asm/cpu_device_id.h>
#include <asm/intel-family.h>

static const struct x86_cpu_id skx[] = {
	X86_MATCH_VFM(INTEL_SKYLAKE_X, NULL),
	{}
};

static bool lp_acpi_device_override_status(struct acpi_device *adev,
					   unsigned long long *status)
{
	if (acpi_dev_hid_uid_match(adev, "BCM2E7C", "1")) {
		*status = ACPI_STA_DEVICE_PRESENT | ACPI_STA_DEVICE_ENABLED |
			  ACPI_STA_DEVICE_UI | ACPI_STA_DEVICE_FUNCTIONING;
		return true;
	}
	return false;
}

static struct klp_func funcs[] = {
	{
		.old_name = "acpi_device_override_status",
		.new_func = lp_acpi_device_override_status,
	}, { }
};

static struct klp_object objs[] = {
	{ .funcs = funcs, }, { }
};

static struct klp_patch patch = {
	.mod = THIS_MODULE,
	.objs = objs,
};

static int __init macpro_bt_present_init(void)
{
	if (!x86_match_cpu(skx) ||
	    !dmi_match(DMI_SYS_VENDOR, "Apple Inc.") ||
	    !dmi_match(DMI_PRODUCT_NAME, "MacPro7,1")) {
		pr_info("not a MacPro7,1, not loading\n");
		return -ENODEV;
	}
	int ret;
	struct acpi_device *adev;

	ret = klp_enable_patch(&patch);
	if (ret)
		return ret;

	/*
	 * When loaded after boot, the status cached by the ACPI scan is
	 * still "not present"; refresh it for BCM2E7C so cdc-acm and
	 * serdev can find the device.
	 */
	adev = acpi_dev_get_first_match_dev("BCM2E7C", "1", -1);
	if (adev) {
		acpi_dev_put(adev);	/* already present */
		return 0;
	}
	{
		acpi_handle h;

		if (ACPI_SUCCESS(acpi_get_handle(NULL,
				"\\_SB.PCI0.XHC1.RHUB.HS06.URT0.BLTH", &h))) {
			adev = acpi_fetch_acpi_dev(h);
			if (adev && acpi_dev_hid_uid_match(adev, "BCM2E7C", "1")) {
				acpi_set_device_status(adev, ACPI_STA_DEVICE_PRESENT |
						       ACPI_STA_DEVICE_ENABLED |
						       ACPI_STA_DEVICE_UI |
						       ACPI_STA_DEVICE_FUNCTIONING);
				pr_info("BCM2E7C marked present\n");
			}
		}
	}
	return 0;
}

static void __exit macpro_bt_present_exit(void)
{
}

module_init(macpro_bt_present_init);
module_exit(macpro_bt_present_exit);
MODULE_LICENSE("GPL");
MODULE_INFO(livepatch, "Y");
MODULE_DESCRIPTION("MacPro7,1: report BCM2E7C Bluetooth as present (t2 patch 9003 stand-in)");
