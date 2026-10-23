"use strict";

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

    if (typeof body.name !== "string") {
        return respond(400, { error: "invalid_name" });
    }

    const name = body.name.trim();
    if (name.length === 0 || name.length > 80) {
        return respond(400, { error: "invalid_name" });
    }

    return respond(200, {
        message: `Hello ${name}, your function is live!`
    });
};
