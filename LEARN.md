# Learn Log

## 2026-09-25 — video-cli documentation

- Reused the `sound-cli` and `image-cli` documentation structure while treating the video command implementations and `video --help` output as the source of truth.
- Documented all nine discovered commands, local versus Modal routing, stdout/stderr contracts, integrations, troubleshooting, and extension points.
- Verified the documented command surface with `video --help` and each command's `--help` output.
- Baseline test run: 10 tests passed; 6 media regression tests could not run because `moviepy` and `faster_whisper` are not installed in the current environment.
- Keep future CLI documentation synchronized with the root tool index and verify claims against the current help text before publishing.
