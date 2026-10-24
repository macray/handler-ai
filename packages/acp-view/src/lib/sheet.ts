// A sheet (a panel over the page, from the bottom of a narrow screen) moved by its handle: it
// follows the finger, past its top it resists, and on release the page says where it settles.

import type { Attachment } from "svelte/attachments";

/** On the handle of an element marked `data-sheet`. `release(dy, velocity)`: dy in px (down is
 *  positive), velocity in px/ms; it returns true when the sheet goes away (it leaves from where the
 *  finger left it), false when it stays (it springs back, by its own CSS transition). */
export function dragSheet(release: (dy: number, velocity: number) => boolean): Attachment<HTMLElement> {
  return (handle) => {
    const down = (start: PointerEvent): void => {
      const sheet = handle.closest<HTMLElement>("[data-sheet]");
      if (!sheet) return;
      handle.setPointerCapture(start.pointerId);
      let dy = 0;
      let last = { y: start.clientY, t: start.timeStamp };
      let velocity = 0;
      sheet.style.transition = "none";
      const move = (e: PointerEvent): void => {
        const raw = e.clientY - start.clientY;
        dy = raw > 0 ? raw : raw / 4; // up: a little, as a rubber band
        sheet.style.transform = `translateY(${dy}px)`;
        if (e.timeStamp > last.t) velocity = (e.clientY - last.y) / (e.timeStamp - last.t);
        last = { y: e.clientY, t: e.timeStamp };
      };
      const up = (): void => {
        handle.removeEventListener("pointermove", move);
        sheet.style.transition = "";
        if (!release(dy, velocity)) sheet.style.transform = "";
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up, { once: true });
      handle.addEventListener("pointercancel", up, { once: true });
    };
    handle.addEventListener("pointerdown", down);
    return () => handle.removeEventListener("pointerdown", down);
  };
}

/** A drag that means "away": far enough, or quick enough downwards. */
export function flungDown(dy: number, velocity: number): boolean {
  return dy > 120 || (dy > 24 && velocity > 0.5);
}

/** A drag that means "further up". */
export function flungUp(dy: number, velocity: number): boolean {
  return dy < -12 || velocity < -0.4;
}
