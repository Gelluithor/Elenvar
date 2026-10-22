import { useSyncExternalStore } from "react";
import { EN } from "./i18n-en";

/**
 * Jednoduchá lokalizace: zdrojovým jazykem je čeština (texty v kódu), angličtina
 * je překlad v souboru i18n-en.ts. Klíčem je přímo český text, proměnné části se
 * zapisují jako {name}.
 */

export type Lang = "cs" | "en";

const STORAGE_KEY = "elenvar.lang";
const listeners = new Set<() => void>();

function detect(): Lang {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "cs" || saved === "en") return saved;
  } catch {
    /* localStorage nemusí být dostupné */
  }
  const preferred = (navigator.languages?.[0] ?? navigator.language ?? "").toLowerCase();
  return preferred.startsWith("cs") || preferred.startsWith("sk") ? "cs" : "en";
}

let current: Lang = detect();
document.documentElement.lang = current;

export function getLang(): Lang {
  return current;
}

export function setLang(lang: Lang): void {
  if (lang === current) return;
  current = lang;
  document.documentElement.lang = lang;
  try {
    window.localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* ignorovat */
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useLang(): Lang {
  return useSyncExternalStore(subscribe, getLang, getLang);
}

type Params = Record<string, string | number>;

/** Přeloží český text do aktuálního jazyka a doplní proměnné {name}. */
export function t(text: string, params?: Params): string {
  let result = current === "en" ? (EN[text] ?? text) : text;
  if (params) {
    result = result.replace(/\{(\w+)\}/g, (match, key: string) => (key in params ? String(params[key]) : match));
  }
  return result;
}

/** Označí text k překladu bez okamžitého překladu (konstanty na úrovni modulu). */
export function N_(text: string): string {
  return text;
}

export function locale(): string {
  return current === "en" ? "en-GB" : "cs-CZ";
}
