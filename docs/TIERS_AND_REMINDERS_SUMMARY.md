# User tiers, usage limits, and branded payment reminders

## User tiers and daily limits (UTC day)

| Tier | Chat messages | AI-created transactions | Voice/image uploads | Reminder limits |
|---|---|---|---|---|
| free (default) | 50 | 20 | 30 | enforced |
| subscribed | 250 | 100 | 150 | enforced |
| test | unlimited | unlimited | unlimited | bypassed |

- `users.account_tier` plus a `user_usage_events` ledger (migration `aa4_user_tiers_usage`).
  The migration sets user `a8843e3d-dcd4-4e43-9af0-9c845dae190a` to `test` if it exists.
- Limits are enforced on `POST /chat/turns`, legacy `POST /chat`, `/chat/voice`, `/chat/image`, and at the
  transaction tool boundary for chat-created transactions. Over the limit returns HTTP 429 with the limit,
  used count, reset time, and `Retry-After`.
- Retries never double-count; a chat turn that fails permanently is refunded; batches are all-or-nothing and a
  retried batch only needs capacity for new rows.
- `GET /auth/me/usage` and the Profile page show tier and usage. `scripts/set_user_tier.py` changes tiers
  (operator only; the public profile API never accepts a tier).
- Settings: `FREE_*`, `SUBSCRIBED_*` variables in `apps/api/.env.example`.

## Split-wide payment reminders

- One confirmation queues a separate email per unpaid participant; cooldown, per-split and daily limits are
  counted per split campaign. Test users bypass these numeric limits but keep ownership, UPI, paid-state,
  provider and in-progress protections.
- Branded HTML email (purple `#a855f7` header, amount, Pay with UPI button, inline QR, safety note) with a
  plain-text fallback. Logo and QR are CID inline PNGs; the QR is generated server-side from the exact UPI link.
  All user-supplied values are HTML-escaped. The worker re-validates recipient, amount, subject and UPI link
  before rendering and cancels stale requests.

## Landing page

- New "What's new" carousel (auto-rotating, pause/prev/next controls, dots, reduced-motion aware) and two new
  feature cards (UPI payment reminders, plans and daily usage).

## Test status

- Backend: 338 passed, 6 skipped; Ruff clean.
- Frontend: 7 tests passed; production build passes.
- Repaired stale tests: import tests reuse seeded default categories; the itemized-split test now expects the
  intentional 409 when deleting a contact still attached to a split.
