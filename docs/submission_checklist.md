# YottaFlex submission checklist

This checklist separates repository evidence from actions that require the candidate's account or a final local run. A checked box means the repository contains the artifact or the stated check was verified; it does not imply an external action such as publishing or emailing has occurred.

- [x] **Guideline 01 — Working executable code with install/run/verify steps:** `README.md`, `pyproject.toml`, `scripts/demo.sh`, and the CLI provide these instructions. Final clean-clone execution is recorded separately below.
- [ ] **Guideline 02 — Public GitHub repository with meaningful commit history:** remote configured as `https://github.com/Rahulsaisuryadevara/supplier-ack-system.git`; public visibility and remote push must be confirmed by the owner.
- [x] **Guideline 03 — Prompt history included and AI disclosure written:** `ai/prompt_history.md` and `ai/ai_disclosure.md` are present. Prompt-history completeness has an outstanding issue documented in the file.
- [x] **Guideline 04 — Reasoning visible:** `docs/decisions.md`, `docs/verification.md`, `docs/schema.md`, and `docs/data_dictionary.md` document assumptions, decisions, trade-offs, testing, and limitations.
- [ ] **FAQ 3 — Dedicated new public repository; submit link from recruitment email address:** repository remote exists, but public visibility and email submission are external actions for the candidate.
- [x] **FAQ 4 — Code, prompt history, and supporting artifacts in identifiable directories:** code is under `src/`, prompts/disclosure under `ai/`, supporting evidence under `docs/`, `reports/`, `data/samples/`, and `tests/`.
- [x] **FAQ 10 — No imported complete solution; standard dependencies and attributed snippets:** disclosure states no complete external solution or intentionally copied third-party implementation is included; no external snippet is currently listed. Recheck if any are added.
- [x] **FAQ 12 — No secrets/sensitive data; safe sample data; setup explained:** sample data is synthetic, `.gitignore` excludes local secrets and generated artifacts, and setup is in `README.md`. Run the documented secret scan before every push.
- [ ] **FAQ 2 — Latest version pushed before the 72-hour deadline:** cannot be checked until the final commit is pushed and the candidate confirms the deadline and submission.

## Final clean-clone gate

Run these commands from a fresh clone using Python 3.11+ and record the actual result before submission:

```bash
python -m pip install -e .
bash scripts/demo.sh
pytest
```

On Windows, use Git Bash for the demo script. `pytest` includes the `e2e` test and coverage reporting; the end-to-end test skips if Bash is unavailable.

## Remaining prompt-history action

The current tracked `ai/prompt_history.md` does not contain separately verifiable verbatim records for every item numbered 1–18, nor a separately identifiable original text for each fix request. The currently present file includes repeated early task text, generation-step prompts, and Prompts 19–20. Supply the missing original prompt text verbatim to complete this requirement without reconstructing or inventing it.
