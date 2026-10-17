import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { Landing } from "./landing/Landing";
import { getState, mutate, setUi } from "./model/store";
import "./styles.css";

// Test hook used by the Playwright suite (tests/e2e_studio.py).
(window as unknown as { __crux: unknown }).__crux = { getState, mutate, setUi };

// "/" is the landing page; "/studio" is the editor.
const inStudio = location.pathname.replace(/\/+$/, "") === "/studio";

createRoot(document.getElementById("root")!).render(
  <StrictMode>{inStudio ? <App /> : <Landing />}</StrictMode>,
);
