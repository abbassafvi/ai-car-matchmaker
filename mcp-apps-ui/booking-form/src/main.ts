/**
 * T032 — the in-chat booking form, as an MCP App.
 *
 * Hackathon hard requirement #3. This is a real MCP App, not an iframe that
 * merely looks like one: it speaks the MCP Apps protocol through the
 * official `App` class from @modelcontextprotocol/ext-apps, performing the
 * `ui/initialize` handshake with the host and calling `submit_booking` back
 * through `callServerTool`. Hand-rolling the postMessage handshake was the
 * alternative and was rejected — a protocol you implement from prose is the
 * classic "looks right, never ran" failure this project keeps paying for.
 *
 * Two constitution rules shape the code below more than anything else:
 *
 * - **Principle I (grounded values).** Every vehicle value rendered here
 *   comes from the `open_booking_form` tool result, which the backend built
 *   from `SessionState.selected_listing()` — the verbatim search record.
 *   Nothing is recomputed, re-derived or defaulted; a field the record does
 *   not carry is simply not shown.
 * - **Principle III (mock-only).** There is no payment input anywhere in
 *   this file. Booking collects contact + pickup details only; the mocked
 *   checkout is a separate App (M4b).
 */
import { App } from "@modelcontextprotocol/ext-apps";
import "./styles.css";

type FieldDef = { name: string; label: string; required: boolean };
type Listing = Record<string, string | number>;
type FormPayload = { listing?: Listing; fields?: FieldDef[] };

const root = document.getElementById("root")!;

/** Values the user has typed, kept outside the DOM so a re-render caused by
 * a validation failure cannot lose them (spec.md US3 AS2 is explicit that a
 * rejected submission must not discard already-entered data). */
const entered: Record<string, string> = {};

let payload: FormPayload = {};
let errors: Record<string, string> = {};
/** A failure that belongs to the submission, not to any one field — a
 * transport error, or a response the server should not have sent. Kept
 * separate from `errors` because both of these used to be written as
 * `{ full_name: … }`, which highlighted the name input and told the user
 * something untrue about it: "Could not reach the booking service" is not
 * a problem with their name. */
let formError: string | null = null;
let submitting = false;
let confirmation: { id: string } | null = null;

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
 * It also does **not** round. It used to (`Math.round`), which was harmless
 * against today's dataset — every price, mileage and rent value in all 203
 * listings is an integer — and was still a Principle I bug waiting for the
 * first decimal: a rendered value must be traceable *verbatim* to the tool
 * record, and 24499.5 displayed as $24,500 is a number the marketplace
 * never returned. Any fractional part is preserved instead.
 */
function money(value: number): string {
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
  // textContent, never innerHTML: listing fields are marketplace data, and
  // marketplace data is untrusted by construction (Principle IV). The
  // attacker-controlled `description` is stripped server-side before it
  // ever reaches this document, but that is a second line of defence, not
  // a licence to interpolate the rest as markup.
  if (text !== undefined) node.textContent = text;
  return node;
}

/** The specs shown beside the car, in display order. Only entries the
 * record actually carries are rendered — no placeholders, no "N/A". */
function vehicleSpecs(listing: Listing): Array<[string, string]> {
  const specs: Array<[string, string]> = [];
  const add = (label: string, value: unknown, format?: (v: never) => string) => {
    if (value === undefined || value === null || value === "") return;
    specs.push([label, format ? format(value as never) : String(value)]);
  };

  const renting = listing.transaction_type === "rent";
  if (renting) {
    add("Per day", listing.rent_price_per_day, money);
  } else {
    add("Price", listing.price, money);
  }
  add("Mileage", listing.mileage, (v: number) => `${money(v).slice(1)} mi`);
  add("Fuel", listing.fuel_type);
  add("Seats", listing.seats);
  add("Location", listing.location);
  add("Available", listing.availability_date);
  add("Source", listing.listing_source);
  return specs;
}

function renderVehicle(listing: Listing): HTMLElement {
  const box = el("div", "vehicle");
  const name = [listing.year, listing.brand, listing.model]
    .filter((part) => part !== undefined && part !== "")
    .join(" ");
  box.append(el("div", "vehicle-name", name || String(listing.id ?? "")));

  const grid = el("div", "vehicle-specs");
  for (const [label, value] of vehicleSpecs(listing)) {
    const cell = el("div");
    cell.append(el("div", "spec-label", label), el("div", "spec-value", value));
    grid.append(cell);
  }
  box.append(grid);
  return box;
}

function renderField(def: FieldDef): HTMLElement {
  const wrap = el("div", "field");
  wrap.dataset.field = def.name;
  wrap.dataset.invalid = String(Boolean(errors[def.name]));

  const id = `field-${def.name}`;
  const label = el("label", undefined, def.label);
  label.htmlFor = id;
  if (def.required) label.append(el("span", "required", "*"));
  wrap.append(label);

  const multiline = def.name === "notes";
  const input = multiline ? el("textarea") : el("input");
  input.id = id;
  input.value = entered[def.name] ?? "";
  if (!multiline) {
    const kinds: Record<string, string> = {
      email: "email",
      phone: "tel",
      pickup_date: "date",
    };
    (input as HTMLInputElement).type = kinds[def.name] ?? "text";
  }
  if (def.required) input.setAttribute("aria-required", "true");
  if (errors[def.name]) {
    input.setAttribute("aria-invalid", "true");
    input.setAttribute("aria-describedby", `${id}-error`);
  }
  // Captured on every keystroke so `entered` is always current — a
  // re-render triggered by a server-side rejection reads from here.
  input.addEventListener("input", () => {
    entered[def.name] = input.value;
  });
  wrap.append(input);

  if (errors[def.name]) {
    const message = el("div", "field-error", errors[def.name]);
    message.id = `${id}-error`;
    wrap.append(message);
  }
  return wrap;
}

function renderConfirmation(): HTMLElement {
  const box = el("div", "confirmed");
  box.append(el("div", "title", "Booking submitted"));
  const line = el("div");
  line.append(
    document.createTextNode("Your reference is "),
    el("span", "ref", confirmation!.id),
    document.createTextNode(". Payment is the next step."),
  );
  box.append(line);
  return box;
}

function render(): void {
  root.replaceChildren();

  if (confirmation) {
    root.append(renderConfirmation());
    return;
  }

  const card = el("div", "card");
  card.append(el("h1", "title", "Book this car"));
  card.append(
    el("p", "subtitle", "We just need a few details. No payment is taken at this step."),
  );

  if (payload.listing) card.append(renderVehicle(payload.listing));

  if (formError) {
    const banner = el("div", "summary", formError);
    banner.setAttribute("role", "alert");
    banner.dataset.formError = "true";
    card.append(banner);
  }

  const errorCount = Object.keys(errors).length;
  if (errorCount > 0) {
    card.append(
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
  for (const def of payload.fields ?? []) fields.append(renderField(def));
  card.append(fields);

  const actions = el("div", "actions");
  const submit = el("button", undefined, submitting ? "Submitting…" : "Submit booking");
  submit.disabled = submitting || !payload.fields?.length;
  submit.addEventListener("click", () => void onSubmit());
  actions.append(submit, el("span", "note", "Mock booking — nothing is charged."));
  card.append(actions);

  root.append(card);
}

/** Apply the host's theme variables to this document. */
function applyHostStyles(styles?: Record<string, string | undefined>): void {
  if (!styles) return;
  for (const [key, value] of Object.entries(styles)) {
    if (value) document.documentElement.style.setProperty(key, value);
  }
}

const app = new App(
  { name: "car-matchmaker-booking-form", version: "1.0.0" },
  {},
  { autoResize: true },
);

/**
 * The host delivers `open_booking_form`'s result here. Registered *before*
 * connect() deliberately: this is a one-shot notification and the SDK warns
 * that a handler attached after the handshake may have already missed it.
 */
app.ontoolresult = (params) => {
  const structured = (params as { structuredContent?: FormPayload }).structuredContent;
  if (!structured) return;
  payload = structured;
  errors = {};
  formError = null;
  render();
};

async function onSubmit(): Promise<void> {
  if (submitting) return;
  submitting = true;
  errors = {};
  formError = null;
  render();

  try {
    const result = await app.callServerTool({
      name: "submit_booking",
      arguments: {
        listing_id: payload.listing?.id,
        // Only what the user typed. The listing values are not echoed back
        // — the server already has the record, and round-tripping them
        // through the browser would create a second, tamperable path to a
        // value Principle I requires to be verbatim.
        fields: { ...entered },
      },
    });

    const out = (result as { structuredContent?: Record<string, unknown> }).structuredContent ?? {};
    if (out.ok === true && out.booking) {
      confirmation = { id: String((out.booking as { id: string }).id) };
    } else if (out.errors && typeof out.errors === "object") {
      // Server-side validation is authoritative; `entered` is untouched, so
      // re-rendering shows the messages without losing anything typed.
      errors = out.errors as Record<string, string>;
    } else {
      formError = "Something went wrong submitting the form. Please try again.";
    }
  } catch (cause) {
    formError = `Could not reach the booking service: ${String(cause)}`;
  } finally {
    submitting = false;
    render();
  }
}

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
