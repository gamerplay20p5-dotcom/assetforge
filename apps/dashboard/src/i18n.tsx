import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { english } from "./english";

type Language = "pt-BR" | "en";
export type Translate = (message: string, ...values: (string | number)[]) => string;

export const portuguese: Translate = (message, ...values) => interpolate(message, values);
const translateEnglish: Translate = (message, ...values) =>
  interpolate(Object.hasOwn(english, message) ? english[message] : message, values);

function interpolate(message: string, values: (string | number)[]) {
  return values.length ? message.replace(/\{(\d+)\}/g, (match, index) => String(values[Number(index)] ?? match)) : message;
}

const storageKey = "assetforge.language";
const LocaleContext = createContext<{ language: Language; setLanguage: (language: Language) => void; t: Translate }>({
  language: "pt-BR", setLanguage: () => {}, t: portuguese,
});

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(() => {
    try {
      return localStorage.getItem(storageKey) === "en" ? "en" : "pt-BR";
    } catch {
      return "pt-BR";
    }
  });
  useEffect(() => {
    document.documentElement.lang = language;
    try {
      localStorage.setItem(storageKey, language);
    } catch {
      // Keep the active language when storage is unavailable.
    }
  }, [language]);
  const value = useMemo(() => ({ language, setLanguage, t: language === "en" ? translateEnglish : portuguese }), [language]);
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale() {
  return useContext(LocaleContext);
}

export function LanguageSelect() {
  const { language, setLanguage, t } = useLocale();
  return <select className="language-select" aria-label={t("Idioma")} value={language}
    onChange={(event) => setLanguage(event.target.value === "en" ? "en" : "pt-BR")}>
    <option value="pt-BR" lang="pt-BR">Português</option>
    <option value="en" lang="en">English</option>
  </select>;
}
