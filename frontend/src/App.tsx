import { BrowserRouter, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { NewTestPage } from "./pages/NewTestPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ResultsPage } from "./pages/ResultsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TestChatPage } from "./pages/TestChatPage";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<NewTestPage />} />
          <Route path="results" element={<ResultsPage />} />
          <Route path="test-chat" element={<TestChatPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
