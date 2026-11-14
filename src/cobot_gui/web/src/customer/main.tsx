import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { createMockApi, httpApi, isMockMode } from "./api";
import "./customer.css";

const search = window.location.search;
const api = isMockMode(search) ? createMockApi() : httpApi;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App api={api} search={search} />
  </StrictMode>,
);
