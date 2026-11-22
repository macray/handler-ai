/** How long ago `at` (an ISO date or ms), in a few characters: "now", "5 min", "3 h", a date. */
export function ago(at: string | number, now = Date.now()): string {
  const s = Math.max(0, (now - new Date(at).getTime()) / 1000);
  if (Number.isNaN(s)) return "";
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  if (s < 86400) return `${Math.floor(s / 3600)} h`;
  return new Date(at).toLocaleDateString();
}

/** When `at` (ms) was, to the minute: "14:02" today, with its date another day. */
export function when(at: number, now = Date.now()): string {
  const time = new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return new Date(at).toDateString() === new Date(now).toDateString() ? time : `${new Date(at).toLocaleDateString()}, ${time}`;
}
