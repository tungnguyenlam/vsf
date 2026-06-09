Do not use icons when coding.

This repository is developed through continuous agent collaboration.

The user will bring hypotheses, experiment ideas, and direction. The agent should execute the work end to end: inspect the existing code, make the smallest useful implementation, run relevant tests or checks, and report the outcome clearly.

Default workflow:
- Treat user ideas as implementation requests unless the user explicitly asks only to discuss.
- Prefer reusable Python modules and tests over notebook-only changes.
- Preserve existing user changes and avoid broad rewrites.
- Run focused tests after each meaningful change; run the broader test suite when the blast radius warrants it.
- Report what changed, what was verified, and any blocker or residual risk.
- Keep heavyweight model downloads, dataset downloads, and integration tests optional unless the user asks to run them.
- For this project, default to Vietnamese-only behavior unless the user explicitly asks to add English support.
