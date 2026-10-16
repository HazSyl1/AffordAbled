# Transaction export and import

## Use in the app

Open **Transactions**. Use **Export** to download CSV, XLSX, or PDF. Leave the date fields blank for all transactions, or choose an inclusive local date range. CSV and XLSX contain occurrence time, type, amount in rupees, account and category names, destination account name for transfers, and merchant. They contain no record IDs, hashes, or free-text notes. PDF is for reading; CSV/XLSX can be imported.

You can also ask chat to export transactions (for example, "Export my transactions as CSV"). Its report button requests a fresh signed download link when clicked, so the chat message does not store a short-lived bearer URL.

Use **Import** to select a CSV/XLSX file, preview row errors, then confirm. Download the CSV template from the import sheet if preparing a file manually. A file must contain a header and at least one transaction. Required columns are `occurred_at`, `type`, an amount column (`amount_paise` or `amount`/`amount_rupees`), and `account` or `account_id`. Expense, income, and refund rows need `category` or `category_id`; transfers need `to_account` or `to_account_id` and no category. Supported types are `expense`, `income`, `refund`, and `transfer`. Dates use ISO date or datetime; dates without a timezone use the browser's timezone.

Accounts and categories must already exist for the signed-in user. Imported rows resolve names against that user's own records. A manually prepared file may supply IDs, but generated exports never include them. Rows are validated again on confirmation. The import is one database transaction: if any row fails, no transactions or balance changes are saved. Re-uploading exactly the same file after it was imported returns a duplicate error. Importing an unchanged report back into the same user account is also blocked using a server-side file fingerprint. There is no row-by-row duplicate matching: editing a file can bypass the exact-file check and add transactions that already exist. Review the preview and source file before importing a modified report; the screen shows only the first 20 rows.

## Limits and storage

- Import: CSV/XLSX only, 10 MB compressed file size, 50 MB total expanded XLSX size, 10,000 data rows.
- Export: up to 50,000 transactions and 20 MB rendered file. Use a shorter date range for larger reports.
- Generated files are stored in the `exports` table for 24 hours. Access expires after that time. The existing retention scheduler removes expired export rows and file bytes when `RETENTION_CLEANUP_ENABLED` is set; enable it in production and set the interval as needed. The authenticated download URL endpoint issues a fresh five-minute signed file URL; the file endpoint checks the signature and ownership encoded in it. Older generated reports with IDs/notes are rejected by the report version check.
- The file bytes currently use PostgreSQL storage. No cloud storage credentials or provisioning are required. A blob adapter remains a future scaling option if report volume grows.

## Deploy and verify

Install the updated API requirements, then run `alembic upgrade head` from `apps/api`. The migrations add file content columns to `exports`, the `transaction_imports` idempotency table, a safe report version marker, and a server-side file fingerprint. The new head is `l1_track_export_file_hash`. The report-version migration expires older generated reports so their IDs and notes cannot be downloaded. Downgrading these migrations deletes saved export bytes and import deduplication records, so back up the database first.

After migration:

1. Export a small CSV, XLSX, and PDF date range and open each file.
2. Import a CSV with an existing account and category; verify the preview, resulting transaction, and account balance.
3. Upload the same file again; expect a duplicate warning.
4. Preview a file with an unknown account or category; expect row errors and no writes.
5. Verify that another signed-in user cannot refresh the first user's export URL.

API routes: `POST /api/v1/exports/transactions`, `GET /api/v1/exports/{id}/download-url`, `GET /api/v1/exports/{id}/file?token=...`, `POST /api/v1/imports/transactions/preview`, and `POST /api/v1/imports/transactions/confirm`.
