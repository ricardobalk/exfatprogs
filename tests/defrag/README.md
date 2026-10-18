# Experimental defrag qualification

**Bottom line:** Run the smoke command for a quick regression check. Run the
full command before you change a release claim. The normal build and install
keep defrag disabled. The C binary from this test build is an internal worker.
It has no journal. Use `defrag/defrag.exfat` as the experimental image-file
interface.

Read [the complete scope and protocol](../../docs/defrag/README.md) before use.

Run these commands from the repository root:

```sh
python3 tests/defrag/qualify.py --out defrag-test-results-smoke
python3 tests/defrag/qualify.py --full --driver --jobs 4 \
  --out defrag-test-results-full
```

The full run executes 1,000 seeds with 5,000 model iterations. It adds capacity
cases. It runs the model with native and ASan/UBSan builds and leak detection.
It also tests all small-fixture worker writes, journal boundaries, commit,
recovery, publication, persistence, negative checks, metadata, and existing
upstream fixtures. With `--driver`, it runs ten seeds with 5,000 real driver
workload iterations. If driver capabilities are absent, the result is NOT_RUN.
This blocks the related claim. The smoke run does not represent the full
qualification program.

The `Experimental defrag qualification` GitHub Actions workflow runs smoke
tests with GCC and Clang for relevant pushes and pull requests. It also runs
focused sanitizer tests. A scheduled or manual job runs the full rootless
program. A separate manual job runs the privileged Linux-driver tests. Each job
uploads its evidence directory.

Results use JSON or JSONL, including failures. A failed case keeps image files,
journals, operation logs, and expected manifests. A successful large case
removes its temporary image. Source and binary hashes and reached fault
positions make the counts reviewable. Files in `context/` are historical input.
They are not current evidence.
