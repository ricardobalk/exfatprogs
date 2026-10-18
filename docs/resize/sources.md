# Sources and baseline

## Repository state

The requested repository `ricardobalk/exfatprogs` had no advertised references,
commits, source files, or local changes. No AGENTS.md file was present under
`/workspace`. The origin remote was retained. No push was performed.

The official remote is <https://github.com/exfatprogs/exfatprogs>.
The inspected master was `8b427483164888f0a5af5e4ba92da4981f1094e2`.
The working branch is `feat/exfat-resize`. Its base is exfat-next commit
`1647ed54299ae8c4343a5edf40b892307f7e6459`. The upstream README requires
contributions to use exfat-next and signed-off commits. Both remote branches and
tags were fetched. No upstream resize CLI was found.

The base includes `defrag/defrag.c`, `defrag/defrag.h`, build files, and
`manpages/defrag.exfat.8`. These files were inspected. The defrag code is not
used by resize. Its interruption comments do not establish resize recovery.
No defrag test counts or safety claims were reused.

The initial native toolchain was Debian 13, x86-64 Linux, GCC 14.2.0, GNU Make
4.4.1, and Python 3.12. Machine-readable results record the exact platform and
source hashes. The final clean build used two jobs. The model campaign used three jobs on
five available CPUs. No application service, credential, mount, or real device was required.

## Normative on-disk source

Microsoft: [exFAT file system specification](https://learn.microsoft.com/en-us/windows/win32/fileio/exfat-specification).
The direct documentation host was blocked in the setup network. The official
MicrosoftDocs/win32 source was read through the existing Git proxy:

- Repository: <https://github.com/MicrosoftDocs/win32>
- Commit: `ca8274decead49403d70ceeed4af8d4ca74eaf11`
- File: `desktop-src/FileIO/exfat-specification.md`
- Revision described: exFAT 1.00.

Sections 3.1 and 3.4 define geometry, excluded checksum fields, and both boot
regions. Section 4 defines FAT links and bad markers. Sections 6 and 7 define
entry sets, flags, ValidDataLength, bitmap, upcase, and vendor entries.
Section 7.2.3 states that the upcase table uses a cluster chain described by
the FAT. A contiguous read from FirstCluster is insufficient for that stream.

## Reused implementation

- Project: <https://github.com/huven/exfat-resize>
- Commit: `870ca5a66591405cd536556b1114d045c94cefff`
- License: MIT; copyright Richard Huveneers, 2026.
- Imported scope: portable C engine, C API header, library tests, and two API
  documents. The upstream CLI and device/partition code were not imported.

The source and transaction document were inspected before reuse. The engine
validates allocation ownership and can move the heap for FAT expansion. Shrink
can move system streams, convert NoFatChain files, and update directory owners.
The original transaction has no journal or automatic rollback. A dirty flag and
successful final flush alone do not meet this task's recovery requirement.
The new host therefore supplies a separate, mandatory durable undo protocol.
The imported tests are regression inputs. They are not accepted as qualification
results until they run in this checkout.

The low-level tests share the engine's private primitives. The Python reader and
exfatprogs checker do not call those primitives. The fixture serializer imports
some reader helpers for base geometry and checksums. This shared test code is
explicit. It limits the independence of fixture construction from the Python
reader. The separate C checker and external logical-byte model supply additional
checks. Linux-driver tests are also required for release; see
[qualification](qualification.md) for the procedure. Other release criteria
remain open.

## CI setup

The resize workflow installs the Debian build and test dependencies, enables
experimental resize, and builds the checked-out revision. It writes generated
reports and failure fixtures outside the source tree and uploads them as job
artifacts. No service needs startup.
