// SPDX-License-Identifier: GPL-2.0-or-later
/* Test-only deterministic signals and storage errors, never linked into tools. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <signal.h>
#include <stdlib.h>
#include <unistd.h>

static unsigned long writes;
static unsigned long reads;

static unsigned long setting(const char *name)
{
	const char *s = getenv(name);
	return s ? strtoul(s, NULL, 10) : 0;
}

ssize_t pread(int fd, void *buf, size_t count, off_t offset)
{
	static ssize_t (*real_pread)(int, void *, size_t, off_t);
	unsigned long n = ++reads;

	if (!real_pread)
		real_pread = dlsym(RTLD_NEXT, "pread");
	if (n == setting("EXFAT_TEST_READ_EINTR_AT")) {
		errno = EINTR;
		return -1;
	}
	if (n == setting("EXFAT_TEST_READ_SHORT_AT") && count > 1)
		count /= 2;
	return real_pread(fd, buf, count, offset);
}

ssize_t pwrite(int fd, const void *buf, size_t count, off_t offset)
{
	static ssize_t (*real_pwrite)(int, const void *, size_t, off_t);
	ssize_t result;
	unsigned long n = ++writes;

	if (!real_pwrite)
		real_pwrite = dlsym(RTLD_NEXT, "pwrite");
	if (setting("EXFAT_TEST_EIO_AFTER") && n >= setting("EXFAT_TEST_EIO_AFTER")) {
		errno = EIO;
		return -1;
	}
	if (n == setting("EXFAT_TEST_EINTR_AT")) {
		errno = EINTR;
		return -1;
	}
	if (n == setting("EXFAT_TEST_SHORT_AT") && count > 1)
		count /= 2;
	result = real_pwrite(fd, buf, count, offset);
	if (n == setting("EXFAT_TEST_SIGNAL_AT"))
		raise((int)setting("EXFAT_TEST_SIGNAL"));
	return result;
}

int fsync(int fd)
{
	static int (*real_fsync)(int);

	if (!real_fsync)
		real_fsync = dlsym(RTLD_NEXT, "fsync");
	if (setting("EXFAT_TEST_FSYNC_ERROR")) {
		errno = EIO;
		return -1;
	}
	return real_fsync(fd);
}
