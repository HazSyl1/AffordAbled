import type { FormFieldProps } from './FormField.types';

export function FormField({ label, htmlFor, error, children }: FormFieldProps) {
  return (
    <div className="mb-4 flex flex-col gap-1.5">
      <label className="text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {error ? (
        <p className="m-0 text-xs text-[var(--negative)]" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
