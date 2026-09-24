// User store in Workers KV. One record per chat: user:{chat_id}. Onboarding drafts: onboard:{chat_id}.

export const MODES = ["full", "simple"];
export const LANGS = ["en", "kk", "ru"];

export function newId() {
  return "u" + Math.random().toString(36).slice(2, 8);
}

export async function getUser(kv, chatId) {
  const v = await kv.get(`user:${chatId}`);
  return v ? JSON.parse(v) : null;
}

export async function putUser(kv, user) {
  await kv.put(`user:${user.chat_id}`, JSON.stringify(user));
  return user;
}

export async function deleteUser(kv, chatId) {
  await kv.delete(`user:${chatId}`);
  await kv.delete(`onboard:${chatId}`);
}

export async function listUsers(kv) {
  const out = [];
  let cursor;
  do {
    const page = await kv.list({ prefix: "user:", cursor });
    for (const k of page.keys) {
      const v = await kv.get(k.name);
      if (v) out.push(JSON.parse(v));
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return out.sort((a, b) => (a.created || "").localeCompare(b.created || ""));
}

export async function getDraft(kv, chatId) {
  const v = await kv.get(`onboard:${chatId}`);
  return v ? JSON.parse(v) : null;
}

export async function putDraft(kv, chatId, draft) {
  await kv.put(`onboard:${chatId}`, JSON.stringify(draft), { expirationTtl: 86400 });
}

export async function clearDraft(kv, chatId) {
  await kv.delete(`onboard:${chatId}`);
}

export function validUser(u) {
  return u && MODES.includes(u.mode) && LANGS.includes(u.lang) && typeof u.tz === "string" && u.tz.includes("/")
    && Number.isInteger(u.send_hour) && u.send_hour >= 0 && u.send_hour <= 23;
}
