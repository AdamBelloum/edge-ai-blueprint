# Workshop: RESTful Microservices Architecture with JWT (Multi-User URL Shortener)

Welcome! In this workshop, you will evolve your **URL Shortener** into a **microservice architecture** with **multi-user support**.

By the end, you will have:
- An **Authentication Service** that manages users and issues **JSON Web Tokens (JWTs)** after successful login.
- A **URL Shortener Service** that requires authentication, associates mappings with specific users, and ensures **only the owner can manage their mappings**.
- A workflow where the shortener service verifies RS256 JWTs **locally using the authentication service's public key**, without contacting the authentication service for each request.

---

## 0. Concept Recap (What You’re Building)

### Microservices vs. Monolith
A microservice architecture splits backend functionality into **multiple simple services**, each with a defined role, instead of one monolithic service containing everything.

### What a JWT Is
In this workshop, a JWT contains a **header, payload, and signature**:
- The authentication service signs with an RSA **private key**.
- The shortener verifies the signature using the corresponding **public key**.
- The payload identifies the user through `sub` and includes issuance and
  expiration timestamps (`iat` and `exp`).
- Base64url encoding is not encryption: token contents remain readable.
- A valid token is not a live session check; ownership must still be enforced
  separately for each protected operation.

---

## 1. Services and Responsibilities

### 1.1 Service Map
| Service | Core Responsibility | Minimal State (In-Memory Allowed) | Key Constraint |
| --- | --- | --- | --- |
| Authentication Service | User database + login + JWT issuance | User table (username, password hash) | Keep the private signing key **only** here |
| URL Shortener Service | CRUD URL mappings with multi-user ownership | Mapping table (id → value + owner) | Must not possess the private signing key; verify tokens locally using the public key |

### 1.2 Data Ownership (Design Reminder)
| Data | Owned By | Used By | Notes |
| --- | --- | --- | --- |
| Users (credentials) | Authentication Service | Authentication Service | Store and update here |
| JWT private signing key | Authentication Service | Authentication Service | **Never share** with URL Shortener |
| URL mappings | URL Shortener Service | URL Shortener Service | Must be bound to a user (owner) |

---

## 2. Required API Specifications

You must implement the following endpoints and return codes.

---

## 2.1 Authentication Service: Required Endpoints

| Path & Method | Parameters | Description | Return Value (HTTP code, Value) |
| :--- | :--- | :--- | :--- |
| `/users` `POST` | `username` (unique), `password` | Create a new user and store it in a table | `201` OR `409, "duplicate"` |
| `/users` `PUT` | `username` (unique), `old_password`, `new_password` | Update password if the old password is correct | `200` OR `403, "forbidden"` |
| `/users/login` `POST` | `username` (unique), `password` | If credentials exist, generate and return a JWT | `200, JWT` OR `403, "forbidden"` |

---

## 2.2 URL Shortener Service: Updated Endpoints (With 403 Cases)

| Path & Method | Parameters | Return Value (HTTP code, Value) |
| :--- | :--- | :--- |
| `/:id` `GET` | `id` (unique identifier of a URL) | `301, value` OR `404` |
| `/:id` `PUT` | `id` (unique identifier of a URL) | `200` OR `400, "error"` OR `404` OR `403, "forbidden"` |
| `/:id` `DELETE` | `id` (unique identifier of a URL) | `204` OR `404` OR `403, "forbidden"` |
| `/` `GET` | (none) | `200, keys` OR `403, "forbidden"` |
| `/` `POST` | `url` (URL to shorten) | `201, id` OR `400, "error"` OR `403, "forbidden"` |
| `/` `DELETE` | (none) | `404` OR `403, "forbidden"` |

### What Changed Compared to the Earlier Shortener Spec?
| Change | Meaning |
| --- | --- |
| Inclusion of `403, "forbidden"` return codes | You must incorporate authentication/authorization failure paths |
| JWT protection in this track | Require a valid token for management routes; keep `GET /<id>` public |
| Adding extra return codes is allowed | As long as the API stays CRUD-style and still supports at least the listed spec |

---

## 3. JWT Requirements and Constraints

### 3.1 Mandatory Constraints
| Constraint | Why It Matters |
| --- | --- |
| Do not put unnecessary information in JWTs | More information costs more to hash/sign and more to transmit |
| Keep the private signing key only in the authentication service | Do **not** share it with the URL shortener service |

### 3.2 Implementation Rule: Build the Token Yourself
You are expected to construct the final JWT yourself by:
1. Generating the required JSON
2. Encoding it in Base64url
3. Signing it

| Allowed | Not Allowed |
| --- | --- |
| Libraries for **individual steps** (encoding, hashing, signing), with references if required | Libraries that implement JWT end-to-end for you |

---

## 4. Hands-on Build Plan

This workshop builds on Module 1, but supplies both service skeletons in
`intermediate/auth_service/auth.py` and `intermediate/shortener_service/shortener.py`.
Complete their TODOs without replacing the exercise with the reference solution.

### Before Running the Services
1. Implement `ensure_keys_exist()` in `auth_service/auth.py`.
2. From the `intermediate/` directory, run `bash setup_local_keys.sh`.
   The helper calls your function, protects the private key, and copies only
   the public key to the shortener. In a fresh workspace, it fails if the
   key-generation TODO is still unfinished.
3. Complete the remaining service TODOs before expecting API tests to pass.
4. Follow the module README for separate service terminals and test execution.
   Run these commands inside your own JupyterHub participant server.

### Step 1: Inspect the Two Supplied Service Skeletons
| Task | Deliverable |
| --- | --- |
| Inspect the authentication skeleton | Identify the user storage, JWT helpers, and endpoint TODOs |
| Inspect the shortener skeleton | Identify the token-verification, mapping-storage, and ownership TODOs |

**Goal:** Two independently runnable services with clear responsibility boundaries.

---

### Step 2: Implement the Authentication Service
Build the endpoints exactly as specified.

#### Checklist
| Endpoint | What to Verify |
| --- | --- |
| `POST /users` | Detect duplicate usernames and return `409, "duplicate"` |
| `PUT /users` | Reject wrong old password with `403, "forbidden"` |
| `POST /users/login` | Return `200, JWT` on success; `403, "forbidden"` on failure |

---

### Step 3: Construct JWTs (Manually, From Steps)
You must define what information you include (keeping it minimal), then construct and sign the token.

#### Token Design (Keep It Minimal)
| Decision | Guidance |
| --- | --- |
| What identity info is included | Keep it minimal; include only what’s needed to identify/authenticate the user |
| What the shortener needs to know | Enough to associate requests with a specific user after validation |

> Reminder: The authentication service signs with its private key; the shortener verifies with the corresponding public key.

---

### Step 4: Require Authentication in the URL Shortener Service
Modify the URL shortener so that:
- Users must be authenticated.
- Mappings are associated with specific users.
- Only the owner can manage their mappings.

#### Ownership and Authorization Rules
| Action | Must Be Enforced |
| --- | --- |
| Create mapping (`POST /`) | The created mapping is owned by the authenticated user |
| List mappings (`GET /`) | Only show keys that belong to the authenticated user (or otherwise ensure unauthorized users cannot access others’ data) |
| Update mapping (`PUT /:id`) | Only the owner can update; else `403, "forbidden"` |
| Delete mapping (`DELETE /:id`) | Only the owner can delete; else `403, "forbidden"` |

> Require a valid JWT for listing, creating, updating, and deleting mappings. Public `GET /<id>` resolution does not require a token. Accept `Authorization: Bearer <token>` or `x-access-token: <token>`, as described in the starter code.

---

### Step 5: Local Token Validation
Users present the JWT to the URL shortener service. The shortener service:
- Verifies the RS256 signature locally using its copy of the public key.
- Checks expiration and the subject (`sub`) claim.
- Uses the verified subject as the identity for ownership checks.

This does not query live login state or the authentication service's user
dictionary. Changing a password does not by itself revoke an existing token.

#### Flow Summary
| Step | Actor | Action |
| --- | --- | --- |
| 1 | Client | Logs in to authentication service and receives JWT |
| 2 | Client | Presents JWT to URL shortener service |
| 3 | URL Shortener Service | Verifies the signature, expiration, and subject locally using the public key |
| 4 | URL Shortener Service | Applies authorization rules (ownership) before CRUD operations |

---

## 5. Workshop “Demo Script” (Self-Check)

Use this as your structured run-through to ensure your implementation matches the spec.

### 5.1 Authentication Service Self-Check
| Scenario | Expected Result |
| --- | --- |
| Register a new user | `201` |
| Register same username again | `409, "duplicate"` |
| Change password with correct old password | `200` |
| Change password with wrong old password | `403, "forbidden"` |
| Login with correct credentials | `200, JWT` |
| Login with wrong credentials | `403, "forbidden"` |

### 5.2 URL Shortener Service Self-Check (With JWT)
| Scenario | Expected Result |
| --- | --- |
| Access a protected path without valid authentication | `403, "forbidden"` where applicable |
| Create a short URL as User A | `201, id` |
| List keys as User A | `200, keys` containing User A’s mappings (as designed) |
| Try to update User A’s mapping as User B | `403, "forbidden"` |
| Delete a mapping as the owner | `204` |
| Request an unknown id | `404` |
| Redirect for an existing id | `301, value` |

---

## 6. Discussion Prompts (Microservice Architecture Thinking)

These are design questions aligned with the workshop goals around organizing and operating microservices.

| Topic | Prompt |
| --- | --- |
| Single entry point | Your services run on different ports by default. How could you create one entry point for all microservices? Describe an approach. |
| Independent scaling | During peak traffic, one service could be overloaded. How would you scale services independently? Describe an approach. |
| Managing distributed services | If services are distributed across multiple backend servers, how would you manage the system? What metrics would you need (e.g., health, location), and how could you collect them? |
| Explaining chosen technology | If you propose a technology solution, explain at a high level how it addresses the above questions (naming it alone is not enough). |

---

## 7. Practical Notes (Implementation Boundaries)

### 7.1 Storage
| Component | Database Requirement |
| --- | --- |
| Authentication Service | External DB not required; in-memory storage is acceptable |
| URL Shortener Service | External DB not required; in-memory storage is acceptable |

### 7.2 Extensibility
| You May Do | Condition |
| --- | --- |
| Add functionality | Must still support at least the required spec |
| Add extra request-body constraints | Must still support at least the required spec |
| Add extra return codes | Keep endpoints CRUD-style and do not break the required spec |

---

## 8. Integrity and Attribution

| Rule | What It Means |
| --- | --- |
| Using external code is allowed with attribution | Provide a source in README/comments and explain how it works |
| Unattributed copying is not acceptable | Must show understanding; otherwise considered plagiarism |
| Avoid “JWT done-for-you” libraries | You must construct the token yourself via JSON → Base64url → signing |

---
### 9. References

1. [What are microservices?:](https://microservices.io/)
2. [Json Web Tokens (JWT):](https://jwt.io/introduction/)
3. [A Practical Guide for JWT Authentication using Nodejs and Express](https://medium.com/swlh/a-practical-guide-for-jwt-authentication-using-nodejs-and-express-d48369e7e6d4)
4. [Introduction to microservices:](https://www.nginx.com/blog/introduction-to-microservices/)
5. [An introduction to OAuth 2:](https://www.digitalocean.com/community/tutorials/an-introduction-to-oauth-2)
