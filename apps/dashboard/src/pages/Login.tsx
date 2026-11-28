import { LanguageSelect, useLocale } from "../i18n";
import { Triangle } from "lucide-react";
import { useState } from "react";
import { api, setToken } from "../api";

export function Login({ onDone }: { onDone: () => void }) {
  const { t } = useLocale();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="login">
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            const r = await api<{ access_token: string }>("/auth/login", { method: "POST", json: { username, password } });
            setToken(r.access_token);
            onDone();
          } catch (err) {
            setError((err as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="brand" style={{ padding: 0 }}>
          <div className="brand-mark">
            <Triangle size={15} fill="currentColor" />
          </div>
          <span>AssetForge</span>
          <div className="spacer" />
          <LanguageSelect />
        </div>
        <label className="field">
          {t("Usuário")}
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
        </label>
        <label className="field">
          {t("Senha")}
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
        {error && <div className="error-note">{error}</div>}
        <button className="primary" disabled={busy || !password} type="submit">
          {t("Entrar")}
        </button>
      </form>
    </div>
  );
}
