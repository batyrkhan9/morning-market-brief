// Onboarding and settings state machine. Pure decisions: given the stored draft and the incoming text,
// return what to reply and what to store. index.js does the I/O.
import { COMMON_CITIES, tzFromCity, tzFromLocation } from "./tz.js";
import { LANGS, MODES, newId, validUser } from "./users.js";

export const LANG_BUTTONS = { "English": "en", "Қазақша": "kk", "Русский": "ru" };
export const STEPS = ["lang", "mode", "hour", "tz", "done"];

export function t(labels, lang, key) {
  return (labels[lang] && labels[lang][key]) || labels.en[key] || key;
}

export function keyboardFor(step, labels, lang) {
  if (step === "lang") return { keyboard: [Object.keys(LANG_BUTTONS)], resize_keyboard: true, one_time_keyboard: true };
  if (step === "mode") return { keyboard: [[t(labels, lang, "btn_mode_full"), t(labels, lang, "btn_mode_simple")]], resize_keyboard: true, one_time_keyboard: true };
  if (step === "hour") {
    const rows = [];
    for (let r = 0; r < 4; r++) rows.push([0, 1, 2, 3, 4, 5].map((c) => String(r * 6 + c).padStart(2, "0") + ":00"));
    return { keyboard: rows, resize_keyboard: true, one_time_keyboard: true };
  }
  if (step === "tz") {
    const rows = [[{ text: t(labels, lang, "btn_share_location"), request_location: true }]];
    for (let i = 0; i < COMMON_CITIES.length; i += 3) rows.push(COMMON_CITIES.slice(i, i + 3));
    return { keyboard: rows, resize_keyboard: true, one_time_keyboard: true };
  }
  if (step === "settings") {
    return { keyboard: [[t(labels, lang, "btn_set_lang"), t(labels, lang, "btn_set_mode")], [t(labels, lang, "btn_set_hour"), t(labels, lang, "btn_set_tz")], [t(labels, lang, "btn_cancel")]], resize_keyboard: true, one_time_keyboard: true };
  }
  return persistentKeyboard(null, labels, lang);
}

export function persistentKeyboard(user, labels, lang) {
  const rows = user && user.mode === "simple" ? [["Қазақша", "Русский"]] : [Object.keys(LANG_BUTTONS)];
  return { keyboard: rows, resize_keyboard: true, is_persistent: true };
}

export function summary(user, labels) {
  const lang = user.lang;
  return [t(labels, lang, "onb_summary"),
    `${t(labels, lang, "lbl_language")}: ${Object.keys(LANG_BUTTONS).find((k) => LANG_BUTTONS[k] === user.lang)}`,
    `${t(labels, lang, "lbl_mode")}: ${t(labels, lang, "btn_mode_" + user.mode)}`,
    `${t(labels, lang, "lbl_send_hour")}: ${String(user.send_hour).padStart(2, "0")}:00`,
    `${t(labels, lang, "lbl_timezone")}: ${user.tz}`,
    user.paused ? t(labels, lang, "lbl_paused") : ""].filter(Boolean).join("\n");
}

function prompt(step, labels, lang) {
  if (step === "lang") return [labels.en.onb_welcome, labels.kk.onb_welcome, labels.ru.onb_welcome].join("\n\n");
  return t(labels, lang, "onb_" + step);
}

// Returns { reply, keyboard, draft (to store or null), user (to save or null), deleteDraft }
export function step(draft, msg, labels, existing) {
  const text = (msg.text || "").trim();
  const lang = draft.lang || (existing && existing.lang) || "en";
  const cur = draft.step;
  draft.chat_id = msg.chat.id;
  if (cur === "lang") {
    const chosen = LANG_BUTTONS[text];
    if (!chosen) return { reply: prompt("lang", labels, lang), keyboard: keyboardFor("lang", labels, lang), draft };
    draft.lang = chosen;
    return advance(draft, labels, "mode", existing);
  }
  if (cur === "mode") {
    const mode = MODES.find((m) => text === t(labels, lang, "btn_mode_" + m)) || MODES.find((m) => text.toLowerCase() === m);
    if (!mode) return { reply: prompt("mode", labels, lang), keyboard: keyboardFor("mode", labels, lang), draft };
    draft.mode = mode;
    return advance(draft, labels, "hour", existing);
  }
  if (cur === "hour") {
    const m = text.match(/^(\d{1,2})(?::00)?$/);
    const h = m ? parseInt(m[1], 10) : NaN;
    if (!(h >= 0 && h <= 23)) return { reply: prompt("hour", labels, lang), keyboard: keyboardFor("hour", labels, lang), draft };
    draft.send_hour = h;
    return advance(draft, labels, "tz", existing);
  }
  if (cur === "tz") {
    let tz = null, city = null;
    if (msg.location) {
      tz = tzFromLocation(msg.location.latitude, msg.location.longitude);
    } else {
      const hit = tzFromCity(text);
      if (hit) { tz = hit.tz; city = hit.city; }
    }
    if (!tz) return { reply: t(labels, lang, "onb_tz_unknown") + "\n\n" + prompt("tz", labels, lang), keyboard: keyboardFor("tz", labels, lang), draft };
    draft.tz = tz;
    draft.city = city;
    return advance(draft, labels, "done", existing);
  }
  return { reply: prompt("lang", labels, lang), keyboard: keyboardFor("lang", labels, lang), draft: { step: "lang", flow: draft.flow } };
}

function advance(draft, labels, next, existing) {
  // In the settings flow only the chosen field is edited, so jump straight to done.
  if (draft.flow === "settings") next = "done";
  if (next !== "done") {
    draft.step = next;
    return { reply: prompt(next, labels, draft.lang), keyboard: keyboardFor(next, labels, draft.lang), draft };
  }
  const base = existing || { id: newId(), chat_id: draft.chat_id, created: new Date().toISOString(), paused: false };
  const user = { ...base, lang: draft.lang ?? base.lang, mode: draft.mode ?? base.mode, send_hour: draft.send_hour ?? base.send_hour,
    tz: draft.tz ?? base.tz, city: draft.city ?? base.city ?? null, updated: new Date().toISOString() };
  if (!validUser(user)) {
    return { reply: prompt("lang", labels, user.lang || "en"), keyboard: keyboardFor("lang", labels, "en"), draft: { step: "lang", flow: draft.flow } };
  }
  const reply = (existing ? t(labels, user.lang, "onb_updated") : t(labels, user.lang, "onb_saved")) + "\n\n" + summary(user, labels);
  return { reply, keyboard: persistentKeyboard(user, labels, user.lang), draft: null, user, deleteDraft: true };
}

export function startFlow(flow, field) {
  // flow "onboard": lang -> mode -> hour -> tz; flow "settings": just one field.
  if (flow === "settings") return { step: field, flow: "settings" };
  return { step: "lang", flow: "onboard" };
}

export function settingsField(text, labels, lang) {
  const map = { btn_set_lang: "lang", btn_set_mode: "mode", btn_set_hour: "hour", btn_set_tz: "tz" };
  for (const [key, field] of Object.entries(map)) if (text === t(labels, lang, key)) return field;
  return null;
}
