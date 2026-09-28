import { z } from 'zod';

export const registerSchema = z.object({
  name: z.string().min(2, 'Name is required').max(120, 'Name is too long'),
  date_of_birth: z
    .string()
    .min(1, 'Date of birth is required')
    .refine((value) => Number.isFinite(Date.parse(value)), 'Enter a valid date')
    .refine((value) => new Date(value).getTime() < Date.now(), 'Date of birth must be in the past'),
  email: z.string().min(1, 'Email is required').email('Enter a valid email'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
});

export type RegisterFormValues = z.infer<typeof registerSchema>;
