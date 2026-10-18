"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const handler = require("./handler");
const fixture = require("../../fixtures/weather-sample.json");

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

test("synthetic fixture produces the expected summary", async () => {
    const result = await invoke(fixture);
    assert.equal(result.status, 200);
    assert.deepEqual(result.body, {
        city: "Amsterdam",
        temperature_c: 12.5,
        condition: "Cloudy",
        message: "Weather in Amsterdam: 12.5°C, Cloudy."
    });
});

test("text is trimmed without mutating the input", async () => {
    const body = Object.freeze({
        city: "  Amsterdam  ",
        temperature_c: 12.5,
        condition: "  Cloudy  "
    });
    const result = await invoke(body);
    assert.equal(result.status, 200);
    assert.equal(result.body.city, "Amsterdam");
    assert.equal(result.body.condition, "Cloudy");
    assert.equal(body.city, "  Amsterdam  ");
    assert.equal(body.condition, "  Cloudy  ");
});

test("text length boundaries are accepted", async () => {
    const result = await invoke({
        city: "a".repeat(80),
        temperature_c: 0,
        condition: "b".repeat(120)
    });
    assert.equal(result.status, 200);
    assert.equal(result.body.city.length, 80);
    assert.equal(result.body.condition.length, 120);
});

for (const temperature of [0, -8, 23.75]) {
    test(`numeric temperature ${temperature} is accepted`, async () => {
        const result = await invoke({
            ...fixture,
            temperature_c: temperature
        });
        assert.equal(result.status, 200);
        assert.equal(result.body.temperature_c, temperature);
        assert.equal(result.body.message,
            `Weather in Amsterdam: ${temperature}°C, Cloudy.`);
    });
}

for (const [label, body] of [
    ["missing", undefined],
    ["null", null],
    ["text", "weather"],
    ["array", []],
    ["number", 42]
]) {
    test(`${label} body is rejected`, async () => {
        const result = await invoke(body);
        assert.equal(result.status, 400);
        assert.deepEqual(result.body, { error: "expected_json_object" });
    });
}

for (const [field, error, values] of [
    ["city", "invalid_city",
        [undefined, null, 42, "", "   ", "a".repeat(81)]],
    ["temperature_c", "invalid_temperature",
        [undefined, null, "12.5", true, NaN, Infinity, -Infinity]],
    ["condition", "invalid_condition",
        [undefined, null, 42, "", "   ", "b".repeat(121)]]
]) {
    values.forEach((value, index) => {
        test(`${field}: invalid case ${index + 1}`, async () => {
            const body = { ...fixture };
            if (value === undefined) {
                delete body[field];
            } else {
                body[field] = value;
            }
            const result = await invoke(body);
            assert.equal(result.status, 400);
            assert.deepEqual(result.body, { error });
        });
    });
}

for (const method of ["GET", "PUT", "DELETE"]) {
    test(`${method} is rejected with an Allow header`, async () => {
        const result = await invoke(fixture, method);
        assert.equal(result.status, 405);
        assert.equal(result.headers.Allow, "POST");
        assert.deepEqual(result.body, { error: "method_not_allowed" });
    });
}
