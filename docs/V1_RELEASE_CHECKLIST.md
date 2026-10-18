# AffordAbled v1 Release Checklist

This checklist prepares the current feature branch for a first release. It does not declare the application release-ready. Complete and record each release gate before tagging or deploying `v1.0.0`.

## Release scope

The current product includes authenticated personal finance accounts, categories, and transactions; chat-driven finance workflows; receipt and voice ingestion; transaction review before writes; transaction analytics; split creation, repayment, and itemized receipt allocations; CSV/XLSX transaction import and safe report export; and user-controlled shared preference memory.

## Gates to complete

### Automated checks

- [x] Full API suite: `python -m pytest -q` from `apps/api` (111 passed).
- [x] API lint: `ruff check .` from `apps/api`.
- [x] Web lint: `npm run lint` from `apps/web`.
- [x] Web typecheck and production build: `npm run build` from `apps/web` (passed during release preparation; bundle-size warning remains).
- [ ] Resolve or explicitly accept the production JavaScript bundle warning (current main bundle is over 500 kB minified).

### Database and deployment

- [ ] Apply all Alembic migrations to a fresh PostgreSQL database and to a copy of the supported pre-release schema; verify the resulting Alembic head.
- [ ] Exercise downgrade/restore procedures against a disposable database and document any intentionally irreversible data changes.
- [ ] Configure production secrets and providers outside source control: database, strong JWT key, Azure model/OCR/speech/storage credentials as used, allowed CORS origins, and production frontend/API URLs.
- [ ] Use PostgreSQL-backed LangGraph checkpointing in production; verify behavior across API restarts and multiple API instances.
- [ ] Verify memory outbox processing and retention cleanup settings, retry behavior, and ownership after deployment. Confirm worker polling is safe for the chosen API replica count.
- [ ] Confirm HTTPS, cookie/token settings, upload limits, rate limits, database backups, restore access, and log redaction for the deployment environment.
- [ ] Verify `/health`, startup logs, and authenticated API smoke checks after migration.

### Product acceptance

- [ ] Desktop and mobile browser pass for registration/login/logout, profile editing, account/category management, and transaction create/edit/delete.
- [ ] Chat accepts an ordinary transaction, asks for missing details, supports explicit confirmation/correction, and does not duplicate a write after retries or follow-up turns.
- [ ] Receipt upload shows processing feedback, presents extracted details for review, and adds a split only when the user requests it.
- [ ] Itemized receipt split totals reconcile exactly to the transaction in paise; preference-based suggestions remain reviewable and do not silently write a split.
- [ ] Split edit, repayment, undo policy (repaid is final), transaction navigation, and outstanding summaries work for owner and participant views.
- [ ] Analytics answer recent, earlier, and bounded historical queries correctly; verify empty results, timezone boundaries, and results beyond display limits.
- [ ] Import validates malformed rows and reports row-level errors; export excludes internal IDs and notes and downloads only the authenticated user's data.
- [ ] Memory suggestions appear in the notification area, can be confirmed or dismissed, and confirmed memories can be reviewed and forgotten from Profile. Verify cross-user isolation.
- [ ] Verify chat history, drafts, notifications, and transaction/split data remain isolated when two users sign in sequentially in the same browser.

### Release artifacts

- [x] Replace the template frontend README with AffordAbled setup and validation instructions; add repository setup and architecture overview.
- [ ] Confirm package/API version metadata, release notes, and migration instructions match the release tag.
- [ ] Record exact commit, test results, migration head, required environment variables, known limitations, and rollback procedure.
- [ ] Create and push the `v1.0.0` tag only after all required gates pass and the deployed smoke test succeeds.

## Known items at checklist creation

- The full API suite passed (111 tests); Ruff and ESLint passed. ESLint now ignores generated `.pytest_cache` directories, which had caused a Windows `EPERM` during the first run.
- The frontend production build and TypeScript check passed. Vite reports a minified JavaScript bundle above its 500 kB warning threshold.
- Static Alembic inspection reports `o1_add_shared_memory` as the single head. Applying migrations to fresh and supported databases still needs verification.
- Fresh-database migration checks and the full browser acceptance journey have not yet been confirmed for this combined branch.
- The repository currently has a Vite template README and frontend package version `0.0.0`; do not tag the release until these release artifacts are updated intentionally.
