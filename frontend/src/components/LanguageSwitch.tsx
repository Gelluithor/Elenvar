import { setLang, useLang, type Lang } from "../lib/i18n";

const LANGS: { value: Lang; short: string; name: string }[] = [
  { value: "cs", short: "CS", name: "Čeština" },
  { value: "en", short: "EN", name: "English" },
];

/** Tlačítko v postranním panelu: přepne na druhý jazyk. */
export function LanguageToggle() {
  const lang = useLang();
  const next = LANGS.find((l) => l.value !== lang) ?? LANGS[0];
  return (
    <button type="button" className="icon-btn lang-toggle" onClick={() => setLang(next.value)} title={next.name} aria-label={next.name}>
      {next.short}
    </button>
  );
}

/** Volba jazyka pod přihlašovacím formulářem. */
export function LanguageLinks() {
  const lang = useLang();
  return (
    <div className="lang-links" role="group" aria-label="Language / Jazyk">
      {LANGS.map((l) => (
        <button key={l.value} type="button" className={`link-btn${l.value === lang ? " active" : ""}`} onClick={() => setLang(l.value)} aria-pressed={l.value === lang}>
          {l.name}
        </button>
      ))}
    </div>
  );
}
