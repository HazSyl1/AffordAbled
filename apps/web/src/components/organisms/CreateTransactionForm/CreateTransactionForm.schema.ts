import { z } from 'zod';

export const createTransactionSchema = z
  .object({
    accountId: z.string().min(1, 'Account is required'),
    type: z.enum(['expense', 'income', 'transfer', 'refund']),
    amountRupees: z
      .string()
      .min(1, 'Amount is required')
      .refine((value) => !Number.isNaN(Number(value)) && Number(value) > 0, 'Enter a valid amount greater than zero'),
    occurredAt: z.string().min(1, 'Date and time are required'),
    categoryId: z.string().optional(),
    toAccountId: z.string().optional(),
    merchant: z.string().max(255, 'Merchant name must be 255 characters or fewer').optional(),
    note: z.string().optional(),
  })
  .superRefine((values, context) => {
    const hasCategoryId = Boolean(values.categoryId && values.categoryId.trim().length > 0);
    const hasToAccountId = Boolean(values.toAccountId && values.toAccountId.trim().length > 0);

    if (values.type === 'transfer') {
      if (!hasToAccountId) {
        context.addIssue({
          code: 'custom',
          message: 'Destination account is required for transfer',
          path: ['toAccountId'],
        });
      }

      if (values.toAccountId === values.accountId) {
        context.addIssue({
          code: 'custom',
          message: 'Source and destination accounts must be different',
          path: ['toAccountId'],
        });
      }

      if (hasCategoryId) {
        context.addIssue({
          code: 'custom',
          message: 'Transfer cannot have a category',
          path: ['categoryId'],
        });
      }
      return;
    }

    if (!hasCategoryId) {
      context.addIssue({
        code: 'custom',
        message: 'Category is required',
        path: ['categoryId'],
      });
    }

    if (hasToAccountId) {
      context.addIssue({
        code: 'custom',
        message: 'Only transfer can define destination account',
        path: ['toAccountId'],
      });
    }
  });

export type CreateTransactionFormValues = z.infer<typeof createTransactionSchema>;
