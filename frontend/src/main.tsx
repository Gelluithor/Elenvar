import { createRoot } from "react-dom/client";
import { useLang } from "./lib/i18n";
import { App } from "./App";
import "@fontsource-variable/inter";
import "./styles.css";
import { applyTheme } from "./lib/theme";

let initialTheme: "dark" | "light" = "dark";
try {
  initialTheme = window.localStorage.getItem("elenvar.theme") === "light" ? "light" : "dark";
} catch {
  /* localStorage nemusí být dostupné */
}
applyTheme(initialTheme);

/** Po změně jazyka se aplikace vykreslí znovu (texty se překládají při vykreslení). */
function Root() {
  const lang = useLang();
  return <App key={lang} />;
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<Root />);
