# Workshop: Architecting a RESTful URL Shortener

Welcome! Today, you are moving beyond theoretical Web Services to build a functional **URL Shortener API**. By the end of this session, you will have a service that accepts long URLs, generates short IDs, and supports lookup, update, and deletion.

---

## Supplied Materials
* **Advanced workspace:** This guide and the `app.py` TODO skeleton.
* **Shared tests:** `../tests/test_api.py` and its input file, `../tests/read_from.csv`.
* **Reference solution:** Released separately by the workshop organiser for the advanced track; it is not part of the initial teaching workspace.

Implement your solution in `app.py`. Treat the shared tests and their input data
as the supplied assessment contract; do not modify them to make a failing
implementation pass.

---

## 1. Prerequisites & Setup

Before we start, ensure your environment is ready.
* **Language:** Python provided by the JupyterHub participant runtime.
* **Framework:** Flask (Micro-framework for Python)
* **Testing Tools:** `curl` in a JupyterHub terminal and the supplied Python integration tests.
* **Starter Files:** Edit the supplied [TODO skeleton](./app.py) in your
  JupyterHub workspace. Do not create a separate `url_shortener` project.

Open a JupyterHub terminal and work in the advanced track:

```bash
cd /home/jovyan/Cloud-Computing-SOA/Module-1/advanced
```

Complete the TODOs in `app.py`, including the development-server configuration.
Then start the application in this terminal:

```bash
python app.py
```

Leave it running on participant-local `127.0.0.1:5000`. Use a second JupyterHub
terminal for requests and tests; your laptop's localhost is different.


### Background Reading
If you are new to these concepts, skim these quickly:
* **REST Principles:** What is REST?
* **HTTP Methods:** Understanding `GET`, `POST`, `PUT`, `DELETE`.
* **Status Codes:** Know your `201` (Created), `301` (Redirect), and `400`/`404` (Errors).

---

## 2. The Specification

Complete the supplied `app.py` TODO skeleton. Use an in-memory Python dictionary
to store short-ID-to-URL mappings.

| Path | Method | Purpose | Success status |
| :--- | :--- | :--- | :--- |
| `/` | `GET` | List all shortened IDs | 200 |
| `/` | `POST` | Create a mapping using JSON field `value` | 201 |
| `/<id>` | `GET` | Return the stored URL or redirect to it | 301 |
| `/<id>` | `PUT` | Update a mapping using JSON field `url` | 200 |
| `/<id>` | `DELETE` | Remove one mapping | 204, empty body |
| `/` | `DELETE` | Clear all mappings | 404, assignment-specific |

Missing IDs return `404`. Missing or empty POST values and invalid PUT URLs
return `400`. Implement the skeleton's validation requirements; the current
tests cover only selected invalid inputs.

For `GET /<id>`, the tests accept either a real redirect with a `Location`
header or a JSON object containing the stored URL, both with status `301`.
The reference implementation uses JSON. A real redirect is an optional design
choice, not a requirement for passing these tests.

Returning `404` after successfully clearing all mappings is unusual HTTP API
design, but is required by this assignment's tests.

---

## 3. Hands-on Challenges

### Step 1: The Skeleton (15 mins)
Create a basic Flask app that responds to `GET /`.
* **Goal:** Verify your environment works.
* **Reference:** Flask - Routing.

> Use the supplied [TODO skeleton](./app.py) for this step and the remaining challenges. An unfinished route will not produce a valid response until you implement its TODOs.

### Step 2: The "Shortener" Algorithm (30 mins)
When a user `POST`s a URL to `/`, you need to give them a short ID (e.g., `/aB3`).
* **The Problem:** How do you make IDs short but unique?
* **Task:** Implement the ID-generation TODO in the supplied skeleton.
* **Discussion:** Random IDs and truncated hashes can collide. Base62 is an encoding, not a uniqueness guarantee. Sequential IDs are predictable, but predictability and uniqueness are different concerns.
* **Extension:** Consider how to detect an existing ID and avoid overwriting a different URL. Passing the supplied tests does not establish collision safety.


### Step 3: Validation & Security (20 mins)
Don't trust the user! Before saving a URL, you must ensure it is valid.
* **Task:** Use a **Regex (Regular Expression)** to check if the input is a valid `http://` or `https://` link.
* **Reference:** Python `re` Module.
* **Fail Case:** If the URL is invalid, return `400 Bad Request`.

### Step 4: URL Lookup and Optional Redirect (20 mins)
Implement `GET /<id>` according to the specification.
* **Task:** Return the stored URL in JSON with status `301`, matching the reference implementation; return `404` for a missing ID.
* **Optional alternative:** Use Flask's `redirect()` with status `301` and a `Location` header. The supplied tests also accept this response style.
* **Discussion:** A JSON response with status `301` does not itself make a browser navigate to the stored URL.

---

## 4. Testing Your Service

Keep the completed application running in the first JupyterHub terminal.
Use a second JupyterHub terminal for requests to `http://127.0.0.1:5000`.

Check these scenarios manually with `curl`:
1. **Create:** POST to `/` with JSON `{"value": "https://www.google.com"}`.
2. **Read:** Copy the returned ID and GET `/<id>`. Expect status `301` and
   either the stored URL in JSON or a `Location` header.
3. **Update:** PUT to `/<id>` with JSON `{"url": "https://example.org"}`.
   Read the mapping again to verify the change.
4. **Delete:** DELETE `/<id>`. Expect `204` with no response body.
5. **Missing ID:** Read or delete the removed ID. Expect `404`.

Use `curl -i` to inspect status codes and headers, and send JSON with
`-H "Content-Type: application/json"` and `-d '...'`.
Do not use `curl -L` when inspecting the API's initial redirect response.

Run the supplied integration tests from their directory:

```bash
cd /home/jovyan/Cloud-Computing-SOA/Module-1/tests
python -m unittest -v test_api
```

The suite opens `read_from.csv` relative to the current directory and requires
`requests`. The application requires Flask.

**Warning:** Tests create mappings and clear all mappings during cleanup.
Use disposable data and recreate any mapping needed for subsequent manual
checks. Restarting the application also clears its in-memory store.

Passing the supplied tests demonstrates the covered scenarios, not complete
input validation, collision handling, security, or production readiness.

---

## 5. Peer Review & Discussion
Once finished, discuss with your neighbor:
* **Scaling:** What happens to your dictionary if 1 million users create URLs?
* **Persistence:** How would you change this code to use a Database (like PostgreSQL) instead of a Python dictionary?

---

## 6. References
1. [Flask quickstart](https://flask.palletsprojects.com/en/stable/quickstart/)
2. [Flask Cheat Sheet](https://realpython.com/flask-blueprint/)
3. [Regular expresssion 101](https://regex101.com/)
4. [Learn RegEx](https://github.com/ziishaned/learn-regex/blob/master/README.md)
5. [iHateRegEx](https://ihateregex.io/expr/url/)
6. [HTTP status code](https://www.restapitutorial.com/httpstatuscodes)
7. [HTTP response status code](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Status)
