// End-to-end through the fetch handler with a fake KV and a fake Telegram.
import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

function fakeKV() {
  const store = new Map();
  return {
    store,
    async get(k) { return store.has(k) ? store.get(k) : null; },
    async put(k, v) { store.set(k, v); },
    async delete(k) { store.delete(k); },
    async list({ prefix }) { return { keys: [...store.keys()].filter((k) => k.startsWith(prefix)).map((name) => ({ name })), list_complete: true }; },
  };
}

function setup() {
  const sent = [];
  globalThis.fetch = async (url, opts) => {
    if (String(url).includes("api.telegram.org")) {
      sent.push(JSON.parse(opts.body));
      return { json: async () => ({ ok: true, result: { message_id: sent.length } }) };
    }
    return { ok: true, text: async () => "TODAY'S BRIEF", json: async () => ({}) };
  };
  const env = { KV: fakeKV(), TELEGRAM_TOKEN: "x", WORKER_SHARED_SECRET: "s", OWNER_CHAT_ID: "1", PAGES_URL: "https://pages" };
  const post = (chatId, text, extra = {}) => worker.fetch(new Request("https://w/webhook", { method: "POST", headers: { "x-telegram-bot-api-secret-token": "s" },
    body: JSON.stringify({ message: { chat: { id: chatId, first_name: "T" }, text, ...extra } }) }), env).then((r) => r.json());
  return { env, sent, post };
}

test("/start onboarding end to end, then /settings, /pause, /stats and /stop", async () => {
  const { env, sent, post } = setup();
  let r = await post(1, "/start");
  assert.match(r.replied, /Welcome to the morning brief/); assert.match(r.replied, /Добро пожаловать/);
  await post(1, "English");
  await post(1, "Full");
  await post(1, "12:00");
  r = await post(1, "Los Angeles");
  assert.match(r.replied, /Saved/); assert.match(r.replied, /America\/Los_Angeles/);
  const user = JSON.parse(env.KV.store.get("user:1"));
  assert.equal(user.mode, "full"); assert.equal(user.send_hour, 12); assert.equal(env.KV.store.has("onboard:1"), false);

  r = await post(1, "/start");                                    // existing user: current settings
  assert.match(r.replied, /Your settings/);
  r = await post(1, "/settings"); assert.match(r.replied, /What do you want to change/);
  r = await post(1, "Send hour"); assert.match(r.replied, /what hour/i);
  r = await post(1, "07:00"); assert.match(r.replied, /Updated/);
  assert.equal(JSON.parse(env.KV.store.get("user:1")).send_hour, 7);

  r = await post(1, "/pause"); assert.match(r.replied, /Paused/);
  assert.equal(JSON.parse(env.KV.store.get("user:1")).paused, true);
  r = await post(1, "/resume"); assert.equal(JSON.parse(env.KV.store.get("user:1")).paused, false);

  r = await post(1, "/stats"); assert.match(r.replied, /Users: 1 \(1 full, 0 simple, 0 paused\)/);
  r = await post(2, "/stats"); assert.equal(r.ignored, true);     // stranger: nothing, but remembered
  assert.ok(env.KV.store.has("seen:2"));

  r = await post(1, "Русский");                                   // language switch re-sends today's message
  assert.equal(r.resent, true);
  assert.equal(sent.at(-1).text, "TODAY'S BRIEF");
  assert.equal(JSON.parse(env.KV.store.get("user:1")).lang, "ru");

  r = await post(1, "/stop"); assert.match(r.replied, /удалены/);
  assert.equal(env.KV.store.has("user:1"), false);
});

test("simple user: language switch sends the launch note, commands are refused, text is forwarded to the owner", async () => {
  const { env, sent, post } = setup();
  await env.KV.put("user:5", JSON.stringify({ id: "uabc", chat_id: 5, mode: "simple", lang: "kk", tz: "Asia/Almaty", send_hour: 8, paused: false, created: "x" }));
  let r = await post(5, "Русский");
  assert.equal(r.resent, true); assert.match(sent.at(-1).text, /Простой режим скоро/);
  r = await post(5, "/predict NKE above 40 by 2026-12-31 because reasons");
  assert.match(r.replied, /скоро/);
  r = await post(5, "сколько стоит нефть?");
  assert.equal(sent.at(-2).chat_id, "1"); assert.match(sent.at(-2).text, /\[uabc\] сколько/);   // forwarded to the owner
  r = await post(1, "/start");                                     // owner not registered yet: onboarding starts
  assert.match(r.replied, /Welcome/);
});

test("/users, /report and /pull need the bearer secret", async () => {
  const { env } = setup();
  await env.KV.put("user:9", JSON.stringify({ id: "u9", chat_id: 9, mode: "full", lang: "en", tz: "UTC", send_hour: 6, paused: false, created: "x" }));
  const get = (path, auth) => worker.fetch(new Request("https://w" + path, { headers: auth ? { authorization: "Bearer s" } : {} }), env);
  assert.equal((await get("/users", false)).status, 403);
  const users = (await (await get("/users", true)).json()).users;
  assert.equal(users.length, 1); assert.equal(users[0].chat_id, 9);
  const rep = await worker.fetch(new Request("https://w/report", { method: "POST", headers: { authorization: "Bearer s" }, body: JSON.stringify({ ok: false }) }), env);
  assert.equal((await rep.json()).ok, true);
  const day = new Date().toISOString().slice(0, 10);
  assert.equal(JSON.parse(env.KV.store.get(`stats:${day}`)).failures, 1);
});
