import { createRoot } from "react-dom/client";
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

const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
