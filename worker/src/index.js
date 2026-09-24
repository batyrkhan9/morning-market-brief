// Telegram webhook for the morning brief: self-service onboarding, settings, commands, KV queue for the build job.
import en from "../../config/i18n/en.json" with { type: "json" };
import kk from "../../config/i18n/kk.json" with { type: "json" };
import ru from "../../config/i18n/ru.json" with { type: "json" };
import { PARSERS, commandOf } from "./commands.js";
import { LANG_BUTTONS, keyboardFor, persistentKeyboard, settingsField, startFlow, step, summary, t as tl } from "./onboarding.js";
import { clearDraft, deleteUser, getDraft, getUser, listUsers, putDraft, putUser } from "./users.js";
import { dueForSend } from "./schedule.js";

const BUILD_CRONS = ["30 22,23 * * 1-5", "30 0-2 * * 2-6"];
const FINAL_ATTEMPT_UTC_HOUR = 2;   // the 02:30 UTC run builds unofficially if the close is still missing
const SEND_CRON = "*/15 * * * *";

const LABELS = { en, kk, ru };
const t = (lang, key) => tl(LABELS, lang, key);

export async function tg(env, method, payload) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
  });
  const data = await r.json();
  if (!data.ok) throw new Error(`telegram ${method}: ${data.description || r.status}`);
  return data.result;
}

async function say(env, chatId, text, keyboard) {
  const res = await tg(env, "sendMessage", { chat_id: chatId, text, parse_mode: "HTML", disable_web_page_preview: true, reply_markup: keyboard });
  return { replied: text, message_id: res.message_id };
}

async function enqueue(env, type, user, data) {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  await env.KV.put(`queue:${id}`, JSON.stringify({ id, type, user: user.id, data, ts: new Date().toISOString() }));
  return id;
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

async function bumpStat(env, field) {
  const key = `stats:${today()}`;
  const cur = JSON.parse((await env.KV.get(key)) || "{}");
  cur[field] = (cur[field] || 0) + 1;
  await env.KV.put(key, JSON.stringify(cur), { expirationTtl: 40 * 86400 });
}

async function fetchManifest(env) {
  const r = await fetch(`${env.PAGES_URL}/messages/latest/manifest.json?t=${Date.now()}`, { cf: { cacheTtl: 0 } });
  if (!r.ok) throw new Error(`manifest ${r.status}`);
  return r.json();
}

function variantOf(user) {
  return user.mode === "simple" ? `simple_${user.lang}` : "full_en";
}

// Deliver the latest edition (or the simple-mode launch note) to one user. Returns a description.
async function deliver(env, user, manifest, { force = false } = {}) {
  const lang = user.lang;
  if (user.mode === "simple" && !manifest.variants.includes(variantOf(user))) {
    const key = `soon:${user.id}`;
    if (!force && (await env.KV.get(key))) return "launch note already sent";
    await say(env, user.chat_id, t(lang, "simple_soon"), persistentKeyboard(user, LABELS, lang));
    await env.KV.put(key, manifest.edition);
    return "sent launch note";
  }
  const r = await fetch(`${env.PAGES_URL}/messages/latest/${variantOf(user)}.txt?t=${Date.now()}`, { cf: { cacheTtl: 0 } });
  if (!r.ok) throw new Error(`variant ${variantOf(user)} ${r.status}`);
  await say(env, user.chat_id, await r.text(), persistentKeyboard(user, LABELS, lang));
  if (manifest.heatmap && user.mode === "full") {
    try { await tg(env, "sendPhoto", { chat_id: user.chat_id, photo: `${env.PAGES_URL}/${manifest.heatmap}`, caption: `S&P 500 · ${manifest.edition}` }); } catch (e) { /* the text went out; the picture is optional */ }
  }
  return `sent ${variantOf(user)}`;
}

async function resendToday(env, user, lang) {
  // Language buttons: re-send today's message in the new language right away.
  try {
    const manifest = await fetchManifest(env);
    return await deliver(env, { ...user, lang }, manifest, { force: true });
  } catch (e) {
    return null;
  }
}

async function alertOwnerOnce(env, key, text) {
  // One alert per distinct error per day, so a broken night does not spam the owner every 15 minutes.
  if (!env.OWNER_CHAT_ID) return;
  const k = `alerted:${key}`;
  if (await env.KV.get(k)) return;
  await env.KV.put(k, "1", { expirationTtl: 86400 });
  try { await tg(env, "sendMessage", { chat_id: env.OWNER_CHAT_ID, text: text.slice(0, 3500) }); } catch {}
}

export async function runSend(env, now = new Date()) {
  let manifest;
  try { manifest = await fetchManifest(env); } catch (e) {
    await alertOwnerOnce(env, "manifest", `⚠️ Send cron: cannot read the latest edition manifest: ${e.message}`);
    return { error: String(e) };
  }
  const users = await listUsers(env.KV);
  const out = { edition: manifest.edition, sent: [], skipped: [], failed: [] };
  for (const user of users) {
    const sentEdition = await env.KV.get(`sent:${user.id}`);
    const { due, reason } = dueForSend(user, manifest, now, sentEdition);
    if (!due) { out.skipped.push(`${user.id}: ${reason}`); continue; }
    try {
      const what = await deliver(env, user, manifest);
      await env.KV.put(`sent:${user.id}`, manifest.edition);
      await bumpStat(env, "sends");
      out.sent.push(`${user.id}: ${what}`);
    } catch (e) {
      await bumpStat(env, "failures");
      out.failed.push(`${user.id}: ${e.message}`);
      await alertOwnerOnce(env, `send:${user.id}:${manifest.edition}`, `⚠️ Send to ${user.id} failed for ${manifest.edition}: ${e.message}`);
    }
  }
  return out;
}

export async function dispatchBuild(env, final) {
  const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/build.yml/dispatches`, {
    method: "POST",
    headers: { authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`, accept: "application/vnd.github+json", "user-agent": "morning-market-brief-bot", "content-type": "application/json" },
    body: JSON.stringify({ ref: "main", inputs: { final: final ? "true" : "false" } }),
  });
  if (r.status !== 204) {
    const body = await r.text();
    throw new Error(`dispatch ${r.status}: ${body.slice(0, 200)}`);
  }
  return { dispatched: true, final };
}

function isOwner(env, chatId) {
  return String(chatId) === String(env.OWNER_CHAT_ID || "");
}

async function handleMessage(env, msg) {
  const chatId = msg.chat.id;
  const text = (msg.text || "").trim();
  const user = await getUser(env.KV, chatId);
  const draft = await getDraft(env.KV, chatId);
  const lang = (user && user.lang) || (draft && draft.lang) || "en";
  const cmd = commandOf(text);

  // /stop and /start always win, even in the middle of a flow.
  if (cmd === "/stop") {
    if (!user) return { ignored: true };
    await deleteUser(env.KV, chatId);
    return say(env, chatId, t(lang, "stopped"), { remove_keyboard: true });
  }
  if (cmd === "/start") {
    if (user) {
      await clearDraft(env.KV, chatId);
      return say(env, chatId, t(user.lang, "bot_welcome") + "\n\n" + summary(user, LABELS), persistentKeyboard(user, LABELS, user.lang));
    }
    const d = startFlow("onboard");
    await putDraft(env.KV, chatId, d);
    const first = [en.onb_welcome, kk.onb_welcome, ru.onb_welcome].join("\n\n");
    return say(env, chatId, first, keyboardFor("lang", LABELS, "en"));
  }

  // An open onboarding or settings flow consumes the message.
  if (draft && draft.step && draft.step !== "menu") {
    const out = step(draft, msg, LABELS, user);
    if (out.user) {
      await putUser(env.KV, out.user);
      await clearDraft(env.KV, chatId);
    } else if (out.draft) {
      await putDraft(env.KV, chatId, out.draft);
    }
    const res = await say(env, chatId, out.reply, out.keyboard);
    if (out.user && user && out.user.lang !== user.lang) await resendToday(env, out.user, out.user.lang);
    return res;
  }
  if (draft && draft.step === "menu") {
    if (text === t(lang, "btn_cancel")) {
      await clearDraft(env.KV, chatId);
      return say(env, chatId, t(lang, "settings_cancelled"), persistentKeyboard(user, LABELS, lang));
    }
    const field = settingsField(text, LABELS, lang);
    if (field) {
      const d = { ...startFlow("settings", field), lang: user.lang };
      await putDraft(env.KV, chatId, d);
      return say(env, chatId, t(lang, "onb_" + field), keyboardFor(field, LABELS, lang));
    }
    return say(env, chatId, t(lang, "settings_menu"), keyboardFor("settings", LABELS, lang));
  }

  if (!user) {
    // Strangers get nothing. Remember at most MAX_SEEN chat ids for a week so the owner can see who knocked.
    const key = `seen:${chatId}`;
    if ((await env.KV.get(key)) || (await env.KV.list({ prefix: "seen:", limit: MAX_SEEN })).keys.length < MAX_SEEN) {
      await env.KV.put(key, JSON.stringify({ chat_id: chatId, name: msg.chat.first_name || "", username: msg.chat.username || "", ts: new Date().toISOString() }), { expirationTtl: SEEN_TTL_SECONDS });
    }
    return { ignored: true };
  }

  if (cmd === "/settings") {
    await putDraft(env.KV, chatId, { step: "menu", flow: "settings", lang: user.lang });
    return say(env, chatId, t(lang, "settings_menu"), keyboardFor("settings", LABELS, lang));
  }
  if (cmd === "/pause" || cmd === "/resume") {
    user.paused = cmd === "/pause";
    await putUser(env.KV, user);
    return say(env, chatId, t(lang, cmd === "/pause" ? "paused" : "resumed"), persistentKeyboard(user, LABELS, lang));
  }
  if (cmd === "/stats") {
    if (!isOwner(env, chatId)) return say(env, chatId, t(lang, "owner_only"), persistentKeyboard(user, LABELS, lang));
    const users = await listUsers(env.KV);
    const s = JSON.parse((await env.KV.get(`stats:${today()}`)) || "{}");
    const text2 = en.stats.replace("{users}", users.length).replace("{full}", users.filter((u) => u.mode === "full").length)
      .replace("{simple}", users.filter((u) => u.mode === "simple").length).replace("{paused}", users.filter((u) => u.paused).length)
      .replace("{sends}", s.sends || 0).replace("{failures}", s.failures || 0);
    return say(env, chatId, text2, persistentKeyboard(user, LABELS, lang));
  }
  if (LANG_BUTTONS[text]) {
    const newLang = LANG_BUTTONS[text];
    user.lang = newLang;
    await putUser(env.KV, user);
    await say(env, chatId, t(newLang, "bot_lang_set"), persistentKeyboard(user, LABELS, newLang));
    const sent = await resendToday(env, user, newLang);
    return { replied: t(newLang, "bot_lang_set"), resent: Boolean(sent) };
  }
  if (cmd && PARSERS[cmd]) {
    if (user.mode === "simple") return say(env, chatId, t(lang, "bot_soon"), persistentKeyboard(user, LABELS, lang));
    const parsed = PARSERS[cmd](text, today());
    if (!parsed.ok) {
      return say(env, chatId, `${t(lang, "bot_" + cmd.slice(1) + "_bad")}\n${t(lang, "bot_error_" + parsed.error)}\n\n${t(lang, "bot_" + cmd.slice(1) + "_usage")}`, persistentKeyboard(user, LABELS, lang));
    }
    const id = await enqueue(env, cmd.slice(1), user, parsed.data);
    const d = parsed.data;
    const sum = cmd === "/predict" ? `${d.ticker} ${d.direction} ${d.level} by ${d.by}` : cmd === "/thesis" ? `${d.ticker} (${d.text.length} chars)` : d.ticker;
    return say(env, chatId, `${t(lang, "bot_" + cmd.slice(1) + "_ok")} ${sum}\n<i>${t(lang, "bot_queued")} ${id}</i>`, persistentKeyboard(user, LABELS, lang));
  }
  if (cmd) return say(env, chatId, t(lang, "bot_unknown_command"), persistentKeyboard(user, LABELS, lang));
  if (user.mode === "simple") {
    if (env.OWNER_CHAT_ID && !isOwner(env, chatId)) {
      try { await tg(env, "sendMessage", { chat_id: env.OWNER_CHAT_ID, text: `[${user.id}] ${text}` }); } catch {}
    }
    return say(env, chatId, t(lang, "bot_soon"), persistentKeyboard(user, LABELS, lang));
  }
  return say(env, chatId, t(lang, "bot_unknown_text"), persistentKeyboard(user, LABELS, lang));
}

const MAX_SEEN = 20;
const SEEN_TTL_SECONDS = 7 * 86400;

function authorized(request, env) {
  return (request.headers.get("authorization") || "") === `Bearer ${env.WORKER_SHARED_SECRET}`;
}

export default {
  async scheduled(event, env, ctx) {
    if (event.cron === SEND_CRON) {
      const res = await runSend(env, new Date(event.scheduledTime));
      console.log(JSON.stringify({ send: res }));
      return;
    }
    if (BUILD_CRONS.includes(event.cron)) {
      const final = new Date(event.scheduledTime).getUTCHours() === FINAL_ATTEMPT_UTC_HOUR;
      try {
        const res = await dispatchBuild(env, final);
        console.log(JSON.stringify({ build: res, cron: event.cron }));
      } catch (e) {
        console.log(JSON.stringify({ build_error: String(e), cron: event.cron }));
        await alertOwnerOnce(env, `dispatch:${new Date(event.scheduledTime).toISOString().slice(0, 13)}`, `❌ Build dispatch failed (${event.cron} UTC): ${e.message}`);
      }
    }
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/webhook") {
      if (request.headers.get("x-telegram-bot-api-secret-token") !== env.WORKER_SHARED_SECRET) return new Response("forbidden", { status: 403 });
      let update;
      try { update = await request.json(); } catch { return new Response("bad json", { status: 400 }); }
      const msg = update.message || update.edited_message;
      let result = { ignored: true };
      if (msg && msg.chat) {
        try { result = await handleMessage(env, msg); } catch (e) { result = { error: String(e) }; }
      }
      return Response.json(result);
    }
    if (url.pathname === "/health") return Response.json({ ok: true });
    if (!authorized(request, env)) return new Response("forbidden", { status: 403 });
    if (url.pathname === "/run-send" && request.method === "POST") {
      return Response.json(await runSend(env));
    }
    if (url.pathname === "/dispatch-build" && request.method === "POST") {
      try { return Response.json(await dispatchBuild(env, url.searchParams.get("final") === "1")); } catch (e) { return Response.json({ error: String(e) }, { status: 502 }); }
    }
    if (url.pathname === "/users" && request.method === "GET") {
      return Response.json({ users: await listUsers(env.KV) });
    }
    if (url.pathname === "/report" && request.method === "POST") {
      const { ok } = await request.json();
      await bumpStat(env, ok ? "sends" : "failures");
      return Response.json({ ok: true });
    }
    if (url.pathname === "/pull" && request.method === "GET") {
      const items = [];
      for (const k of (await env.KV.list({ prefix: "queue:" })).keys) {
        const v = await env.KV.get(k.name);
        if (v) items.push(JSON.parse(v));
      }
      const seen = [];
      for (const k of (await env.KV.list({ prefix: "seen:" })).keys) {
        const v = await env.KV.get(k.name);
        if (v) seen.push(JSON.parse(v));
      }
      return Response.json({ items, seen });
    }
    if (url.pathname === "/ack" && request.method === "POST") {
      const { ids } = await request.json();
      for (const id of ids || []) await env.KV.delete(`queue:${id}`);
      return Response.json({ deleted: (ids || []).length });
    }
    return new Response("not found", { status: 404 });
  },
};
