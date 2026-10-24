// A touch screen (a phone, a tablet) gets taps nobody meant: in a pocket, as the screen comes back
// on, on a button that just appeared where the finger already was.

export const touch = matchMedia("(pointer: coarse)").matches;

export const SETTLE = 600; // ms

/** On a touch screen, `ready` is false for a moment after the component appears and after the
 *  page comes back on screen: its buttons are disabled then. Always ready elsewhere. Call it while
 *  a component is being made (it uses an effect). */
export function settled(): { readonly ready: boolean } {
  const state = $state({ ready: !touch });
  if (!touch) return state;
  $effect(() => {
    let timer = setTimeout(() => (state.ready = true), SETTLE);
    const changed = (): void => {
      clearTimeout(timer);
      state.ready = false;
      if (document.visibilityState === "visible") timer = setTimeout(() => (state.ready = true), SETTLE);
    };
    document.addEventListener("visibilitychange", changed);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", changed);
    };
  });
  return state;
}
