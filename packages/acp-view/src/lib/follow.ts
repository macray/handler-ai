// Keeps a scrolling timeline at its end while the user is there, like a terminal: on new output
// (`toEnd()`), and when the box shrinks (the composer growing a line would otherwise cover the
// last lines). Scrolling up stops it; scrolling back to the end, or sending (`resume()`), resumes.
export class FollowEnd {
  private el: HTMLElement | null = null;
  private following = true;
  private lastTop = 0;

  /** `{@attach follow.attach}` on the scrolling element. */
  attach = (el: HTMLElement): (() => void) => {
    this.el = el;
    const observer = new ResizeObserver(() => this.toEnd());
    observer.observe(el);
    el.addEventListener("scroll", this.scrolled);
    return () => {
      observer.disconnect();
      el.removeEventListener("scroll", this.scrolled);
      this.el = null;
    };
  };

  toEnd(): void {
    if (this.following) this.el?.scrollTo({ top: this.el.scrollHeight });
  }

  resume(): void {
    this.following = true;
    this.toEnd();
  }

  // Only a scroll up stops following: the event of our own scrollTo arrives a frame later, when
  // the composer may have grown again and the end look out of reach.
  private scrolled = (): void => {
    if (!this.el) return;
    const top = this.el.scrollTop;
    if (this.el.scrollHeight - top - this.el.clientHeight < 40) this.following = true;
    else if (top < this.lastTop) this.following = false;
    this.lastTop = top;
  };
}
