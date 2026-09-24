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
    if (String(url).includes("manifest.json")) return { ok: true, json: async () => ({ edition: "2026-09-23", built_at: "2026-09-24T00:47:00Z", variants: ["full_en"] }) };
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

test("send cron delivers due users once and marks them; dispatch posts to GitHub", async () => {
  const { env, sent } = setup();
  const calls = [];
  globalThis.fetch = async (url, opts) => {
    const u = String(url);
    if (u.includes("api.telegram.org")) { sent.push(JSON.parse(opts.body)); return { json: async () => ({ ok: true, result: { message_id: sent.length } }) }; }
    if (u.includes("manifest.json")) return { ok: true, json: async () => ({ edition: "2026-09-23", built_at: "2026-09-24T00:47:00Z", variants: ["full_en"], heatmap: "en/heatmap.png?v=2026-09-23" }) };
    if (u.includes("full_en.txt")) return { ok: true, text: async () => "BRIEF 2026-09-23" };
    if (u.includes("api.github.com")) { calls.push({ url: u, body: JSON.parse(opts.body), auth: opts.headers.authorization }); return { status: 204, text: async () => "" }; }
    return { ok: false, status: 404, text: async () => "" };
  };
  env.GH_DISPATCH_TOKEN = "ghp_test"; env.GITHUB_REPO = "o/r";
  await env.KV.put("user:1", JSON.stringify({ id: "owner", chat_id: 1, mode: "full", lang: "en", tz: "America/Los_Angeles", send_hour: 12, paused: false, created: "2026-09-23T07:00:00Z" }));
  await env.KV.put("user:5", JSON.stringify({ id: "uabc", chat_id: 5, mode: "simple", lang: "kk", tz: "Asia/Almaty", send_hour: 8, paused: false, created: "2026-09-01T00:00:00Z" }));
  const { runSend, dispatchBuild } = await import("../src/index.js");
  let res = await runSend(env, new Date("2026-09-24T03:05:00Z"));            // 08:05 Almaty; 20:05 PDT the day before (owner waits)
  assert.deepEqual(res.sent, ["uabc: sent launch note"]);
  assert.ok(res.skipped.some((s) => s.startsWith("owner: edition built after today's slot")));
  res = await runSend(env, new Date("2026-09-24T19:05:00Z"));                // 12:05 PDT
  assert.deepEqual(res.sent, ["owner: sent full_en"]);
  assert.equal(sent.filter((m) => m.text === "BRIEF 2026-09-23").length, 1);
  assert.equal(sent.filter((m) => m.photo).length, 1);
  res = await runSend(env, new Date("2026-09-24T19:20:00Z"));                // 15 minutes later: nothing repeats
  assert.deepEqual(res.sent, []);
  assert.ok(res.skipped.some((s) => s.startsWith("owner: already sent")));
  const d = await dispatchBuild(env, true);
  assert.equal(d.dispatched, true);
  assert.equal(calls[0].url, "https://api.github.com/repos/o/r/actions/workflows/build.yml/dispatches");
  assert.equal(calls[0].body.inputs.final, "true"); assert.equal(calls[0].auth, "Bearer ghp_test");
});

test("dispatch failure alerts the owner once per hour slot", async () => {
  const { env, sent } = setup();
  globalThis.fetch = async (url, opts) => {
    if (String(url).includes("api.telegram.org")) { sent.push(JSON.parse(opts.body)); return { json: async () => ({ ok: true, result: { message_id: 1 } }) }; }
    return { status: 401, text: async () => "Bad credentials" };
  };
  env.GH_DISPATCH_TOKEN = "bad"; env.GITHUB_REPO = "o/r";
  const ev = { cron: "30 22,23 * * 1-5", scheduledTime: Date.parse("2026-09-24T22:30:00Z") };
  await worker.scheduled(ev, env, {});
  await worker.scheduled(ev, env, {});
  const alerts = sent.filter((m) => /Build dispatch failed/.test(m.text));
  assert.equal(alerts.length, 1); assert.equal(alerts[0].chat_id, "1");
  // the 02:30 slot is the final attempt
  const calls = [];
  globalThis.fetch = async (url, opts) => {
    if (String(url).includes("api.telegram.org")) return { json: async () => ({ ok: true, result: {} }) };
    calls.push(JSON.parse(opts.body)); return { status: 204, text: async () => "" };
  };
  await worker.scheduled({ cron: "30 0-2 * * 2-6", scheduledTime: Date.parse("2026-09-25T02:30:00Z") }, env, {});
  await worker.scheduled({ cron: "30 0-2 * * 2-6", scheduledTime: Date.parse("2026-09-25T01:30:00Z") }, env, {});
  assert.deepEqual(calls.map((c) => c.inputs.final), ["true", "false"]);
});
