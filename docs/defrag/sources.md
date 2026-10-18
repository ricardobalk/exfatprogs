# Sources and provenance

**Bottom line:** The implementation uses public upstream sources, the published
exFAT specification, and local project code. Historical context supplied repair
ideas, but its result counts do not appear as new evidence.

Checked on 18 October 2026 in Europe/London.

- [Upstream issue 318](https://github.com/exfatprogs/exfatprogs/issues/318)
  supplies reports and investigation hypotheses. It does not prove that one
  cause produced all reported damage.
- [Release 1.3.1](https://github.com/exfatprogs/exfatprogs/releases/tag/1.3.1)
  states that upstream removed defrag from the build because of reported data
  loss.
- The [Microsoft exFAT specification](https://learn.microsoft.com/en-us/windows/win32/fileio/exfat-specification)
  is the primary format source for geometry, FAT, directories, and checksums.
  The implementation and independent tests are original code. No leaked
  implementation was used.
- The local upstream README, `Makefile.am`, `configure.ac`, and data flow through
  `defrag.c`, libexfat, and exfat_dir are the primary code sources.

This read-only command checked the upstream branch tips:

```sh
git ls-remote https://github.com/exfatprogs/exfatprogs.git refs/heads/master refs/heads/exfat-next
```

It returned:

```text
1647ed54299ae8c4343a5edf40b892307f7e6459 refs/heads/exfat-next
8b427483164888f0a5af5e4ba92da4981f1094e2 refs/heads/master
```

The selected base is the verified exfat-next tip. The supplied context patch is
based on the verified master tip. The patch was adapted for the newer I/O count
paths and `exfat_fsync`. The two context patch files have equal content. Useful
C repairs, fixture code, and interposition code were adopted and then tested
again in this work. Historical test counts do not appear as current evidence.

The full-image journal pattern was adapted from the local
`feat/exfat-resize` branch in `resize/image_resize.py`. No C resize library was
imported. Only the resize commit series was read. The independent defrag reader
does not reuse a resize or defrag engine parser, serializer, or virtual mapping.
