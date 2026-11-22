// Nudges (H.17): what an app asks you to do, in your inbox until it is done, dismissed or expired.
// How it alerts you is yours, per nudge of an app: its reminders as the app says, none, or no
// alert at all (Reminders), in words with what each means; and what the app says, in words.
import { DAYS, WEEKDAYS, type Day } from "./automations";
import type { AppManifestNudgeRemind, InboxMessage, InboxNudge, NudgeSettingRequest, Schedule } from "./contracts.gen";

export type NudgeSetting = NudgeSettingRequest["setting"];

/** The choices, most alerts first. */
export const SETTINGS: NudgeSetting[] = ["default", "once", "silent"];

export const SETTING_WORDS: Record<NudgeSetting, string> = {
  default: "As the app says",
  once: "No reminders",
  silent: "Never alert me",
};

/** What a choice means for this nudge: "reminds you every day, 2 times", "it alerts you once",
 *  "it comes to your inbox quietly". */
export function settingMeaning(setting: NudgeSetting, remind: AppManifestNudgeRemind | null | undefined): string {
  if (setting === "default") return remindWords(remind);
  return setting === "once" ? "it alerts you once" : "it comes to your inbox quietly";
}

/** "30m", "2h", "1d" in words: "30 minutes", "an hour", "2 hours", "a day". */
export function durationWords(every: string): string {
  const n = Number(every.slice(0, -1));
  const unit = every.endsWith("d") ? "day" : every.endsWith("h") ? "hour" : "minute";
  if (n === 1) return unit === "hour" ? "an hour" : `a ${unit}`;
  return `${n} ${unit}s`;
}

/** The app's reminders after the first alert, in words: "reminds you every 2 hours, 2 times",
 *  "reminds you once more after an hour", "alerts you once, no reminders". */
export function remindWords(remind: AppManifestNudgeRemind | null | undefined): string {
  if (!remind) return "alerts you once, no reminders";
  const times = remind.times ?? 1;
  const after = durationWords(remind.every);
  if (times === 1) return `reminds you once more after ${after}`;
  const every = after.replace(/^an? /, ""); // "every day", "every hour", "every 2 hours"
  return `reminds you every ${every}, ${times} times`;
}

const DAY_NAMES: Record<Day, string> = { mon: "Mondays", tue: "Tuesdays", wed: "Wednesdays", thu: "Thursdays", fri: "Fridays", sat: "Saturdays", sun: "Sundays" };

/** When Handler sends a nudge, in words: "Fridays at 16:00", "every day at 09:00", "weekdays at
 *  08:30", "Mondays and Fridays at 16:00", "every 2 days". */
export function whenWords(when: Schedule): string {
  if (when.every) {
    const words = durationWords(when.every);
    return `every ${words.replace(/^an? /, "")}`;
  }
  const days = when.days?.length ? DAYS.filter((d) => when.days?.includes(d)) : DAYS;
  let on: string;
  if (days.length === DAYS.length) on = "every day";
  else if (days.length === WEEKDAYS.length && WEEKDAYS.every((d) => days.includes(d))) on = "weekdays";
  else {
    const names = days.map((d) => DAY_NAMES[d]);
    on = names.length === 1 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
  }
  return `${on} at ${when.at}`;
}

/** A nudge still asking you something. */
export function isOpen(m: InboxMessage): m is InboxMessage & { nudge: InboxNudge } {
  return m.kind === "nudge" && !!m.nudge && (m.nudge.state ?? "open") === "open";
}

/** An ended nudge's state, in words (an open one: null). */
export function endedWords(n: InboxNudge): string | null {
  switch (n.state) {
    case "done":
      return "Done";
    case "dismissed":
      return "Dismissed";
    case "expired":
      return "Expired";
    default:
      return null;
  }
}

/** An inbox message the bell counts: unread, and failed, wanting an answer, or an open nudge. */
export function waitsForYou(m: InboxMessage): boolean {
  return !m.read && (m.status === "failed" || m.status === "attention" || isOpen(m));
}
