import { useState } from "react";

import { ApiError } from "../lib/api";
import {
  PRICE_IN_KEY,
  PRICE_OUT_KEY,
  parsePrice,
  storedPrices,
  updateProvider,
  type Provider,
} from "../lib/providers";
import { Button } from "./Button";

/**
 * The optional token prices used for the rough cost estimate on a verdict.
 *
 * They are stored in the provider's metadata bag, merged rather than replaced,
 * so other metadata keys survive. An empty field clears the key instead of
 * storing a 0, because a 0 price would make every run look free.
 */

function summary(priceIn: number | null, priceOut: number | null): string {
  if (priceIn === null && priceOut === null) {
    return "not set";
  }
  const show = (value: number | null) => (value === null ? "not set" : String(value));
  return `in ${show(priceIn)} / out ${show(priceOut)} per 1K`;
}

export interface ProviderPricesProps {
  provider: Provider;
  onSaved: () => void | Promise<void>;
}

export function ProviderPrices({ provider, onSaved }: ProviderPricesProps) {
  const current = storedPrices(provider.provider_config);
  const [editing, setEditing] = useState(false);
  const [priceIn, setPriceIn] = useState("");
  const [priceOut, setPriceOut] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const startEditing = () => {
    setPriceIn(current.priceIn === null ? "" : String(current.priceIn));
    setPriceOut(current.priceOut === null ? "" : String(current.priceOut));
    setError(null);
    setEditing(true);
  };

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    const parsedIn = parsePrice(priceIn);
    const parsedOut = parsePrice(priceOut);
    const problem = parsedIn.error ?? parsedOut.error;
    if (problem !== null) {
      setError(problem);
      return;
    }

    setBusy(true);
    setError(null);
    try {
      await updateProvider(provider.id, {
        // null tells the API to remove that key, so clearing works.
        metadata: {
          [PRICE_IN_KEY]: parsedIn.value,
          [PRICE_OUT_KEY]: parsedOut.value,
        },
      });
      setEditing(false);
      await onSaved();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "Could not save the prices. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  if (!editing) {
    return (
      <div className="provider-prices">
        <span className="card__hint" data-testid="provider-price-summary">
          Tokens: {summary(current.priceIn, current.priceOut)}
        </span>
        <Button variant="ghost" onClick={startEditing} data-testid="provider-price-edit">
          Edit prices
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSave} className="provider-prices" data-testid="provider-price-form">
      <label className="form__label" htmlFor={`price-in-${provider.id}`}>
        Price per 1K input tokens:
      </label>
      <input
        id={`price-in-${provider.id}`}
        data-testid="provider-price-edit-in"
        type="text"
        inputMode="decimal"
        value={priceIn}
        onChange={(e) => setPriceIn(e.target.value)}
        disabled={busy}
      />
      <label className="form__label" htmlFor={`price-out-${provider.id}`}>
        Price per 1K output tokens:
      </label>
      <input
        id={`price-out-${provider.id}`}
        data-testid="provider-price-edit-out"
        type="text"
        inputMode="decimal"
        value={priceOut}
        onChange={(e) => setPriceOut(e.target.value)}
        disabled={busy}
      />
      <p className="card__hint">
        Used only for the rough cost estimate on the verdict. Leave empty if unknown.
      </p>
      {error !== null && (
        <p className="form-error" role="alert" data-testid="provider-price-error">
          {error}
        </p>
      )}
      <div className="datasets__actions">
        <Button type="submit" variant="primary" loading={busy} data-testid="provider-price-save">
          Save prices
        </Button>
        <Button
          variant="ghost"
          onClick={() => setEditing(false)}
          disabled={busy}
          data-testid="provider-price-cancel"
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}
