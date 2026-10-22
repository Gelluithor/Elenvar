export type Theme = "dark" | "light";

/** Nastaví motiv stránky a odpovídající ikonu v záložce prohlížeče. */
export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  const icon = document.getElementById("favicon") as HTMLLinkElement | null;
  if (icon) icon.href = theme === "light" ? "/logo-light.svg" : "/logo-dark.svg";
}
