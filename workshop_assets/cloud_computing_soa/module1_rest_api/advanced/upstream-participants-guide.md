# Workshop: Architecting a RESTful URL Shortener

Welcome! Today, you are moving beyond theoretical Web Services to build a functional **URL Shortener API**. By the end of this session, you will have a service that accepts long URLs, generates unique short IDs, and handles redirects.

---

##  Extra Material
* **Unit Testing Guide:** A guide on how to use unit tests.
* **Data Source:** A `.csv` file where the tests will fetch data.
* **Unit Tests:** The actual test scripts.
* **Instructional PDF:** Read this carefully; it explains how unit tests work, what you can modify, and what is off-limits.

---

## 1. Prerequisites & Setup

Before we start, ensure your environment is ready.
* **Language:** Python 3.8+
* **Framework:** Flask (Micro-framework for Python)
* **Testing Tool:** Postman or `curl`
* **Starter Files:** Create a folder named `url_shortener` and a file named `app.py`.

### Background Reading
If you are new to these concepts, skim these quickly:
* **REST Principles:** What is REST?
* **HTTP Methods:** Understanding `GET`, `POST`, `PUT`, `DELETE`.
* **Status Codes:** Know your `201` (Created), `301` (Redirect), and `400`/`404` (Errors).

---

## 2. The Specification

Your API must implement the following endpoints. Use an **in-memory Python dictionary** (e.g., `url_db = {}`) to store your mappings during this workshop.

| Path | Method | Purpose | Return Code |
| :--- | :--- | :--- | :--- |
| `/` | `GET` | List all shortened IDs | 200 OK |
| `/` | `POST` | Create a new short ID for a URL | 201 Created |
| `/:id` | `GET` | Redirect to the original URL | 301 Moved Permanently |
| `/:id` | `PUT` | Update the URL for an existing ID | 200 OK |
| `/:id` | `DELETE` | Remove a mapping | 204 No Content |

---

## 3. Hands-on Challenges

### Step 1: The Skeleton (15 mins)
Create a basic Flask app that responds to `GET /`.
* **Goal:** Verify your environment works.
* **Reference:** Flask - Routing.

`[!NOTE]` if for some reason you cannot perform this step move on the next step and use the provided scheleton
[skeleton-STILL MISSING](./01-rest-api-skeleton.py)
### Step 2: The "Shortener" Algorithm (30 mins)
When a user `POST`s a URL to `/`, you need to give them a short ID (e.g., `/aB3`).
* **The Problem:** How do you make IDs short but unique?
* **Constraint:** Do not use random numbers (they collide) or simple 1, 2, 3 (they are predictable).
* **Tip:** Research **Base62 Encoding** or use a portion of an **MD5/SHA hash**.


### Step 3: Validation & Security (20 mins)
Don't trust the user! Before saving a URL, you must ensure it is valid.
* **Task:** Use a **Regex (Regular Expression)** to check if the input is a valid `http://` or `https://` link.
* **Reference:** Python `re` Module.
* **Fail Case:** If the URL is invalid, return `400 Bad Request`.

### Step 4: The Redirect (20 mins)
When someone visits `/:id`, they shouldn't see text; their browser should "jump" to the destination.
* **Task:** Use Flask's `redirect()` function and ensure you set the status code to `301`.

---

## 4. Testing Your Service
Once your code is running, open **Postman** and try to "break" your service:
1.  **Create:** Send a `POST` to `/` with JSON: `{"url": "https://www.google.com"}`.
2.  **Verify:** Get the ID and try `GET /<your_id>` in your browser.
3.  **Error Check:** Try to `DELETE` an ID that doesn't exist. Do you get a `404`?
4.  **Update:** Use `PUT` to change where an existing ID points.

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
