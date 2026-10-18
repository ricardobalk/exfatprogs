# ADR 005: Experimental release gate

Status: Implemented gate; release qualification is pending.

Build the host only with `--enable-experimental-resize`. Require Linux, Python,
shared libraries, and a working checker. Keep direct devices and partition
updates unavailable. A user cannot enable them with a hidden force option.

The test model does not qualify the Linux exFAT driver. The earlier container
could not run the driver suite. The specified suite later passed in a VM with
ten seeds and 5,000 real workload iterations per seed. See
[qualification](../qualification.md) for the kernel, geometry, source identity,
and reached counts. Its explicit GitHub Actions job fails if required
capabilities are absent. A driver PASS is necessary for release. It does not
satisfy other open criteria. Physical power-loss qualification and the other
stated release items remain open.

The workflow runs regular image regressions and a complete small-fixture fault
sweep. A manual or scheduled full run selects 1,000 model seeds. A separate job
runs sanitizers. The workflow uploads evidence, including failed synthetic
fixtures. It does not publish a release or push a branch.

No human acceptance, upstream acceptance, GitHub Actions execution, new cloud
snapshot restoration, or production qualification is implied by local test
results. Keep a requirements matrix and current evidence record with the code.
