// On a phone the page runs in handler's frame, with no network: __handlerFetch carries the calls.
const send = globalThis.__handlerFetch ?? fetch;
const show = async (r) => { document.getElementById("n").textContent = (await r.json()).n; };
document.getElementById("add").onclick = () => send("/api/count", { method: "POST" }).then(show);
send("/api/count").then(show);
