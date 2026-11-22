// Settings → Your phone's guided gateway setup (E5): each way's commands are the phone guide's,
// and what failed (Connect refused, its try of the gateway, or the light) is said in words with
// its fix.
import { describe, expect, it } from "vitest";
import { ApiError } from "../src/lib/api";
import { CONTAINER, GATEWAY_WAYS, NOT_A_GATEWAY, connectError, gatewayProblem } from "../src/lib/gateway";

// pydantic's message for a refused body, as handlerd sends it in the 422's detail (parse_body)
const refused = (...fields: string[]) =>
  new ApiError(422, "invalid request", [`${fields.length} validation errors for SetRemoteGatewayRequest`, ...fields.flatMap((f) => [f, "  String should match pattern '…'"])].join("\n"));

describe("the ways to run the gateway", () => {
  it("are tabs: Container first, Without a container, and a community gateway, soon", () => {
    expect(GATEWAY_WAYS.map((w) => [w.label, Boolean(w.soon)])).toEqual([
      ["Container", false],
      ["Without a container", false],
      ["Community gateway", true],
    ]);
    expect(GATEWAY_WAYS[0]).toBe(CONTAINER);
  });

  it("each prints the host token with add-host, in the container or not", () => {
    expect(CONTAINER.addHost).toBe("podman exec handler-gateway handler-gateway add-host laptop");
    expect(GATEWAY_WAYS[1]?.addHost).toBe("handler-gateway add-host laptop");
    expect(CONTAINER.run?.command.split("\n")[0]).toBe("podman build -f remote-gateway/Containerfile -t handler-gateway .");
    expect(GATEWAY_WAYS[1]?.run?.command).toContain("uv tool install ./remote-gateway");
  });
});

describe("Connect refused", () => {
  it("names the address when it is not https", () => {
    expect(connectError(refused("gatewayUrl"))).toMatch(/^This address can't be used: it starts with https:\/\//);
  });

  it("names the token when it is not one, pointing at step 3", () => {
    expect(connectError(refused("hostToken"))).toBe("This isn't a host token: it is the line starting with h_ that step 3 prints.");
  });

  it("names both when both are wrong", () => {
    const said = connectError(refused("gatewayUrl", "hostToken"));
    expect(said).toContain("This address can't be used");
    expect(said).toContain("This isn't a host token");
  });

  it("says anything else as it came", () => {
    expect(connectError(new TypeError("Failed to fetch"))).toBe("Couldn't save the gateway: Failed to fetch");
    expect(connectError(new ApiError(500, "Internal Server Error"))).toBe("Couldn't save the gateway: Internal Server Error");
  });
});

describe("the gateway's light, in words", () => {
  it("nothing when it is reachable, idle or not set", () => {
    for (const light of ["ok", "idle", "off", undefined] as const) expect(gatewayProblem(light, null)).toBeNull();
  });

  it("a refused token: run step 3 again", () => {
    expect(gatewayProblem("unauthorized", "the gateway refused the host token")).toBe(
      "Reached the gateway, but it doesn't know this token: run step 3 again on the gateway's machine, then Change.",
    );
  });

  it("an HTTP error: something answered, not as a gateway", () => {
    expect(gatewayProblem("unreachable", "HTTP 404")).toBe("Something answered at this address, but not as a gateway does (HTTP 404): check the address.");
  });

  it("no answer: the gateway didn't answer, with the connection's error", () => {
    const said = gatewayProblem("unreachable", "All connection attempts failed");
    expect(said).toMatch(/^The gateway didn't answer at this address \(All connection attempts failed\): check the address/);
  });
});

describe("Connect's try, in words beside Connect", () => {
  it("a refused token: paste the new one here", () => {
    expect(gatewayProblem("unauthorized", "the gateway refused the host token", true)).toBe(
      "Reached the gateway, but it doesn't know this token: run step 3 again on the gateway's machine, then paste its new token here.",
    );
  });

  it("something that is not a gateway answered", () => {
    expect(gatewayProblem("unreachable", NOT_A_GATEWAY, true)).toBe("Something answered at this address, but not as a gateway does: check the address.");
  });

  it("nothing when the try reached it", () => {
    expect(gatewayProblem("ok", null, true)).toBeNull();
  });
});
