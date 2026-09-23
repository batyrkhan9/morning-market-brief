// Strict command parsing. Same rules on the Python side (src/inbox.py) so nothing bad reaches the repo.

const TICKER = /^[A-Z][A-Z0-9.\-]{0,9}$/;
const SNAPSHOT_ITEMS = ["SPX", "NDX", "DJI", "RUT", "VIX", "DXY", "OIL", "GOLD", "US2Y", "US10Y"];
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function isTicker(t) {
  return TICKER.test(t) || SNAPSHOT_ITEMS.includes(t);
}

function validDate(s, today) {
  if (!ISO_DATE.test(s)) return false;
  const d = new Date(s + "T00:00:00Z");
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== s) return false;
  return !today || s > today;
}

// /predict NKE above 40 by 2026-12-31 because ...   (also "below")
export function parsePredict(text, today) {
  const m = text.trim().match(/^\/predict\s+(\S+)\s+(above|below)\s+([0-9]+(?:[.,][0-9]+)?)\s+by\s+(\S+)\s+because\s+(.{3,})$/is);
  if (!m) return { ok: false, error: "format" };
  const ticker = m[1].toUpperCase();
  if (!isTicker(ticker)) return { ok: false, error: "ticker" };
  const level = parseFloat(m[3].replace(",", "."));
  if (!(level > 0)) return { ok: false, error: "level" };
  if (!validDate(m[4], today)) return { ok: false, error: "date" };
  return { ok: true, data: { ticker, direction: m[2].toLowerCase(), level, by: m[4], reason: m[5].trim().slice(0, 500) } };
}

// /thesis NKE five sentences ...
export function parseThesis(text) {
  const m = text.trim().match(/^\/thesis\s+(\S+)\s+([\s\S]{20,})$/i);
  if (!m) return { ok: false, error: "format" };
  const ticker = m[1].toUpperCase();
  if (!TICKER.test(ticker)) return { ok: false, error: "ticker" };
  return { ok: true, data: { ticker, text: m[2].trim().slice(0, 4000) } };
}

// /queue NKE
export function parseQueue(text) {
  const m = text.trim().match(/^\/queue\s+(\S+)\s*$/i);
  if (!m) return { ok: false, error: "format" };
  const ticker = m[1].toUpperCase();
  if (!TICKER.test(ticker)) return { ok: false, error: "ticker" };
  return { ok: true, data: { ticker } };
}

export const PARSERS = { "/predict": parsePredict, "/thesis": parseThesis, "/queue": parseQueue };

export function commandOf(text) {
  const m = (text || "").trim().match(/^(\/[a-z]+)/i);
  return m ? m[1].toLowerCase() : null;
}
