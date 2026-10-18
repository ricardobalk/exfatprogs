// SPDX-License-Identifier: GPL-2.0-or-later
/* Image host ABI. The portable engine API is in vendor/include/exfat_resize.h.
 */
#include "exfat_resize.h"
#include <stdlib.h>

static void *image_allocate(void *context, size_t size)
{
	(void)context;
	return malloc(size);
}

static void image_free(void *context, void *memory, size_t size)
{
	(void)context;
	(void)size;
	free(memory);
}

static const struct exfat_resize_allocator image_allocator = {
	.context = NULL,
	.allocate = image_allocate,
	.deallocate = image_free,
};

int image_inspect(const struct exfat_resize_block_device *device,
		  uint64_t target, struct exfat_resize_plan *plan)
{
	return exfat_resize_inspect(device, target, &image_allocator, plan);
}

int image_resize(const struct exfat_resize_block_device *device,
		 uint64_t target, const struct exfat_resize_monitor *monitor,
		 enum exfat_resize_stage *stage)
{
	return exfat_resize(device, target, &image_allocator, monitor, stage);
}
