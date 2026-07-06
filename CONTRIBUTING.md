# Contributing

This repository is developed as a sequence of small, reviewable learning
milestones. Each change should be understandable, testable, and safe to revert.

## Branches

- `main` is the accepted project history.
- A module is developed on `feat/module-XX-short-name`.
- Keep one module branch active until that module passes acceptance.

## Commits

Use Conventional Commits with an English summary:

```text
chore(repo): establish repository conventions
feat(api): add readiness health check
test(parser): cover python adapter fallback
docs(readme): document local startup
```

One commit should represent one completed subtask. Do not combine unrelated
cleanup or future-module scaffolding with the current task.

## Subtask workflow

1. Confirm the current module and one bounded objective.
2. Inspect the existing implementation and preserve unrelated changes.
3. Implement the smallest complete behavior.
4. Add or update focused tests and documentation.
5. Run the relevant tests and static checks.
6. Review the diff for secrets, generated files, and accidental scope growth.
7. Commit and push the verified subtask to the module branch.
8. Report the result and wait before starting another subtask.

## Acceptance rules

- Never commit `.env` files, credentials, uploaded repositories, runtime data,
  generated reports, caches, or local database volumes.
- Do not call paid model APIs from automated tests.
- Do not claim benchmark improvements without checked-in, reproducible results.
- Database schema changes require an Alembic migration and migration test.
- A module is merged into `main` only after its unit and integration checks pass.

## Verification commands

Module 01 will add the executable verification commands with the backend and
frontend toolchains. Until then, repository-only changes are checked with:

```powershell
git diff --check
git status --short
```
