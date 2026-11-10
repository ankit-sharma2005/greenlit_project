import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NewTestPage } from "./NewTestPage";

const mocks = vi.hoisted(() => ({
  fetchPreferences: vi.fn(),
  updatePreferences: vi.fn(),
  listDatasets: vi.fn(),
  listProviders: vi.fn(),
}));

vi.mock("../lib/preferences", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/preferences")>();
  return {
    ...actual,
    fetchPreferences: mocks.fetchPreferences,
    updatePreferences: mocks.updatePreferences,
  };
});

vi.mock("../lib/datasets", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/datasets")>();
  return { ...actual, listDatasets: mocks.listDatasets };
});

vi.mock("../lib/providers", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/providers")>();
  return { ...actual, listProviders: mocks.listProviders };
});

function renderPage() {
  return render(
    <MemoryRouter>
      <NewTestPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listDatasets.mockResolvedValue({ items: [], total: 0 });
  mocks.listProviders.mockResolvedValue({ items: [], total: 0 });
  mocks.updatePreferences.mockResolvedValue({ theme: "dark" });
});

describe("New Test prefill", () => {
  it("opens on the stored entry point with the stored test types ticked", async () => {
    mocks.fetchPreferences.mockResolvedValue({
      theme: "dark",
      entry_point: "prompt_app",
      test_types: ["quality", "operations"],
    });

    renderPage();

    await waitFor(() => expect(screen.getByTestId("connector-select")).toHaveValue("prompt_app"));
    expect(screen.getByRole("checkbox", { name: "Quality" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Safety" })).not.toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /Operations/ }),
    ).toBeChecked();
  });

  it("keeps the default form when nothing is stored", async () => {
    mocks.fetchPreferences.mockResolvedValue({ theme: "dark" });

    renderPage();

    await waitFor(() => expect(mocks.fetchPreferences).toHaveBeenCalled());
    expect(screen.getByTestId("connector-select")).toHaveValue("http_endpoint");
    expect(screen.getByRole("checkbox", { name: "Safety" })).toBeChecked();
  });

  it("never replaces a choice the user already made", async () => {
    // Hold the answer open so the user can act first, which is the real race.
    let release: (value: unknown) => void = () => {};
    mocks.fetchPreferences.mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );

    renderPage();
    await userEvent.selectOptions(screen.getByTestId("connector-select"), "upload_outputs");
    release({ theme: "dark", entry_point: "prompt_app", test_types: ["safety"] });

    await waitFor(() => expect(mocks.fetchPreferences).toHaveBeenCalled());
    // The user's pick stands; the stored default does not overwrite it.
    expect(screen.getByTestId("connector-select")).toHaveValue("upload_outputs");
  });
});
