"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const handler = require("./handler");

async function invoke(body, method = "POST") {
    const result = { calls: 0 };
    const context = {
        status(code) { result.status = code; return this; },
        headers(values) { result.headers = values; return this; },
        succeed(value) { result.body = value; result.calls++; },
        fail() { assert.fail("Do not use context.fail for JSON responses"); }
    };
    await handler({ method, body }, context);
    assert.equal(result.calls, 1);
    assert.equal(result.headers["Content-Type"], "application/json");
    return result;
}

for (const [label, input, name] of [
    ["valid name", "Ada", "Ada"],
    ["trimmed name", "  Ada  ", "Ada"],
    ["80-character name", "a".repeat(80), "a".repeat(80)]
]) {
    test(label, async () => {
        const result = await invoke({ name: input });
        assert.equal(result.status, 200);
        assert.deepEqual(result.body, {
            message: `Hello ${name}, your function is live!`
        });
    });
}

for (const [label, body] of [
    ["missing body", undefined],
    ["null body", null],
    ["text body", "Ada"],
    ["array body", []],
    ["numeric body", 42]
]) {
    test(label + " is rejected", async () => {
        const result = await invoke(body);
        assert.equal(result.status, 400);
        assert.deepEqual(result.body, { error: "expected_json_object" });
    });
}

for (const [label, body] of [
    ["missing name", {}],
    ["null name", { name: null }],
    ["numeric name", { name: 42 }],
    ["empty name", { name: "" }],
    ["whitespace-only name", { name: "   " }],
    ["overlong name", { name: "a".repeat(81) }]
]) {
    test(label + " is rejected", async () => {
        const result = await invoke(body);
        assert.equal(result.status, 400);
        assert.deepEqual(result.body, { error: "invalid_name" });
    });
}

test("GET is rejected with an Allow header", async () => {
    const result = await invoke({ name: "Ada" }, "GET");
    assert.equal(result.status, 405);
    assert.equal(result.headers.Allow, "POST");
    assert.deepEqual(result.body, { error: "method_not_allowed" });
});
