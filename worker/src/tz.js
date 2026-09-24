// Timezone helpers: offline coordinates -> IANA zone, a short list of common cities, typed city matching.
import tzlookup from "tz-lookup";
import cities from "./cities.json" with { type: "json" };

export const COMMON_CITIES = ["Almaty", "Astana", "Moscow", "London", "Berlin", "Istanbul", "Dubai", "New York",
  "Chicago", "Los Angeles", "Singapore", "Tokyo"];

export function tzFromLocation(lat, lon) {
  return tzlookup(lat, lon);
}

function norm(s) {
  return (s || "").toLowerCase().replace(/[\s\-_.]+/g, " ").trim();
}

export function tzFromCity(text) {
  const q = norm(text);
  if (!q) return null;
  for (const c of cities) {
    if (norm(c.name) === q || (c.aliases || []).some((a) => norm(a) === q)) return { tz: c.tz, city: c.name };
  }
  for (const c of cities) {
    if (norm(c.name).startsWith(q) && q.length >= 3) return { tz: c.tz, city: c.name };
    if ((c.aliases || []).some((a) => norm(a).startsWith(q)) && q.length >= 3) return { tz: c.tz, city: c.name };
  }
  return null;
}

export function isIanaZone(s) {
  try { new Intl.DateTimeFormat("en", { timeZone: s }); return true; } catch { return false; }
}

export function localHour(tz, date = new Date()) {
  return parseInt(new Intl.DateTimeFormat("en", { timeZone: tz, hour: "numeric", hour12: false }).format(date), 10) % 24;
}
