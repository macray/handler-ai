// Settings → Your phone's guided gateway setup (E5): the ways to run the gateway, each one's
// commands (those of the phone guide, docs/phone.md), and what failed when Connect or the gateway
// did, in words. Connect saves the address and the token (contract D.7, refused when they are not
// ones), then handlerd tries the gateway once and answers with the light that try set: what
// failed is said beside Connect at once. After, handlerd reaches the gateway while something is
// on a phone, and says how it went in the status light and its detail.
import { ApiError } from "./api";
import type { RemoteLight } from "./remote.svelte";

/** A way to run the gateway: its tab, then its steps 1–3 (step 4 is the form). */
export type GatewayWay = {
  id: "container" | "direct" | "community";
  label: string;
  soon?: boolean; // shown greyed, not chosen
  run?: { note: string; command: string; after?: string };
  addHost?: string; // step 3: prints the host token
};

/** Step 2, the same for every way: Tailscale in front, HTTPS for the phone's WebCrypto. */
export const HTTPS_COMMAND = "tailscale serve --bg --https=443 http://127.0.0.1:7431";

/** The way shown first. */
export const CONTAINER: GatewayWay = {
  id: "container",
  label: "Container",
  run: {
    note: "on that machine, from Handler's source folder (with Podman)",
    command: [
      "podman build -f remote-gateway/Containerfile -t handler-gateway .",
      "podman run -d --name handler-gateway -p 127.0.0.1:7431:7431 \\",
      "  -v handler-gateway:/state handler-gateway",
    ].join("\n"),
    after: "To keep it running after a reboot, the phone guide has its Quadlet unit.",
  },
  addHost: "podman exec handler-gateway handler-gateway add-host laptop",
};

export const GATEWAY_WAYS: GatewayWay[] = [
  CONTAINER,
  {
    id: "direct",
    label: "Without a container",
    run: {
      note: "on that machine, from Handler's source folder (with uv and bun)",
      command: [
        "bun install",
        "(cd packages/remote-client && bun run build)",
        "uv tool install ./remote-gateway",
        'handler-gateway serve --port 7431 --client "$PWD/packages/remote-client/dist"',
      ].join("\n"),
      after: "It runs while that terminal is open: the phone guide has a systemd unit to keep it running.",
    },
    addHost: "handler-gateway add-host laptop",
  },
  { id: "community", label: "Community gateway", soon: true },
];

/** Why Connect was refused (D.7: 422 when the address or the token is not one), in words: each
 *  field the refusal names; anything else (handlerd down, say) as it came. */
export function connectError(e: unknown): string {
  if (e instanceof ApiError && e.status === 422) {
    const detail = e.detail ?? "";
    const said = [
      /^gatewayUrl$/m.test(detail) &&
        "This address can't be used: it starts with https:// (plain http:// only for a gateway on this computer).",
      /^hostToken$/m.test(detail) && "This isn't a host token: it is the line starting with h_ that step 3 prints.",
    ].filter(Boolean);
    if (said.length) return said.join(" ");
  }
  return `Couldn't save the gateway: ${(e as Error).message}`;
}

/** The detail of Connect's try when something answered, but not as a gateway (D.7). */
export const NOT_A_GATEWAY = "not a gateway's answer";

/** What the status light says went wrong with the saved gateway, in words with its fix; null
 *  when nothing did. `detail` is the poll's error: "HTTP <code>" when something answered with an
 *  error, NOT_A_GATEWAY when it answered with something else (Connect's try tells), otherwise the
 *  connection's own error. `atConnect`: said beside Connect, where the token is pasted again
 *  (otherwise beside the saved gateway, where Change opens the form). */
export function gatewayProblem(light: RemoteLight | undefined, detail?: string | null, atConnect = false): string | null {
  if (light === "unauthorized")
    return `Reached the gateway, but it doesn't know this token: run step 3 again on the gateway's machine, then ${atConnect ? "paste its new token here" : "Change"}.`;
  if (light !== "unreachable") return null;
  const status = detail?.match(/^HTTP (\d{3})$/)?.[1];
  if (status) return `Something answered at this address, but not as a gateway does (HTTP ${status}): check the address.`;
  if (detail === NOT_A_GATEWAY) return "Something answered at this address, but not as a gateway does: check the address.";
  return `The gateway didn't answer at this address${detail ? ` (${detail})` : ""}: check the address, that the gateway runs, and that this computer reaches it (on your tailnet?).`;
}
