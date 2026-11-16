import type { ApiError } from "@/lib/api";

/** State returned by every form action and read by the form components. */
export type FormState = {
  status: "idle" | "error" | "success";
  message?: string;
  /** Field name -> error message. */
  fields?: Record<string, string>;
  /** Non-secret values to put back in the form after a failed submission. */
  values?: Record<string, string>;
};

export const idleState: FormState = { status: "idle" };

// API error codes that concern one specific form field.
const CODE_TO_FIELD: Record<string, string> = {
  email_already_registered: "email",
  invalid_email: "email",
  weak_password: "password",
  terms_required: "accept_terms",
  invalid_current_password: "current_password",
};

// The API names some fields differently from the forms.
const FIELD_ALIASES: Record<string, string> = { new_password: "password" };

export function failure(
  error: ApiError,
  values?: Record<string, string>,
  aliases: Record<string, string> = FIELD_ALIASES,
): FormState {
  const fields: Record<string, string> = {};
  for (const [name, message] of Object.entries(error.fields)) {
    fields[aliases[name] ?? name] = message;
  }
  const field = CODE_TO_FIELD[error.code];
  if (field) {
    fields[aliases[field] ?? field] = error.message;
  }
  const hasFieldErrors = Object.keys(fields).length > 0;
  return {
    status: "error",
    message:
      hasFieldErrors && error.code === "validation_error"
        ? "Certains champs sont à corriger."
        : hasFieldErrors && field
          ? undefined
          : error.message,
    fields,
    values,
  };
}

export function invalid(fields: Record<string, string>, values?: Record<string, string>): FormState {
  return { status: "error", message: "Certains champs sont à corriger.", fields, values };
}

export function success(message: string): FormState {
  return { status: "success", message };
}

export function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

/** Passwords are taken verbatim: no trimming. */
export function secret(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}
