import type { buildAllowAttribute } from "@modelcontextprotocol/ext-apps/app-bridge";

import type { CspDeclaration } from "./csp";

/**
 * The `mcp_app` WebSocket envelope, as `api/main.py` builds it.
 *
 * Both notification halves are present deliberately: ext-apps 1.7.5 states
 * `sendToolInput` "is sent exactly once and is required before
 * `sendToolResult`", so a host that forwards only the result leaves the
 * View waiting for a notification that never arrives.
 */
export type McpAppEnvelope = {
  type: "mcp_app";
  app: string;
  toolName: string;
  resource: {
    uri: string;
    mimeType: string;
    html: string;
    /** The resource's `_meta`. `ui.csp` is spec.md US3 AS1's declaration. */
    meta?: {
      ui?: {
        csp?: CspDeclaration;
        /** Shaped by ext-apps' McpUiResourcePermissions (camera, microphone,
         *  geolocation, clipboardWrite...). The booking App declares `{}`. */
        permissions?: Parameters<typeof buildAllowAttribute>[0];
      };
    };
  };
  toolInput: { arguments: Record<string, unknown> };
  toolResult: { structuredContent: Record<string, unknown> };
};

/** What the host sends back up the socket when the App calls a tool. */
export type AppToolCall = {
  type: "app_tool_call";
  call_id: string;
  name: string;
  arguments: Record<string, unknown>;
};

export type AppToolResult = {
  type: "app_tool_result";
  call_id: string;
  result: { structuredContent?: Record<string, unknown> };
};
