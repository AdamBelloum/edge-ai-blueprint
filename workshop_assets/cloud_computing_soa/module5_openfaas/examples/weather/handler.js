"use strict";

// Processes supplied teaching data; does not fetch live weather.
module.exports = async (event, context) => {
    const respond = (status, body) =>
        context.status(status)
            .headers({ "Content-Type": "application/json" })
            .succeed(body);

    if (event.method !== "POST") {
        return context.status(405)
            .headers({
                "Content-Type": "application/json",
                "Allow": "POST"
            })
            .succeed({ error: "method_not_allowed" });
    }

    const body = event.body;
    if (body === null || typeof body !== "object" || Array.isArray(body)) {
        return respond(400, { error: "expected_json_object" });
    }

    if (typeof body.city !== "string") {
        return respond(400, { error: "invalid_city" });
    }
    const city = body.city.trim();
    if (city.length === 0 || city.length > 80) {
        return respond(400, { error: "invalid_city" });
    }

    if (typeof body.temperature_c !== "number" ||
            !Number.isFinite(body.temperature_c)) {
        return respond(400, { error: "invalid_temperature" });
    }

    if (typeof body.condition !== "string") {
        return respond(400, { error: "invalid_condition" });
    }
    const condition = body.condition.trim();
    if (condition.length === 0 || condition.length > 120) {
        return respond(400, { error: "invalid_condition" });
    }

    return respond(200, {
        city,
        temperature_c: body.temperature_c,
        condition,
        message: `Weather in ${city}: ${body.temperature_c}°C, ${condition}.`
    });
};
