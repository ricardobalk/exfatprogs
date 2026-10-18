// SPDX-License-Identifier: GPL-2.0-or-later
/* Scoped to explicitly launched test workers and their disposable images. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

static unsigned long writes, reads, syncs;
static bool bootchecksummed, directory_injected;

static unsigned long setting(const char *name)
{
	const char *s = getenv(name);
	return s ? strtoul(s, NULL, 10) : 0;
}

static void event(const char *kind, unsigned long n, off_t offset,
		  size_t size, ssize_t result, bool injected)
{
	const char *path = getenv("EXFAT_TEST_LOG");
	char buf[256];
	int fd, len, saved = errno;

	if (path) {
		fd = open(path, O_WRONLY | O_APPEND | O_CREAT | O_NOFOLLOW, 0600);
		if (fd >= 0) {
			len = snprintf(buf, sizeof(buf),
				"{\"event\":\"%s\",\"position\":%lu,\"offset\":%lld,\"size\":%zu,\"result\":%zd,\"injected\":%s}\n",
				kind, n, (long long)offset, size, result,
				injected ? "true" : "false");
			if (len > 0 && (size_t)len < sizeof(buf))
				(void)write(fd, buf, len);
			close(fd);
		}
	}
	errno = saved;
}

/* Binary replay trace: W + LE offset/length (native little endian Linux here),
 * payload; S + two zero uint64 fields. Only records actual completed writes. */
static void persistence(char kind, off_t offset, const void *data, size_t size)
{
	const char *path = getenv("EXFAT_TEST_PERSIST_LOG");
	uint64_t fields[2] = { offset, size };
	int fd, saved = errno;

	if (path) {
		fd = open(path, O_WRONLY | O_APPEND | O_CREAT | O_NOFOLLOW, 0600);
		if (fd >= 0) {
			(void)write(fd, &kind, 1);
			(void)write(fd, fields, sizeof(fields));
			if (size)
				(void)write(fd, data, size);
			close(fd);
		}
	}
	errno = saved;
}

ssize_t pread(int fd, void *buf, size_t count, off_t offset)
{
	static ssize_t (*real_pread)(int, void *, size_t, off_t);
	unsigned long n = ++reads;
	ssize_t result;
	bool injected = false;

	if (!real_pread)
		real_pread = dlsym(RTLD_NEXT, "pread");
	if (n == setting("EXFAT_TEST_READ_EINTR_AT")) {
		errno = EINTR;
		result = -1;
		injected = true;
	} else if (n == setting("EXFAT_TEST_READ_ZERO_AT")) {
		result = 0;
		injected = true;
	} else {
		if (n == setting("EXFAT_TEST_READ_SHORT_AT") && count > 1) {
			count /= 2;
			injected = true;
		}
		result = real_pread(fd, buf, count, offset);
	}
	event("read", n, offset, count, result, injected);
	return result;
}

ssize_t pwrite(int fd, const void *buf, size_t count, off_t offset)
{
	static ssize_t (*real_pwrite)(int, const void *, size_t, off_t);
	ssize_t result;
	unsigned long n = ++writes;
	bool injected = false;

	if (!real_pwrite)
		real_pwrite = dlsym(RTLD_NEXT, "pwrite");
	if (setting("EXFAT_TEST_DIRECTORY_EIO") && bootchecksummed &&
	    !directory_injected && offset >= (1 << 20)) {
		errno = EIO;
		result = -1;
		injected = true;
		directory_injected = true;
	} else if ((setting("EXFAT_TEST_EIO_AFTER") && n >= setting("EXFAT_TEST_EIO_AFTER")) ||
	    n == setting("EXFAT_TEST_ENOSPC_AT")) {
		errno = n == setting("EXFAT_TEST_ENOSPC_AT") ? ENOSPC : EIO;
		result = -1;
		injected = true;
	} else if (n == setting("EXFAT_TEST_EINTR_AT")) {
		errno = EINTR;
		result = -1;
		injected = true;
	} else if (n == setting("EXFAT_TEST_ZERO_AT")) {
		result = 0;
		injected = true;
	} else {
		if (n == setting("EXFAT_TEST_SHORT_AT") && count > 1) {
			count /= 2;
			injected = true;
		}
		result = real_pwrite(fd, buf, count, offset);
	}
	if (result > 0) {
		persistence('W', offset, buf, result);
		if (offset == 23 * 512)
			bootchecksummed = true;
	}
	injected |= n == setting("EXFAT_TEST_SIGNAL_AT");
	event("write", n, offset, count, result, injected);
	if (n == setting("EXFAT_TEST_PAUSE_AT"))
		raise(SIGSTOP);
	if (n == setting("EXFAT_TEST_SIGNAL_AT"))
		raise((int)setting("EXFAT_TEST_SIGNAL"));
	return result;
}

int fsync(int fd)
{
	static int (*real_fsync)(int);
	unsigned long n = ++syncs;
	int result;
	bool injected = setting("EXFAT_TEST_FSYNC_ERROR") || n == setting("EXFAT_TEST_FSYNC_EINTR_AT");

	if (!real_fsync)
		real_fsync = dlsym(RTLD_NEXT, "fsync");
	if (setting("EXFAT_TEST_FSYNC_ERROR")) {
		errno = EIO;
		result = -1;
	} else if (n == setting("EXFAT_TEST_FSYNC_EINTR_AT")) {
		errno = EINTR;
		result = -1;
	} else {
		result = real_fsync(fd);
	}
	if (result == 0)
		persistence('S', 0, NULL, 0);
	event("sync", n, 0, 0, result, injected);
	return result;
}
