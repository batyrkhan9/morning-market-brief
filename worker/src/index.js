// Telegram webhook for the morning brief. Known chat IDs only. Instant confirmations, KV queue for the build job.
import en from "../../config/i18n/en.json";
import kk from "../../config/i18n/kk.json";
import ru from "../../config/i18n/ru.json";
import { PARSERS, commandOf } from "./commands.js";

const LABELS = { en, kk, ru };
const LANG_BUTTONS = { "English": "en", "Қазақша": "kk", "Русский": "ru" };
const MAX_SEEN = 20;               // unknown chat ids remembered at most
const SEEN_TTL_SECONDS = 7 * 86400; // and only for a week

function t(lang, key) {
  return (LABELS[lang] && LABELS[lang][key]) || LABELS.en[key] || key;
}

function keyboard(user) {
  const rows = user.mode === "simple" ? [["Қазақша", "Русский"]] : [["English", "Қазақша", "Русский"]];
  return { keyboard: rows, resize_keyboard: true, is_persistent: true };
}

async function tg(env, method, payload) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
  });
  return r.json();
}

function users(env) {
  try { return JSON.parse(env.USERS || "[]"); } catch { return []; }
}

async function currentLang(env, user) {
  return (await env.KV.get(`lang:${user.id}`)) || user.default_language || "en";
}

async function enqueue(env, type, user, data) {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  await env.KV.put(`queue:${id}`, JSON.stringify({ id, type, user: user.id, data, ts: new Date().toISOString() }));
  return id;
}

async function resendToday(env, user, lang) {
  const mode = user.mode === "simple" ? "simple" : "full";
  const r = await fetch(`${env.PAGES_URL}/messages/latest/${mode}_${lang}.txt`, { cf: { cacheTtl: 60 } });
  if (!r.ok) return null;
  const text = await r.text();
  await tg(env, "sendMessage", { chat_id: user.chat_id, text, parse_mode: "HTML", disable_web_page_preview: true, reply_markup: keyboard(user) });
  return text;
}

async function handleMessage(env, msg) {
  const user = users(env).find((u) => u.chat_id === msg.chat.id);
  if (!user) {
    // No reply to strangers. Remember at most MAX_SEEN chat ids for 7 days so the owner can onboard someone via /pull.
    const key = `seen:${msg.chat.id}`;
    const existing = await env.KV.get(key);
    if (existing || (await env.KV.list({ prefix: "seen:", limit: MAX_SEEN })).keys.length < MAX_SEEN) {
      await env.KV.put(key, JSON.stringify({ chat_id: msg.chat.id, name: msg.chat.first_name || "", username: msg.chat.username || "", ts: new Date().toISOString() }), { expirationTtl: SEEN_TTL_SECONDS });
    }
    return { ignored: true };
  }
  const text = (msg.text || "").trim();
  const lang = await currentLang(env, user);
  const reply = async (body, extra = {}) => {
    await tg(env, "sendMessage", { chat_id: user.chat_id, text: body, parse_mode: "HTML", disable_web_page_preview: true, reply_markup: keyboard(user), ...extra });
    return { replied: body };
  };

  if (text === "/start") {
    return reply(t(lang, "bot_welcome"));
  }
  if (LANG_BUTTONS[text]) {
    const newLang = LANG_BUTTONS[text];
    if (!(user.languages || ["en"]).includes(newLang)) return reply(t(lang, "bot_lang_unavailable"));
    await env.KV.put(`lang:${user.id}`, newLang);
    await tg(env, "sendMessage", { chat_id: user.chat_id, text: t(newLang, "bot_lang_set"), reply_markup: keyboard(user) });
    const sent = await resendToday(env, user, newLang);
    return { replied: t(newLang, "bot_lang_set"), resent: Boolean(sent) };
  }
  const cmd = commandOf(text);
  if (cmd && PARSERS[cmd]) {
    if (user.mode === "simple") return reply(t(lang, "bot_soon"));
    const today = new Date().toISOString().slice(0, 10);
    const parsed = PARSERS[cmd](text, today);
    if (!parsed.ok) {
      return reply(`${t(lang, "bot_" + cmd.slice(1) + "_bad")}\n${t(lang, "bot_error_" + parsed.error)}\n\n${t(lang, "bot_" + cmd.slice(1) + "_usage")}`);
    }
    const id = await enqueue(env, cmd.slice(1), user, parsed.data);
    const d = parsed.data;
    const summary = cmd === "/predict" ? `${d.ticker} ${d.direction} ${d.level} by ${d.by}` : cmd === "/thesis" ? `${d.ticker} (${d.text.length} chars)` : d.ticker;
    return reply(`${t(lang, "bot_" + cmd.slice(1) + "_ok")} ${summary}\n<i>${t(lang, "bot_queued")} ${id}</i>`);
  }
  if (cmd) return reply(t(lang, "bot_unknown_command"));
  if (user.mode === "simple") {
    const owner = users(env).find((u) => u.is_owner);
    if (owner && user.mirror_to_owner !== false) {
      await tg(env, "sendMessage", { chat_id: owner.chat_id, text: `[${user.id}] ${text}` });
    }
    return reply(t(lang, "bot_soon"));
  }
  return reply(t(lang, "bot_unknown_text"));
}

function authorized(request, env) {
  const auth = request.headers.get("authorization") || "";
  return auth === `Bearer ${env.WORKER_SHARED_SECRET}`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/webhook") {
      if (request.headers.get("x-telegram-bot-api-secret-token") !== env.WORKER_SHARED_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
      let update;
      try { update = await request.json(); } catch { return new Response("bad json", { status: 400 }); }
      const msg = update.message || update.edited_message;
      let result = { ignored: true };
      if (msg && msg.chat) {
        try { result = await handleMessage(env, msg); } catch (e) { result = { error: String(e) }; }
      }
      return Response.json(result);
    }
    if (url.pathname === "/pull" && request.method === "GET") {
      if (!authorized(request, env)) return new Response("forbidden", { status: 403 });
      const list = await env.KV.list({ prefix: "queue:" });
      const items = [];
      for (const k of list.keys) {
        const v = await env.KV.get(k.name);
        if (v) items.push(JSON.parse(v));
      }
      const languages = {};
      for (const u of users(env)) {
        const l = await env.KV.get(`lang:${u.id}`);
        if (l) languages[u.id] = l;
      }
      const seen = [];
      for (const k of (await env.KV.list({ prefix: "seen:" })).keys) {
        const v = await env.KV.get(k.name);
        if (v) seen.push(JSON.parse(v));
      }
      return Response.json({ items, languages, seen });
    }
    if (url.pathname === "/ack" && request.method === "POST") {
      if (!authorized(request, env)) return new Response("forbidden", { status: 403 });
      const { ids } = await request.json();
      for (const id of ids || []) await env.KV.delete(`queue:${id}`);
      return Response.json({ deleted: (ids || []).length });
    }
    if (url.pathname === "/health") return Response.json({ ok: true });
    return new Response("not found", { status: 404 });
  },
};
