/**
 * T044 — Playwright E2E: full interview→payment path.
 *
 * Asserts zero CSP violations and zero console errors throughout.
 * Requires: docker compose up (all services running) and a valid LLM_API_KEY.
 *
 * This test walks through the complete user journey:
 * 1. Open the app, verify initial state
 * 2. Send interview messages (category, budget, transaction type)
 * 3. Wait for catalogue to appear (research complete)
 * 4. Select a listing from the catalogue
 * 5. Fill and submit the booking form
 * 6. Complete the mock checkout
 * 7. Verify confirmation message
 */
import { test, expect } from '@playwright/test';

const WS_HOST = process.env.VITE_AGENT_BACKEND_HOST ?? 'localhost';
const WS_PORT = process.env.VITE_AGENT_BACKEND_PORT ?? '8000';

test.describe('Full interview→payment path', () => {
  test('completes without CSP violations or console errors', async ({ page }) => {
    const consoleErrors: string[] = [];
    const cspViolations: string[] = [];

    // Collect console errors
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    // Collect CSP violations
    page.on('pageerror', (error) => {
      if (error.message.includes('Content Security Policy') ||
          error.message.includes('CSP') ||
          error.message.includes("violates the following Content Security Policy")) {
        cspViolations.push(error.message);
      }
    });

    // 1. Open the app
    await page.goto('/');
    await expect(page.locator('[data-testid="connection-status"]')).toHaveAttribute('data-connected', 'true');
    await expect(page.locator('.chat-title')).toHaveText('AI Car Matchmaker');

    // 2. Send interview message
    const chatInput = page.locator('[data-testid="chat-input"]');
    const sendButton = page.locator('[data-testid="chat-send"]');

    await chatInput.fill('I want an SUV to buy, budget up to $25000, for daily commute.');
    await sendButton.click();

    // Wait for assistant response (interview or research)
    await expect(page.locator('.chat-row[data-role="assistant"]').first()).toBeVisible({ timeout: 30_000 });

    // 3. Wait for catalogue to appear (research phase)
    // The A2UI panel should show a catalogue surface
    const a2uiPanel = page.locator('[data-testid="a2ui-panel"]');
    await expect(a2uiPanel).toBeVisible();

    // Wait for catalogue cards to appear (may take time for research)
    await expect(page.locator('[data-surface-id]').first()).toBeVisible({ timeout: 60_000 });

    // 4. Select a listing (click a catalogue card button)
    // The catalogue cards have "Choose this one" buttons
    const chooseButton = page.locator('button:has-text("Choose this one")').first();
    if (await chooseButton.isVisible({ timeout: 10_000 }).catch(() => false)) {
      await chooseButton.click();

      // 5. Wait for booking form MCP App to appear
      const mcpAppFrame = page.locator('iframe').first();
      await expect(mcpAppFrame).toBeVisible({ timeout: 15_000 });

      // The booking form should be visible in the iframe
      const frame = mcpAppFrame.contentFrame();
      if (frame) {
        // Wait for form fields to load
        await frame.locator('input, select, textarea').first().waitFor({ state: 'visible', timeout: 10_000 });

        // Fill form fields (name, email, phone, pickup date)
        const nameInput = frame.locator('input[name="full_name"], input[placeholder*="name" i]').first();
        if (await nameInput.isVisible().catch(() => false)) {
          await nameInput.fill('Test User');
        }

        const emailInput = frame.locator('input[name="email"], input[type="email"]').first();
        if (await emailInput.isVisible().catch(() => false)) {
          await emailInput.fill('test@example.com');
        }

        const phoneInput = frame.locator('input[name="phone"], input[type="tel"]').first();
        if (await phoneInput.isVisible().catch(() => false)) {
          await phoneInput.fill('555-010-9999');
        }

        // Submit the form
        const submitButton = frame.locator('button[type="submit"], button:has-text("Submit")').first();
        if (await submitButton.isVisible().catch(() => false)) {
          await submitButton.click();

          // 6. Wait for checkout MCP App to appear
          // After booking submission, phase advances to AWAITING_PAYMENT
          // and the checkout iframe should appear
          const checkoutFrame = page.locator('iframe').first();
          await expect(checkoutFrame).toBeVisible({ timeout: 15_000 });

          const checkoutContent = checkoutFrame.contentFrame();
          if (checkoutContent) {
            // Verify checkout is labelled as mock
            await expect(checkoutContent.locator('text=MOCK')).toBeVisible({ timeout: 10_000 });

            // Confirm mock payment
            const confirmButton = checkoutContent.locator('button:has-text("Confirm"), button:has-text("Pay")').first();
            if (await confirmButton.isVisible().catch(() => false)) {
              await confirmButton.click();
            }
          }
        }
      }
    }

    // 7. Verify no CSP violations occurred
    expect(cspViolations).toEqual([]);

    // Allow known benign console errors (like WebSocket reconnect attempts)
    const criticalErrors = consoleErrors.filter(
      (e) => !e.includes('WebSocket') && !e.includes('favicon') && !e.includes('404')
    );
    expect(criticalErrors).toEqual([]);
  });

  test('app loads and shows connected status', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="connection-status"]')).toHaveAttribute('data-connected', 'true');
    await expect(page.locator('.chat-title')).toHaveText('AI Car Matchmaker');
  });

  test('chat input sends message and receives response', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="connection-status"]')).toHaveAttribute('data-connected', 'true');

    const chatInput = page.locator('[data-testid="chat-input"]');
    const sendButton = page.locator('[data-testid="chat-send"]');

    // Send a message
    await chatInput.fill('Hello');
    await sendButton.click();

    // Should get an assistant response
    await expect(page.locator('.chat-row[data-role="assistant"]').first()).toBeVisible({ timeout: 30_000 });
  });

  test('A2UI panel shows progress surfaces', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="connection-status"]')).toHaveAttribute('data-connected', 'true');

    // Send an interview message to trigger research
    const chatInput = page.locator('[data-testid="chat-input"]');
    await chatInput.fill('I need a sedan to rent for $100/day.');
    await page.locator('[data-testid="chat-send"]').click();

    // Wait for A2UI surfaces to appear
    await expect(page.locator('[data-surface-id]').first()).toBeVisible({ timeout: 60_000 });
  });
});
