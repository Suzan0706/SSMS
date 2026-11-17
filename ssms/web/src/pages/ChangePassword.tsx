import { FormEvent, useState } from "react";

import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Button, Card, ErrorBox, Field, Input } from "../ui";

export default function ChangePassword() {
  const auth = useAuth();
  const [, t] = useLang();
  const [form, setForm] = useState({ current_password: "", new_password: "" });
  const [error, setError] = useState<ApiError | null>(null);
  const forced = auth.session?.user.must_change_password;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/auth/change-password", { body: form });
      await auth.reload();                                   // new session data: must_change_password = false
    } catch (err) {
      setError(err as ApiError);
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <Card title={t("changePassword")}>
        {forced && <p className="mb-3 text-sm text-amber-800">{t("mustChange")}</p>}
        <ErrorBox error={error} />
        <form className="mt-3 space-y-3" onSubmit={submit}>
          <Field label={t("currentPassword")}>
            <Input type="password" name="current_password" autoComplete="current-password" required
              value={form.current_password} onChange={(e) => setForm({ ...form, current_password: e.target.value })} />
          </Field>
          <Field label={t("newPassword")}>
            <Input type="password" name="new_password" autoComplete="new-password" required minLength={10}
              value={form.new_password} onChange={(e) => setForm({ ...form, new_password: e.target.value })} />
          </Field>
          <Button type="submit">{t("save")}</Button>
        </form>
      </Card>
    </div>
  );
}
