# ADR 005: Experimental release gate

Status: Implemented gate; release qualification is pending.

Build the host only with `--enable-experimental-resize`. Require Linux, Python,
shared libraries, and a working checker. Keep direct devices and partition
updates unavailable. A user cannot enable them with a hidden force option.

The test model does not qualify the Linux exFAT driver. The current container has
no CAP_SYS_ADMIN and no loop device nodes. Its driver result is NOT_RUN, with
exit 77. The supplied driver suite requires ten seeds and 5,000 real workload
iterations per seed. Its explicit GitHub Actions job fails if required
capabilities are absent. It must pass before a release decision.

The workflow runs regular image regressions and a complete small-fixture fault
sweep. A manual or scheduled full run selects 1,000 model seeds. A separate job
runs sanitizers. The workflow uploads evidence, including failed synthetic
fixtures. It does not publish a release or push a branch.

No human acceptance, upstream acceptance, GitHub Actions execution, new cloud
snapshot restoration, or production qualification is implied by local test
results. Keep a requirements matrix and current evidence record with the code.
