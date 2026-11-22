// The Library's Tools shelf (G, D.15): each tool with its connections, the connections whose tool
// is gone apart, and who each is given to, in words.
import { describe, expect, it } from "vitest";
import type { AddonInfo, BindingInfo } from "../src/lib/contracts.gen";
import { connectionFacts, connectionUsers, givenWords, shelfOf, toolUsers } from "../src/lib/tools";

const tool = (name: string): AddonInfo => ({ name, directory: `/t/${name}` });

describe("the Tools shelf", () => {
  it("puts each connection under its tool, and those whose tool is gone apart", () => {
    const connections: BindingInfo[] = [
      { name: "dev-shop", addon: "shopify" },
      { name: "live-shop", addon: "shopify" },
      { name: "crm-prod", addon: "hubspot" },
      { name: "broken", error: "unknown tool 'nope'" },
    ];
    const shelf = shelfOf([tool("shopify"), tool("browser")], connections);
    expect(shelf.tools.map((t) => [t.tool.name, t.connections.map((c) => c.name)])).toEqual([
      ["shopify", ["dev-shop", "live-shop"]],
      ["browser", []],
    ]);
    expect(shelf.orphans.map((c) => c.name)).toEqual(["crm-prod", "broken"]);
  });

  it("says who a connection is given to, as the rest of the UI names them", () => {
    expect(connectionUsers(["agents/shop-theme/dev", "projects/blog", "ad-hoc/a1b2"])).toEqual(["shop-theme · dev", "all agents of blog", "a1b2 (outside projects)"]);
    expect(connectionUsers()).toEqual([]);
  });

  it("says who a tool is given to: agents and projects, each once", () => {
    const refs = [
      { kind: "agent", label: "shop-theme · review" },
      { kind: "agent", label: "shop-theme · review" },
      { kind: "project", label: "blog" },
      { kind: "automation", label: "nightly" },
    ];
    expect(toolUsers(refs)).toEqual(["shop-theme · review", "all agents of blog"]);
  });

  it("joins them in a sentence", () => {
    expect(givenWords([])).toBe("not given to any agent yet");
    expect(givenWords(["a"])).toBe("given to a");
    expect(givenWords(["a", "b", "c"])).toBe("given to a, b and c");
  });

  it("says what a connection holds: its values, then its secrets sealed", () => {
    expect(connectionFacts({ name: "s", settings: { store: "dev.example.com" }, secrets: ["theme_token"] })).toEqual(["dev.example.com", "theme_token sealed"]);
    expect(connectionFacts({ name: "s" })).toEqual([]);
  });
});
