import test from "node:test";
import assert from "node:assert/strict";
import { dueForSend, localToUtc, slotToday } from "../src/schedule.js";

const la = { id: "owner", mode: "full", lang: "en", tz: "America/Los_Angeles", send_hour: 12, paused: false, created: "2026-09-23T07:00:00Z" };
const almaty = { id: "father", mode: "simple", lang: "kk", tz: "Asia/Almaty", send_hour: 8, paused: false, created: "2026-09-01T00:00:00Z" };
const manifest = { edition: "2026-09-23", built_at: "2026-09-24T00:47:00Z", variants: ["full_en"] };   // built 17:47 PDT on the 23rd
const at = (iso) => new Date(iso);

test("slot arithmetic handles DST", () => {
  assert.equal(localToUtc("America/Los_Angeles", 2026, 9, 24, 12).toISOString(), "2026-09-24T19:00:00.000Z");   // PDT
  assert.equal(localToUtc("America/Los_Angeles", 2026, 11, 2, 12).toISOString(), "2026-11-02T20:00:00.000Z");   // PST after Nov 1
  assert.equal(localToUtc("Asia/Almaty", 2026, 1, 15, 8).toISOString(), "2026-01-15T03:00:00.000Z");
  assert.equal(slotToday(la, at("2026-09-24T18:59:00Z")).toISOString(), "2026-09-24T19:00:00.000Z");
});

test("sends at the send hour, once per edition, never before", () => {
  assert.equal(dueForSend(la, manifest, at("2026-09-24T18:59:00Z"), null).due, false);            // 11:59 PDT
  assert.equal(dueForSend(la, manifest, at("2026-09-24T19:01:00Z"), null).due, true);             // 12:01 PDT
  assert.equal(dueForSend(la, manifest, at("2026-09-24T23:00:00Z"), "2026-09-23").due, false);    // already got it
  assert.equal(dueForSend({ ...la, paused: true }, manifest, at("2026-09-24T19:01:00Z"), null).due, false);
});

test("an edition built after today's slot waits for tomorrow", () => {
  // Build finished 17:47 PDT on the 23rd; the owner's slot that day was 12:00 PDT: not today, tomorrow at 12:00.
  assert.equal(dueForSend(la, manifest, at("2026-09-24T01:00:00Z"), null).reason, "edition built after today's slot, goes out tomorrow");
  assert.equal(dueForSend(la, manifest, at("2026-09-24T19:05:00Z"), null).due, true);
  // Almaty 08:00 = 03:00 UTC on the 24th, after the build: due then.
  assert.equal(dueForSend(almaty, manifest, at("2026-09-24T02:59:00Z"), null).due, false);
  assert.equal(dueForSend(almaty, manifest, at("2026-09-24T03:00:00Z"), null).due, true);
});

test("a user who registered after today's slot gets tomorrow's, not a stale edition", () => {
  const late = { ...la, created: "2026-09-24T21:00:00Z" };        // registered 14:00 PDT, send hour 12
  assert.equal(dueForSend(late, manifest, at("2026-09-24T21:30:00Z"), null).reason, "registered after today's slot, starts tomorrow");
  assert.equal(dueForSend(late, manifest, at("2026-09-25T19:00:00Z"), null).due, true);   // next day at 12:00
});

test("simple mode skips Sunday; unknown zone never throws", () => {
  const sunday = at("2026-09-27T05:00:00Z");                         // Sunday 10:00 in Almaty
  assert.equal(dueForSend(almaty, { ...manifest, built_at: "2026-09-26T00:00:00Z" }, sunday, null).reason, "sunday");
  assert.equal(dueForSend({ ...la, tz: "Mars/Olympus" }, manifest, at("2026-09-24T19:01:00Z"), null).reason, "bad timezone");
});
