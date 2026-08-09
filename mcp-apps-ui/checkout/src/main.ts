/**
 * T038 — the in-chat mock checkout, as an MCP App.
 *
 * Hackathon hard requirement #4. A real MCP App, not an iframe that looks
 * like one: it speaks the MCP Apps protocol through the official `App`
 * class from @modelcontextprotocol/ext-apps, performing the
 * `ui/initialize` handshake and calling `confirm_mock_payment` back
 * through `callServerTool`. Hand-rolling the postMessage handshake was
 * rejected for the booking form and is rejected here for the same reason
 * — a protocol implemented from prose is the "looks right, never ran"
 * failure this project keeps paying for.
 *
 * ====================================================================
 * CONSTITUTION PRINCIPLE III — this file is the first layer of three
 * ====================================================================
 *
 * The principle: *"no persistence of real-looking payment credentials
 * anywhere (DB, logs, traces) even transiently. Any card-like input is
 * discarded server-side immediately after the mock 'authorization'
 * step."* spec.md US4 AS2 sharpens it: no raw payment-like input written
 * to any datastore, log file, or OTel span.
 *
 * The design decision that makes this cheap to guarantee: **the card
 * values never leave this document.**
 *
 *   - They live in `card`, a module-level object, never in a DOM `value`
 *     attribute that survives a re-render and never in storage (the
 *     iframe has an opaque origin, so it has no usable storage anyway).
 *   - `authoriseLocally()` is the mock "authorization step". It runs
 *     *here*, in the sandbox, and checks shape only.
 *   - `forgetCard()` runs immediately after it, implementing the
 *     principle's own sentence literally.
 *   - `confirm_mock_payment` is then called with **`{}`** — no arguments
 *     at all. Not a filtered subset: nothing. `buildToolArguments()`
 *     exists as a named function purely so that this is a reviewable
 *     line rather than an easily-missed empty object literal.
 *
 * The other two layers are `api/main.py`'s App-bridge handler (which
 * ignores whatever this sends and supplies `booking_id` from persisted
 * state) and `payment/store.py`'s allowlist. Each holds if the other two
 * are bypassed; this one holds even against a host that logs every
 * message it relays.
 *
 * Principle I applies as it does everywhere: every vehicle value shown
 * comes from the `open_mock_checkout` tool result, which the backend
 * built from `SessionState.selected_listing()` — the verbatim search
 * record. Nothing is recomputed, and in particular **no total, tax or
 * fee is calculated**, because each would be a number on screen that no
 * tool call ever returned.
 */
import { App } from "@modelcontextprotocol/ext-apps";
import "./styles.css";

type Listing = Record<string, string | number>;
type Booking = Record<string, string>;
type CheckoutPayload = {
  booking?: Booking;
  listing?: Listing;
  mock?: boolean;
  notice?: string;
};
type Confirmation = { confirmation_code: string; id: string; booking_id: string };

const root = document.getElementById("root")!;

/**
 * The card-like values, held here and nowhere else.
 *
 * Not `entered` as in the booking form, and the difference is
 * deliberate: booking keeps typed values across a re-render because a
 * server-side rejection must not lose them (US3 AS2). Here there is no
 * server-side rejection to survive — authorization is local — so the
 * values exist only between keystroke and authorization, and are cleared
 * the moment it completes.
 */
let card: Record<string, string> = {};

let payload: CheckoutPayload = {};
let errors: Record<string, string> = {};
let formError: string | null = null;
let paying = false;
let confirmation: Confirmation | null = null;

const CARD_FIELDS = [
  { name: "card_name", label: "Name on card", placeholder: "Dana Okoro", numeric: false },
  { name: "card_number", label: "Card number", placeholder: "4242 4242 4242 4242", numeric: true },
] as const;

const SHORT_FIELDS = [
  { name: "card_expiry", label: "Expiry", placeholder: "12/29" },
  { name: "card_cvc", label: "Security code", placeholder: "123" },
] as const;

/**
 * Group thousands with plain commas.
 *
 * Deliberately NOT `toLocaleString`: it emits U+202F (narrow no-break
 * space) as the group separator in several locales, and this project has
 * already been bitten by exactly that character once — a test's price
 * extractor read "$25 000" as "25" because the model emitted U+202F
 * (HANDOFF §3). A deterministic separator keeps the rendered value
 * greppable and identical in every environment.
 *
 * It also does not round. A rendered value must be traceable *verbatim*
 * to the tool record, and 24499.5 shown as $24,500 is a number the
 * marketplace never returned.
 */
function money(value: number | string): string {
  const [whole, fraction] = String(value).split(".");
  const negative = whole.startsWith("-");
  const digits = negative ? whole.slice(1) : whole;
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "-" : ""}$${grouped}${fraction ? "." + fraction : ""}`;
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  // textContent, never innerHTML: listing fields are marketplace data and
  // marketplace data is untrusted by construction (Principle IV). The
  // attacker-controlled `description` is stripped server-side before it
  // reaches this document, but that is a second line of defence, not a
  // licence to interpolate the rest as markup.
  if (text !== undefined) node.textContent = text;
  return node;
}

/** The amount line, taken verbatim from the record and labelled for the
 * transaction type. Rent and sale are genuinely different numbers in the
 * dataset, and showing the wrong one is a Principle I failure even though
 * both values are real. */
function amountFor(listing: Listing): [string, string] | null {
  if (listing.transaction_type === "rent") {
    const perDay = listing.rent_price_per_day;
    return perDay === undefined || perDay === null
      ? null
      : ["Amount (per day)", money(perDay as number)];
  }
  const price = listing.price;
  return price === undefined || price === null ? null : ["Amount", money(price as number)];
}

function renderVehicle(listing: Listing, booking: Booking): HTMLElement {
  const box = el("div", "vehicle");
  const name = [listing.year, listing.brand, listing.model]
    .filter((part) => part !== undefined && part !== "")
    .join(" ");
  box.append(el("div", "vehicle-name", name || String(listing.id ?? "")));

  const grid = el("div", "vehicle-specs");
  const cell = (label: string, value: string, amount = false) => {
    const wrap = el("div");
    wrap.append(
      el("div", "spec-label", label),
      el("div", `spec-value${amount ? " amount" : ""}`, value),
    );
    return wrap;
  };

  const amount = amountFor(listing);
  if (amount) grid.append(cell(amount[0], amount[1], true));
  if (booking.id) grid.append(cell("Booking", booking.id));
  if (listing.location) grid.append(cell("Location", String(listing.location)));
  box.append(grid);
  return box;
}

function renderMockBanner(): HTMLElement {
  const banner = el("div", "mock-banner");
  banner.setAttribute("role", "note");
  banner.dataset.mock = "true";
  banner.append(
    el("span", "mock-tag", "MOCK"),
    el(
      "span",
      "mock-text",
      // The server sends a notice; this falls back to its own wording
      // rather than rendering nothing, because spec.md US4 AS1 is a
      // requirement on the *screen* and must not depend on a field
      // arriving.
      payload.notice ??
        "This is a demo checkout. No real payment is processed and no card details are stored.",
    ),
  );
  return banner;
}

function renderField(
  def: { name: string; label: string; placeholder: string; numeric?: boolean },
  hint?: string,
): HTMLElement {
  const wrap = el("div", "field");
  wrap.dataset.field = def.name;
  wrap.dataset.invalid = String(Boolean(errors[def.name]));

  const id = `field-${def.name}`;
  const label = el("label", undefined, def.label);
  label.htmlFor = id;
  label.append(el("span", "required", "*"));
  wrap.append(label);

  const input = el("input", def.numeric ? "numeric" : undefined);
  input.id = id;
  input.type = "text";
  input.placeholder = def.placeholder;
  input.value = card[def.name] ?? "";
  if (def.numeric) input.inputMode = "numeric";
  input.setAttribute("aria-required", "true");
  // No `name` attribute and autocomplete off, on purpose. A field named
  // `cardnumber` invites the browser and any password manager to offer to
  // *store* it — which would put a real card number on the user's disk,
  // outside anything this codebase controls, from a form that is
  // explicitly a mock. Principle III is about not retaining payment data
  // anywhere, and "anywhere" includes the client.
  input.autocomplete = "off";
  if (errors[def.name]) {
    input.setAttribute("aria-invalid", "true");
    input.setAttribute("aria-describedby", `${id}-error`);
  }
  input.addEventListener("input", () => {
    card[def.name] = input.value;
  });
  wrap.append(input);

  if (errors[def.name]) {
    const message = el("div", "field-error", errors[def.name]);
    message.id = `${id}-error`;
    wrap.append(message);
  } else if (hint) {
    wrap.append(el("div", "field-hint", hint));
  }
  return wrap;
}

function renderConfirmation(): HTMLElement {
  const box = el("div", "confirmed");
  box.setAttribute("role", "status");
  box.append(el("div", "title", "Mock payment confirmed"));
  box.append(el("div", "ref", confirmation!.confirmation_code));

  const listing = payload.listing ?? {};
  const name = [listing.year, listing.brand, listing.model]
    .filter((part) => part !== undefined && part !== "")
    .join(" ");
  const amount = amountFor(listing);
  // Every value here comes from a tool record: the code and id from
  // confirm_mock_payment, the car and amount from open_mock_checkout.
  if (name) box.append(el("div", "detail", `${name}${amount ? ` — ${amount[1]}` : ""}`));
  box.append(el("div", "detail", `Booking ${confirmation!.booking_id}`));
  box.append(
    el("div", "detail", "No payment was taken. This is a demo and no card details were stored."),
  );
  return box;
}

function render(): void {
  root.replaceChildren();

  if (confirmation) {
    root.append(renderConfirmation());
    return;
  }

  const cardBox = el("div", "card");
  // The mock banner is the first child, before the amount. A disclosure
  // below the fold is not "unambiguous".
  cardBox.append(renderMockBanner());
  cardBox.append(el("h1", "title", "Confirm your booking"));
  cardBox.append(
    el("p", "subtitle", "Enter any card details you like — they are never sent or stored."),
  );

  if (payload.listing) cardBox.append(renderVehicle(payload.listing, payload.booking ?? {}));

  if (formError) {
    const banner = el("div", "summary", formError);
    banner.setAttribute("role", "alert");
    banner.dataset.formError = "true";
    cardBox.append(banner);
  }

  const errorCount = Object.keys(errors).length;
  if (errorCount > 0) {
    cardBox.append(
      el(
        "div",
        "summary",
        errorCount === 1
          ? "Please correct the highlighted field."
          : `Please correct the ${errorCount} highlighted fields.`,
      ),
    );
  }

  const fields = el("div", "fields");
  fields.append(renderField(CARD_FIELDS[0]));
  fields.append(
    renderField(CARD_FIELDS[1], "Any 13–19 digits. Nothing is validated against a real network."),
  );
  const row = el("div", "field-row");
  for (const def of SHORT_FIELDS) row.append(renderField(def));
  fields.append(row);
  cardBox.append(fields);

  const actions = el("div", "actions");
  const pay = el("button", undefined, paying ? "Authorising…" : "Pay (mock)");
  pay.disabled = paying || !payload.booking?.id;
  pay.addEventListener("click", () => void onPay());
  actions.append(pay, el("span", "note", "Mock payment — nothing is charged."));
  cardBox.append(actions);

  root.append(cardBox);
}

/**
 * The mock "authorization" step, run entirely inside this document.
 *
 * Shape only. It deliberately does no Luhn check and contacts nothing:
 * a real-looking validation would imply a real network, and the CSP
 * (`connect-src 'none'`) means there is not one to contact. Bounds are
 * loose for the same reason booking's email rule is loose — an
 * over-strict check that rejects a judge's improvised input mid-demo is
 * a worse failure than one that accepts something odd, because the value
 * is discarded either way.
 */
function authoriseLocally(): Record<string, string> {
  const found: Record<string, string> = {};

  if (!(card.card_name ?? "").trim()) {
    found.card_name = "Enter the name on the card.";
  }

  const digits = (card.card_number ?? "").replace(/[\s-]/g, "");
  if (!digits) {
    found.card_number = "Enter a card number.";
  } else if (!/^\d{13,19}$/.test(digits)) {
    found.card_number = "Enter 13 to 19 digits. Any number works — this is a mock.";
  }

  if (!/^\d{2}\s*\/\s*\d{2}$/.test((card.card_expiry ?? "").trim())) {
    found.card_expiry = "Use MM/YY.";
  }

  if (!/^\d{3,4}$/.test((card.card_cvc ?? "").trim())) {
    found.card_cvc = "3 or 4 digits.";
  }

  return found;
}

/**
 * Constitution Principle III, implemented as the sentence it comes from:
 * *"discarded immediately after the mock 'authorization' step"*.
 *
 * Replaces the object rather than deleting keys, so no stale reference
 * keeps the old values reachable, and re-renders from the emptied state
 * so nothing card-like remains in the DOM either.
 */
function forgetCard(): void {
  card = {};
}

/**
 * What is sent to the server: nothing.
 *
 * A named function for an empty object looks like ceremony and is not.
 * `confirm_mock_payment`'s server signature accepts a `fields` argument
 * and drops it through an allowlist; the temptation, the next time
 * someone wants "just the last four on the receipt", is to start filling
 * it in here. Having the decision live in one named, commented place
 * makes that a visible edit in a diff instead of four characters inside a
 * call. `booking_id` is not sent either — the backend supplies it from
 * persisted session state, because the browser's idea of which booking
 * this is must not decide what gets paid for.
 */
function buildToolArguments(): Record<string, never> {
  return {};
}

async function onPay(): Promise<void> {
  if (paying) return;
  paying = true;
  errors = {};
  formError = null;
  render();

  const found = authoriseLocally();
  if (Object.keys(found).length > 0) {
    errors = found;
    paying = false;
    render();
    return;
  }

  // Authorised. The card values have served their entire purpose and are
  // dropped here, before any await — so they are not even live across the
  // network call, let alone sent over it.
  forgetCard();

  try {
    const result = await app.callServerTool({
      name: "confirm_mock_payment",
      arguments: buildToolArguments(),
    });

    const out = (result as { structuredContent?: Record<string, unknown> }).structuredContent ?? {};
    if (out.ok === true && out.confirmation) {
      confirmation = out.confirmation as Confirmation;
    } else if (out.errors && typeof out.errors === "object") {
      const messages = Object.values(out.errors as Record<string, string>);
      formError = messages[0] ?? "The payment could not be confirmed.";
    } else {
      formError = "Something went wrong confirming the payment. Please try again.";
    }
  } catch (cause) {
    formError = `Could not reach the payment service: ${String(cause)}`;
  } finally {
    paying = false;
    render();
  }
}

/** Apply the host's theme variables to this document. */
function applyHostStyles(styles?: Record<string, string | undefined>): void {
  if (!styles) return;
  for (const [key, value] of Object.entries(styles)) {
    if (value) document.documentElement.style.setProperty(key, value);
  }
}

const app = new App(
  { name: "car-matchmaker-checkout", version: "1.0.0" },
  {},
  { autoResize: true },
);

/**
 * The host delivers `open_mock_checkout`'s result here. Registered
 * *before* connect() deliberately: this is a one-shot notification and
 * the SDK warns that a handler attached after the handshake may have
 * already missed it.
 */
app.ontoolresult = (params) => {
  const structured = (params as { structuredContent?: CheckoutPayload }).structuredContent;
  if (!structured) return;
  payload = structured;
  errors = {};
  formError = null;
  render();
};

render();

void app.connect().then(() => {
  const context = app.getHostContext();
  applyHostStyles(context?.styles as Record<string, string | undefined> | undefined);
  if (context?.theme) document.documentElement.dataset.theme = context.theme;
  app.onhostcontextchanged = (next) => {
    applyHostStyles(next?.styles as Record<string, string | undefined> | undefined);
    if (next?.theme) document.documentElement.dataset.theme = next.theme;
  };
});
