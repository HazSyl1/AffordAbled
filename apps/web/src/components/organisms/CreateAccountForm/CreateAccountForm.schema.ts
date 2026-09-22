import { z } from 'zod';

export const createAccountSchema = z.object({
  name: z.string().min(1, 'Name is required').max(120),
  type: z.enum(['cash', 'bank', 'card', 'wallet']),
  // Entered in rupees for usability; converted to paise before the API call.
  balanceRupees: z
    .string()
    .min(1, 'Starting balance is required')
    .refine((value) => !Number.isNaN(Number(value)) && Number(value) >= 0, 'Enter a valid non-negative amount'),
});

export type CreateAccountFormValues = z.infer<typeof createAccountSchema>;
