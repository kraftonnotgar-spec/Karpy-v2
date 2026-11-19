"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { CircleAlert } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { CopyButton } from "@/core/components/copy-button";
import { adminHref } from "@/core/config/admin-path";
import { safeRedirect } from "@/core/features/auth/sign-in-form";
import type { MessageKey } from "@/core/i18n";
import { useT } from "@/core/i18n/provider";
import { toSafeError } from "@/core/lib/api";
import { toast } from "@/core/lib/notify";
import { adminCompleteSetup, adminLogin } from "./console-api";

type Step =
  | { kind: "password" }
  | { kind: "code"; login: string; password: string }
  | { kind: "setup"; token: string; secret?: string; qr?: string }
  | { kind: "recovery"; codes: string[] };

/**
 * Admin sign-in (POST /api/admin/auth/login). Every admin session needs an authenticator:
 * first sign-in enrols one (QR + setup key, then /login/setup), later sign-ins ask for its code.
 */
export function AdminSignIn() {
  const t = useT();
  const router = useRouter();
  const params = useSearchParams();
  const [step, setStep] = useState<Step>({ kind: "password" });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<MessageKey>();
  const destination = safeRedirect(params.get("redirect"), adminHref("/admin"));

  function finish() {
    toast.success(t("auth.signIn.success"));
    router.replace(destination);
    router.refresh();
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();
    setPending(true);
    setError(undefined);
    try {
      if (step.kind === "setup") {
        const result = await adminCompleteSetup({ token: step.token, code: value("code") });
        if (result.recovery_codes?.length) setStep({ kind: "recovery", codes: result.recovery_codes });
        else finish();
        return;
      }
      const login = step.kind === "code" ? step.login : value("login");
      const password = step.kind === "code" ? step.password : String(form.get("password") ?? "");
      const result = await adminLogin({ login, password, ...(step.kind === "code" ? { code: value("code") } : {}) });
      if (result.mfa_setup_required && result.setup_token) setStep({ kind: "setup", token: result.setup_token, secret: result.secret, qr: result.qr });
      else if (result.mfa_required) setStep({ kind: "code", login, password });
      else finish();
    } catch (reason) {
      const detail = toSafeError(reason);
      setError(
        detail.status === 429
          ? "auth.errors.tooMany"
          : detail.status === 422
            ? step.kind === "password"
              ? "auth.errors.invalidCredentials"
              : "admin.signIn.errors.invalidCode"
            : detail.status === 401 || detail.status === 410
              ? "admin.signIn.errors.expired"
              : "auth.errors.unavailable",
      );
    } finally {
      setPending(false);
    }
  }

  if (step.kind === "recovery") {
    return (
      <div className="flex flex-col gap-4">
        <div>
          <h2 className="text-sm font-semibold">{t("admin.signIn.recoveryTitle")}</h2>
          <p className="mt-1 text-[13px] text-muted-foreground">{t("admin.signIn.recoveryDescription")}</p>
        </div>
        <div className="flex items-start gap-2 rounded-lg border p-3">
          <ul className="grid flex-1 grid-cols-2 gap-1 font-mono text-[13px]">
            {step.codes.map((code) => (
              <li key={code}>{code}</li>
            ))}
          </ul>
          <CopyButton value={step.codes.join("\n")} variant="outline" />
        </div>
        <Button className="h-10" onClick={finish}>
          {t("admin.signIn.continue")}
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-5">
      {error && (
        <Alert variant="destructive" role="alert">
          <CircleAlert />
          <AlertDescription>{t(error)}</AlertDescription>
        </Alert>
      )}
      <FieldGroup>
        {step.kind === "password" && (
          <>
            <Field>
              <FieldLabel htmlFor="login">{t("admin.signIn.login")}</FieldLabel>
              <Input id="login" name="login" autoComplete="username" required autoFocus maxLength={120} />
            </Field>
            <Field>
              <FieldLabel htmlFor="password">{t("admin.signIn.password")}</FieldLabel>
              <Input id="password" name="password" type="password" autoComplete="current-password" required maxLength={120} />
            </Field>
          </>
        )}
        {step.kind === "setup" && (
          <div className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-semibold">{t("admin.signIn.setupTitle")}</h2>
              <p className="mt-1 text-[13px] text-muted-foreground">{t("admin.signIn.setupDescription")}</p>
            </div>
            {step.qr?.startsWith("data:image/") && (
              // eslint-disable-next-line @next/next/no-img-element -- one-off data URI from the backend
              <img src={step.qr} alt={t("admin.signIn.qrAlt")} className="size-44 self-center rounded-md border bg-background p-2" />
            )}
            {step.secret && (
              <Field>
                <FieldLabel htmlFor="setup-key">{t("admin.signIn.setupKey")}</FieldLabel>
                <div className="flex gap-2">
                  <Input id="setup-key" readOnly value={step.secret} className="font-mono" />
                  <CopyButton value={step.secret} variant="outline" />
                </div>
              </Field>
            )}
          </div>
        )}
        {step.kind !== "password" && (
          <Field>
            <FieldLabel htmlFor="code">{t("admin.signIn.code")}</FieldLabel>
            <Input id="code" name="code" inputMode="numeric" autoComplete="one-time-code" required autoFocus maxLength={64} />
            <FieldDescription>{t("admin.signIn.codeHint")}</FieldDescription>
          </Field>
        )}
      </FieldGroup>
      <Button type="submit" disabled={pending} className="h-10">
        {pending && <Spinner data-icon="inline-start" />}
        {pending ? t("admin.signIn.submitting") : t("admin.signIn.submit")}
      </Button>
    </form>
  );
}
