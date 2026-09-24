import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { keyboardFor, settingsField, startFlow, step, summary } from "../src/onboarding.js";
import { tzFromCity, tzFromLocation, localHour } from "../src/tz.js";
import { validUser } from "../src/users.js";

const labels = Object.fromEntries(["en", "kk", "ru"].map((l) => [l, JSON.parse(readFileSync(new URL(`../../config/i18n/${l}.json`, import.meta.url)))]));
const msg = (text) => ({ text, chat: { id: 1 } });

test("onboarding walks lang -> mode -> hour -> tz and saves a valid user", () => {
  let d = startFlow("onboard");
  let out = step(d, msg("Русский"), labels, null);
  assert.equal(out.draft.step, "mode"); assert.equal(out.draft.lang, "ru");
  assert.match(out.reply, /Выберите режим/);
  out = step(out.draft, msg("Простой"), labels, null);
  assert.equal(out.draft.step, "hour"); assert.equal(out.draft.mode, "simple");
  assert.equal(keyboardFor("hour", labels, "ru").keyboard.flat().length, 24);
  out = step(out.draft, msg("08:00"), labels, null);
  assert.equal(out.draft.step, "tz"); assert.equal(out.draft.send_hour, 8);
  out = step(out.draft, msg("Алматы"), labels, null);
  assert.ok(out.user && validUser(out.user));
  assert.equal(out.user.tz, "Asia/Almaty"); assert.equal(out.user.lang, "ru"); assert.equal(out.user.mode, "simple");
  assert.match(out.reply, /Сохранено/); assert.match(out.reply, /Asia\/Almaty/);
  assert.deepEqual(out.keyboard.keyboard, [["Қазақша", "Русский"]]);   // simple mode keyboard
  assert.ok(out.user.id.startsWith("u") && out.user.created);
});

test("wrong answers repeat the same step; location and typed city both resolve", () => {
  let d = { step: "mode", flow: "onboard", lang: "en" };
  let out = step(d, msg("whatever"), labels, null);
  assert.equal(out.draft.step, "mode"); assert.match(out.reply, /Choose the mode/);
  out = step({ step: "hour", flow: "onboard", lang: "en", mode: "full" }, msg("25"), labels, null);
  assert.equal(out.draft.step, "hour");
  out = step({ step: "tz", flow: "onboard", lang: "en", mode: "full", send_hour: 6 }, msg("Nowhere City"), labels, null);
  assert.equal(out.draft.step, "tz"); assert.match(out.reply, /do not know that city/);
  out = step({ step: "tz", flow: "onboard", lang: "en", mode: "full", send_hour: 6 }, { chat: { id: 1 }, location: { latitude: 34.05, longitude: -118.24 } }, labels, null);
  assert.equal(out.user.tz, "America/Los_Angeles");
  assert.equal(tzFromCity("new york").tz, "America/New_York");
  assert.equal(tzFromCity("Москва").tz, "Europe/Moscow");
  assert.equal(tzFromCity("sing").tz, "Asia/Singapore");            // prefix match from 3 characters
  assert.equal(tzFromCity("xy"), null);
  assert.equal(tzFromLocation(51.17, 71.43), "Asia/Almaty");
});

test("settings flow edits one field and keeps the rest", () => {
  const existing = { id: "owner", chat_id: 1, mode: "full", lang: "en", tz: "America/Los_Angeles", send_hour: 12, paused: false, created: "2026-09-23T07:00:00Z" };
  assert.equal(settingsField("Send hour", labels, "en"), "hour");
  const d = { ...startFlow("settings", "hour"), lang: "en" };
  const out = step(d, msg("07:00"), labels, existing);
  assert.equal(out.user.send_hour, 7); assert.equal(out.user.tz, existing.tz); assert.equal(out.user.id, "owner");
  assert.match(out.reply, /Updated/);
  const tz = step({ ...startFlow("settings", "tz"), lang: "en" }, msg("Tokyo"), labels, existing);
  assert.equal(tz.user.tz, "Asia/Tokyo"); assert.equal(tz.user.send_hour, 12);
  const lang = step({ ...startFlow("settings", "lang"), lang: "en" }, msg("Қазақша"), labels, existing);
  assert.equal(lang.user.lang, "kk"); assert.match(lang.reply, /Жаңартылды/);
  assert.match(summary(existing, labels), /Send hour: 12:00/);
});

test("local hour follows the zone", () => {
  const d = new Date("2026-09-24T13:30:00Z");
  assert.equal(localHour("America/Los_Angeles", d), 6);
  assert.equal(localHour("Asia/Almaty", d), 18);
});
