# AI-Use Disclosure

This project was developed with substantial AI assistance. This document describes how AI was used, what I personally contributed, and the areas where I relied most heavily on AI.

## How AI Was Used

I planned the project as a sequence of 21 staged prompts, with acceptance checklists, required commit messages, and verification steps. The work was carried out with an AI coding assistant across two conversations: the first reached its context limit, and a context handover continued the work. A second AI assistant (Vibe) helped me plan the prompt sequence and structure the verification routine.

AI generated most of the implementation, including the schema, application code, tests, and documentation. I directed the development through the staged requirements, evaluated the outputs, and decided when to accept, fix, or rework them.

## What I Personally Contributed

- **Prompt planning and requirements:** I developed and iterated the staged prompt plan, including architecture requirements, ID conventions, threshold values, acceptance criteria, and the intended commit sequence. The recorded prompts are documented in `ai/prompt_history.md`.
- **Local verification on Windows:** I installed the project dependencies, ran the test suite, exercised the demonstration script, checked reproducibility, and ran the CLI doctor check. The latest recorded test run completed with 182 passing tests, no failures, no skips, and 80% coverage. I ran scripts/demo.sh end-to-end on my machine; all six stages passed.
- **Identifying and correcting integration issues:** I found issues by running the project in my local Windows environment and requested targeted fixes:
  1. Workflow tests used hardcoded `/tmp` paths that worked in the AI's Linux environment but failed on Windows. I isolated the cross-platform compatibility issue and requested a fix.
  2. `matplotlib` and `tabulate` were imported but were missing from the declared project dependencies. I identified the problem during a clean installation and requested that the dependencies be declared.
  3. The `generate` command's default output directory did not match the tests' expectations. I identified the mismatch through local test execution and requested a correction during Prompt 19's Task 0.
- **Acceptance checks and milestones:** I checked deliverables against the relevant prompt acceptance criteria before proceeding to subsequent phases. I also pushed project milestones to GitHub; I pushed milestones to GitHub at five checkpoints during development.

## Where I Relied Most on AI

The schema and DDL details, generator implementation, workflow engine internals, and breadth of the test suite were primarily AI-generated. My review of these areas is not as exhaustive as the size of the implementation might suggest.

I do not claim production-grade correctness or that the encoded business policies are universally valid. This project uses synthetic data, and its tests establish behavior only for the paths and conditions they exercise.

## Ownership and Technical Understanding

My role included defining requirements, directing implementation, checking outputs, identifying environment and integration issues, and verifying the resulting behavior. I can explain the core rules and design choices, including the price tolerance of ±5%, the seven-day delivery slip, the 10% quantity-shortfall threshold, approval-gated plan updates, the four labelled anomaly classes, and the use of SQLite and seeded deterministic generation.

The detailed decisions and verification evidence are documented in `docs/decisions.md` and `docs/verification.md`, respectively.

## External Code and Licensing

I did not intentionally include a complete external solution or copied implementation. The project's declared dependencies are listed in `pyproject.toml` and remain subject to their respective licenses. The project code is released under the MIT license (see LICENSE).