import test from "node:test";
import assert from "node:assert/strict";
import { parsePredict, parseThesis, parseQueue, commandOf } from "../src/commands.js";

const today = "2026-09-22";

test("predict: good input", () => {
  const r = parsePredict("/predict NKE above 40 by 2026-12-31 because the turnaround is priced too low", today);
  assert.equal(r.ok, true);
  assert.deepEqual(r.data, { ticker: "NKE", direction: "above", level: 40, by: "2026-12-31", reason: "the turnaround is priced too low" });
});

test("predict: snapshot items and decimal comma", () => {
  assert.equal(parsePredict("/predict us10y below 4,5 by 2027-01-15 because growth slows", today).data.level, 4.5);
  assert.equal(parsePredict("/predict spx above 8000 by 2027-06-30 because earnings", today).data.ticker, "SPX");
});

test("predict: bad inputs", () => {
  assert.equal(parsePredict("/predict NKE up 40 by 2026-12-31 because reasons", today).error, "format");
  assert.equal(parsePredict("/predict NKE above 40 by 2026-12-31", today).error, "format");
  assert.equal(parsePredict("/predict NKE above 40 by 2026-02-30 because leap", today).error, "date");
  assert.equal(parsePredict("/predict NKE above 40 by 2026-09-01 because past", today).error, "date");
  assert.equal(parsePredict("/predict nike! above 40 by 2026-12-31 because reasons", today).error, "ticker");
  assert.equal(parsePredict("/predict NKE above 0 by 2026-12-31 because reasons", today).error, "level");
});

test("thesis and queue", () => {
  assert.equal(parseThesis("/thesis NKE Nike lost the run-of-the-mill customer. Bull: margins. Bear: China.").ok, true);
  assert.equal(parseThesis("/thesis NKE short").error, "format");
  assert.deepEqual(parseQueue("/queue zts").data, { ticker: "ZTS" });
  assert.equal(parseQueue("/queue two words").error, "format");
  assert.equal(commandOf("/Predict x"), "/predict");
  assert.equal(commandOf("hello"), null);
});
