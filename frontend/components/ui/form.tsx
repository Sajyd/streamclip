"use client";

import {
  createContext,
  use,
  useActionState,
  useId,
  type ComponentProps,
  type ReactNode,
} from "react";

import { buttonClasses, type ButtonSize, type ButtonVariant } from "@/components/ui/button";
import { cx } from "@/lib/format";
import { idleState, type FormState } from "@/lib/form-state";

type FormContextValue = { state: FormState; pending: boolean };

const FormContext = createContext<FormContextValue>({ state: idleState, pending: false });

type FormAction =
  | ((state: FormState, formData: FormData) => Promise<FormState>)
  | ((state: FormState) => Promise<FormState>);

type FormProps = Omit<ComponentProps<"form">, "action"> & {
  action: FormAction;
  /** Hide the status message (when the form shows it elsewhere). */
  quiet?: boolean;
};

/**
 * A form bound to a Server Action. Works without JavaScript; with it, shows
 * the pending state, the outcome, and per-field errors.
 */
export function Form({ action, quiet = false, className, children, ...props }: FormProps) {
  const [state, formAction, pending] = useActionState(
    action as (state: FormState, formData: FormData) => Promise<FormState>,
    idleState,
  );
  return (
    <FormContext value={{ state, pending }}>
      <form action={formAction} noValidate className={cx("space-y-4", className)} {...props}>
        {children}
        {quiet ? null : <FormMessage />}
      </form>
    </FormContext>
  );
}

export function FormMessage() {
  const { state } = use(FormContext);
  if (state.status === "idle" || !state.message) {
    return null;
  }
  const isError = state.status === "error";
  return (
    <p
      role={isError ? "alert" : "status"}
      className={cx(
        "rounded-lg border px-3 py-2 text-sm",
        isError
          ? "border-danger-500/40 bg-danger-500/10 text-danger-400"
          : "border-ok-500/40 bg-ok-500/10 text-ok-400",
      )}
    >
      {state.message}
    </p>
  );
}

type FieldProps = Omit<ComponentProps<"input">, "name"> & {
  name: string;
  label: string;
  hint?: ReactNode;
};

export function Field({ name, label, hint, className, defaultValue, type = "text", ...props }: FieldProps) {
  const { state } = use(FormContext);
  const id = useId();
  const error = state.fields?.[name];
  // After a failed submission the browser form is reset: non-secret values
  // returned by the action are put back.
  const restored = type === "password" ? undefined : state.values?.[name];
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink-200">
        {label}
      </label>
      <input
        id={id}
        name={name}
        type={type}
        defaultValue={restored ?? defaultValue}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className={cx(
          "block w-full rounded-lg border bg-ink-900 px-3 py-2.5 text-sm text-ink-100",
          "placeholder:text-ink-500 transition-colors",
          error ? "border-danger-500/70" : "border-ink-600 hover:border-ink-500",
        )}
        {...props}
      />
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-sm text-danger-400">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1.5 text-xs text-ink-400">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

type SelectFieldProps = Omit<ComponentProps<"select">, "name"> & {
  name: string;
  label: string;
  options: readonly string[];
};

export function SelectField({ name, label, options, defaultValue, className, ...props }: SelectFieldProps) {
  const { state } = use(FormContext);
  const id = useId();
  const error = state.fields?.[name];
  const selected = state.values?.[name] ?? defaultValue;
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink-200">
        {label}
      </label>
      <select
        id={id}
        name={name}
        defaultValue={selected}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={cx(
          "block w-full rounded-lg border bg-ink-900 px-3 py-2.5 text-sm text-ink-100",
          error ? "border-danger-500/70" : "border-ink-600 hover:border-ink-500",
        )}
        {...props}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-sm text-danger-400">
          {error}
        </p>
      ) : null}
    </div>
  );
}

type CheckboxProps = { name: string; children: ReactNode; required?: boolean };

export function Checkbox({ name, children, required }: CheckboxProps) {
  const { state } = use(FormContext);
  const id = useId();
  const error = state.fields?.[name];
  return (
    <div>
      <div className="flex items-start gap-3">
        <input
          id={id}
          name={name}
          type="checkbox"
          required={required}
          // Kept ticked when the form comes back with an error on another field.
          defaultChecked={state.values?.[name] === "on"}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          className="mt-0.5 size-4 shrink-0 rounded border-ink-500 bg-ink-900 accent-brand-500"
        />
        <label htmlFor={id} className="text-sm text-ink-300">
          {children}
        </label>
      </div>
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-sm text-danger-400">
          {error}
        </p>
      ) : null}
    </div>
  );
}

type SubmitButtonProps = Omit<ComponentProps<"button">, "type"> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  pendingLabel?: string;
};

export function SubmitButton({
  children,
  variant = "primary",
  size = "md",
  pendingLabel,
  className,
  disabled,
  ...props
}: SubmitButtonProps) {
  const { pending } = use(FormContext);
  return (
    <button
      type="submit"
      disabled={pending || disabled}
      aria-busy={pending || undefined}
      className={buttonClasses({ variant, size, className })}
      {...props}
    >
      {pending ? (pendingLabel ?? "Un instant…") : children}
    </button>
  );
}
