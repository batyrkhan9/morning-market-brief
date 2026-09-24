// Send scheduling: one message per user per local day, at their send hour, never a stale edition.

function parts(tz, date) {
  const f = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  const o = Object.fromEntries(f.formatToParts(date).filter((p) => p.type !== "literal").map((p) => [p.type, parseInt(p.value, 10)]));
  return { y: o.year, m: o.month, d: o.day, h: o.hour % 24, min: o.minute };
}

// UTC instant of local wall time y-m-d h:00 in tz (two passes handle the DST offset).
export function localToUtc(tz, y, m, d, h) {
  let guess = Date.UTC(y, m - 1, d, h);
  for (let i = 0; i < 2; i++) {
    const p = parts(tz, new Date(guess));
    const seen = Date.UTC(p.y, p.m - 1, p.d, p.h, p.min);
    guess += Date.UTC(y, m - 1, d, h) - seen;
  }
  return new Date(guess);
}

// Today's send slot for a user, as a UTC instant.
export function slotToday(user, now) {
  const p = parts(user.tz, now);
  return localToUtc(user.tz, p.y, p.m, p.d, user.send_hour);
}

export function localWeekday(tz, date) {
  return new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short" }).format(date);
}

// Decide whether to send `manifest` to `user` now. sentEdition = what they last received.
export function dueForSend(user, manifest, now, sentEdition) {
  if (!manifest || !manifest.edition) return { due: false, reason: "no edition" };
  if (user.paused) return { due: false, reason: "paused" };
  if (sentEdition === manifest.edition) return { due: false, reason: "already sent" };
  let slot;
  try { slot = slotToday(user, now); } catch { return { due: false, reason: "bad timezone" }; }
  if (now < slot) return { due: false, reason: "before send hour" };
  if (user.mode === "simple" && localWeekday(user.tz, now) === "Sun") return { due: false, reason: "sunday" };
  const built = manifest.built_at ? new Date(manifest.built_at) : null;
  if (built && built > slot) return { due: false, reason: "edition built after today's slot, goes out tomorrow" };
  if (user.created && new Date(user.created) > slot) return { due: false, reason: "registered after today's slot, starts tomorrow" };
  return { due: true, reason: "due" };
}
