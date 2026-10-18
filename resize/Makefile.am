# The shared library is private. Do not install the unjournaled engine as a CLI.
AM_CFLAGS = -std=c11 -Wall -Wextra -Wpedantic -I$(srcdir)/vendor/include -I$(srcdir)/vendor/lib
resizelibdir = $(libexecdir)/exfatprogs-resize
resizelib_LTLIBRARIES = libresize-image.la
libresize_image_la_LDFLAGS = -avoid-version -module
libresize_image_la_SOURCES = bridge.c \
 vendor/lib/allocation.c vendor/lib/block_device.c vendor/lib/boot_region.c \
 vendor/lib/checked_math.c vendor/lib/directory.c vendor/lib/endian.c \
 vendor/lib/event.c vendor/lib/geometry.c vendor/lib/grow.c vendor/lib/resize.c \
 vendor/lib/sector_adapter.c vendor/lib/shrink.c vendor/lib/stream.c vendor/lib/volume.c
resizelib_PYTHON = image_resize.py
sbin_SCRIPTS = resize.exfat
CLEANFILES = resize.exfat
EXTRA_DIST = resize.exfat.in \
 tests/driver.py \
 tests/fixture.py \
 tests/baselines/image-host-before-cancel-fix.py \
 tests/baselines/image-host-before-container-check.py \
 tests/baselines/reader-before.py \
 tests/cancel_commit.py \
 tests/container.py \
 tests/fsck_regression.py \
 tests/large_faults.py \
 tests/nofat.py \
 tests/reader.py \
 tests/regressions.py \
 tests/run.py \
 tests/signals.py \
 tests/test_host.py \
 vendor/LICENSE \
 vendor/ORIGIN \
 vendor/docs/LIBRARY.md \
 vendor/docs/TRANSACTION.md \
 vendor/include/exfat_resize.h \
 vendor/lib/allocation.c \
 vendor/lib/allocation.h \
 vendor/lib/block_device.c \
 vendor/lib/block_device.h \
 vendor/lib/boot_region.c \
 vendor/lib/boot_region.h \
 vendor/lib/checked_math.c \
 vendor/lib/checked_math.h \
 vendor/lib/common.h \
 vendor/lib/directory.c \
 vendor/lib/directory.h \
 vendor/lib/endian.c \
 vendor/lib/endian.h \
 vendor/lib/event.c \
 vendor/lib/event.h \
 vendor/lib/geometry.c \
 vendor/lib/geometry.h \
 vendor/lib/grow.c \
 vendor/lib/grow.h \
 vendor/lib/resize.c \
 vendor/lib/resize_internal.h \
 vendor/lib/sector_adapter.c \
 vendor/lib/sector_adapter.h \
 vendor/lib/shrink.c \
 vendor/lib/shrink.h \
 vendor/lib/stream.c \
 vendor/lib/stream.h \
 vendor/lib/volume.c \
 vendor/lib/volume.h \
 vendor/tests/library/CMakeLists.txt \
 vendor/tests/library/integration/api_tests.c \
 vendor/tests/library/integration/mechanism_tests.c \
 vendor/tests/library/integration/resize_tests.c \
 vendor/tests/library/integration/shrink_materialization_tests.c \
 vendor/tests/library/integration/shrink_tests.c \
 vendor/tests/library/integration/shrink_transaction_tests.c \
 vendor/tests/library/integration/transaction_tests.c \
 vendor/tests/library/support/exfat_fixture.c \
 vendor/tests/library/support/exfat_fixture.h \
 vendor/tests/library/support/memory_block_device.c \
 vendor/tests/library/support/memory_block_device.h \
 vendor/tests/library/support/shrink_fixture.c \
 vendor/tests/library/support/shrink_fixture.h \
 vendor/tests/library/support/test_allocator.c \
 vendor/tests/library/support/test_allocator.h \
 vendor/tests/library/unit/boot_region_tests.c \
 vendor/tests/library/unit/foundation_tests.c \
 vendor/tests/library/unit/geometry_tests.c
resize.exfat: $(srcdir)/resize.exfat.in Makefile
	$(AM_V_GEN)sed -e 's|@RESIZE_MODULE_DIR@|$(resizelibdir)|g' -e 's|@RESIZE_SOURCE_DIR@|$(abs_srcdir)|g' $(srcdir)/resize.exfat.in > $@
	chmod +x $@
check-local: all
	RESIZE_LIBRARY=$(abs_builddir)/.libs/libresize-image.so $(PYTHON) $(srcdir)/tests/run.py --library-only
