import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@fontsource/dm-serif-display";
import "@fontsource/dm-serif-display/400-italic.css";
import "@fontsource-variable/jost";
import "@fontsource-variable/caveat";
import "@fontsource-variable/jetbrains-mono";

import { App } from "./App";
import "./styles.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("index.html is missing the #root element");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
