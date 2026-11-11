// A prompt from the phone is never lost (remote design §5, the lease): re-attached
// before it is sent after a sleep, sent again when the host had detached the phone, given back
// to the input when it still fails.
import { beforeEach, describe, expect, it } from "vitest";
import type { AcpConnection } from "@handler/acp-view/lib/connection.svelte";
import { app, loadDraft, saveDraft } from "../src/lib/app.svelte";
import type { Mailbox } from "../src/lib/mailbox.svelte";
import type { SharedSession } from "../src/lib/remote.gen";

/** An attachment whose prompts answer, in turn, with `outcomes` (an error is thrown). */
function attachment(outcomes: (string | Error)[], prompts: string[]): AcpConnection {
  return {
    closed: null,
    async prompt(text: string) {
      prompts.push(text);
      const next = outcomes.shift() ?? "end_turn";
      if (next instanceof Error) throw next;
      return next;
    },
  } as unknown as AcpConnection;
}

const notAttached = Object.assign(new Error("not attached: initialize"), { code: -32021 });

describe("send", () => {
  let prompts: string[];
  let attached: number;

  function setUp(first: (string | Error)[], afterReattach: (string | Error)[], mayBeDetached = false): void {
    prompts = [];
    attached = 0;
    app.current = { id: "s1" } as SharedSession;
    app.mailbox = { mayBeDetached } as Mailbox;
    app.conn = attachment(first, prompts);
    app.open = async () => {
      attached++;
      app.conn = attachment(afterReattach, prompts);
    };
  }

  beforeEach(() => {
    app.error = null;
  });

  it("sends again on a new attachment when the host had detached the phone", async () => {
    setUp([notAttached], []);
    expect(await app.send("hello")).toBe(true);
    expect(prompts).toEqual(["hello", "hello"]);
    expect(attached).toBe(1);
    expect(app.error).toBeNull();
  });

  it("re-attaches before sending after a sleep", async () => {
    setUp([new Error("should not be used")], [], true);
    expect(await app.send("hello")).toBe(true);
    expect(attached).toBe(1);
    expect(prompts).toEqual(["hello"]);
  });

  it("says a prompt that still fails is back in the input", async () => {
    setUp([new Error("the gateway refused it (502)")], []);
    expect(await app.send("hello")).toBe(false);
    expect(app.error).toBe("Your message failed (the gateway refused it (502)). It is back in the input.");
    expect(attached).toBe(1); // a sound attachment for the next try
  });
});

describe("drafts", () => {
  beforeEach(() => localStorage.clear());

  it("are kept per session until sent", () => {
    saveDraft("s1", "half a thought");
    expect(loadDraft("s1")).toBe("half a thought");
    expect(loadDraft("s2")).toBe("");
    saveDraft("s1", "");
    expect(localStorage.length).toBe(0);
  });
});
