# Smart receipt splits

## Current flow

The existing image endpoint runs Azure Document Intelligence OCR. Chat receives the OCR text as untrusted data and can log a transaction. If the user types split instructions before uploading, the chat page includes them with that image prompt. For example: "Isha and I shared the veg pizza; Piyush and I shared the chicken; split tax evenly." The split specialist runs only after the expense transaction exists.

The split specialist can pass reviewed item names, paise amounts, food types, and `shared_by` names to `create_split`. The backend verifies that every item has an allocation and all rows sum to the expense total. It divides each row in paise, with deterministic remainder handling, and asks the user to confirm the item list and resulting shares before saving. A correction or refusal leaves the split unsaved; the agent receives the correction, and the next turn can resume the pending split without recording the expense again. The completion popup waits for the full queued request, including the split. Saved item breakdowns can be opened on the Splits page. Editing participant amounts clears an outdated breakdown; a title-only edit keeps it.

## Contact memory

The Splits page lets the owner save, change, or forget a confirmed vegetarian, vegan, or meat-eating preference for a named contact. Chat can read these preferences and save one only when the user explicitly asks. A preference does not prove who consumed an item. A confirmed vegetarian or vegan contact assigned a meat item triggers a review warning.

Three separate reviewed splits with vegetarian or vegan items assigned to the same person and no meat allocation produce a **suggestion**, not stored memory. The user must confirm it. Preferences and suggestions are scoped by the authenticated user.

## Deployment and checks

Run `alembic upgrade head` from `apps/api` after installing dependencies. The new head is `n1_add_split_item_breakdown`. Migration `m1` creates user-owned contact preferences; `n1` adds nullable item breakdowns to splits. Downgrading `n1` removes saved item breakdowns; downgrading `m1` deletes saved contact preferences.

Test with a receipt that has a clear total and line prices. Type the people and item assignments in chat before selecting the image. Verify the transaction is recorded first, the itemized review question appears, and a split is saved only after confirming. Open the split to inspect each item's allocation. Set Isha to vegetarian on the Splits page and try assigning a meat item to her; the review should warn. Check a second account cannot see Isha's preference, split, or pattern suggestion.

OCR is still text-only; the model proposes item structure from that text. Unclear prices, taxes, or consumption require clarification. No preference is inferred permanently from one receipt. The first chat review is limited to 20 items, while the direct itemized API accepts up to 100 rows.
