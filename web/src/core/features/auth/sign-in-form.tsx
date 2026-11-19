"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { CircleAlert } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import type { MessageKey } from "@/core/i18n";
import { useT } from "@/core/i18n/provider";
import { postJSON, toSafeError, userAuthAPI, type SafeError } from "@/core/lib/api";
import { toast } from "@/core/lib/notify";

const AFTER_SIGN_IN = "/dashboard";

/** Only same-site paths are followed after sign-in (no open redirects). */
export function safeRedirect(value: string | null, fallback: string) {
  return value && value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/\\") ? value : fallback;
}

/** Backend errors become catalog messages chosen by status; upstream text is never shown. */
function errorKey(error: SafeError): MessageKey {
  const body = error.body as { detail?: unknown } | undefined;
  const detail = body?.detail && typeof body.detail === "object" && !Array.isArray(body.detail) ? (body.detail as { requiresVerification?: boolean }) : undefined;
  // FastAPI answers schema problems with a list of issues; wrong credentials with an object.
  if (error.status === 422) return Array.isArray(body?.detail) ? "auth.errors.invalidInput" : "auth.errors.invalidCredentials";
  if (error.status === 403) return detail?.requiresVerification ? "auth.errors.emailNotVerified" : "auth.errors.notAllowed";
  if (error.status === 429) return "auth.errors.tooMany";
  return "auth.errors.unavailable";
}

/** User sign-in: POST /api/plugins/auth/user/login { email, password, remember }. */
export function SignInForm() {
  const t = useT();
  const router = useRouter();
  const params = useSearchParams();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<MessageKey>();

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(undefined);
    try {
      const { data } = await postJSON<{ requiresOTP?: boolean }>(`${userAuthAPI}/login`, {
        email: String(form.get("email") ?? "").trim(),
        password: String(form.get("password") ?? ""),
        remember: form.get("remember") === "on",
      });
      if (data?.requiresOTP) {
        setError("auth.errors.codeRequired");
        return;
      }
      toast.success(t("auth.signIn.success"));
      router.replace(safeRedirect(params.get("redirect"), AFTER_SIGN_IN));
      router.refresh();
    } catch (reason) {
      setError(errorKey(toSafeError(reason)));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate={false} className="flex flex-col gap-5">
      {error && (
        <Alert variant={error === "auth.errors.codeRequired" ? "default" : "destructive"} role="alert">
          <CircleAlert />
          <AlertDescription>{t(error)}</AlertDescription>
        </Alert>
      )}
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="email">{t("auth.signIn.email")}</FieldLabel>
          <Input id="email" name="email" type="email" autoComplete="email" required autoFocus />
        </Field>
        <Field>
          <FieldLabel htmlFor="password">{t("auth.signIn.password")}</FieldLabel>
          <Input id="password" name="password" type="password" autoComplete="current-password" required maxLength={120} />
        </Field>
        <Field orientation="horizontal">
          <Checkbox id="remember" name="remember" />
          <FieldLabel htmlFor="remember" className="font-normal">
            {t("auth.signIn.remember")}
          </FieldLabel>
        </Field>
      </FieldGroup>
      <Button type="submit" disabled={pending} className="h-10">
        {pending && <Spinner data-icon="inline-start" />}
        {pending ? t("auth.signIn.submitting") : t("auth.signIn.submit")}
      </Button>
    </form>
  );
}
