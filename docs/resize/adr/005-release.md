# ADR 005: Experimental release gate

Status: Implemented gate; release qualification is pending.

Build the host only with `--enable-experimental-resize`. Require Linux, Python,
shared libraries, and a working checker. Keep direct devices and partition
updates unavailable. A user cannot enable them with a hidden force option.

The test model does not qualify the Linux exFAT driver. Run the separate driver
suite with ten seeds and 5,000 real workload iterations per seed. Its explicit
GitHub Actions job fails if required capabilities are absent. A driver PASS is
necessary for release. It does not satisfy other open criteria. Physical
power-loss qualification and the other stated release items remain open.

The workflow runs regular image regressions and a complete small-fixture fault
sweep. A manual or scheduled full run selects 1,000 model seeds. A separate job
runs sanitizers. The workflow uploads test output, including failed synthetic
fixtures. It does not publish a release or push a branch.

No human acceptance, upstream acceptance, or production qualification is
implied by local test results. Keep the requirements matrix and qualification
procedure with the code. Keep generated results in test output or CI artifacts.
