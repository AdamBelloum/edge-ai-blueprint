# TA audit checks

Every check of the audit scripts, generated from them by `python audit_common.py`.
README.md explains FAIL, WARN and INFO and how to run the scripts.

## Assignment 1: `audit_a1.py`

| Check | Severity | What is checked | Why | Oral exam |
|---|---|---|---|---|
| A1-METHOD-01 | FAIL | POST / with a valid URL answers 201 and an identifier | The specification table of Assignment 1 lists 201 with the id for POST /. | Show how POST / creates a mapping and what it returns. |
| A1-METHOD-02 | FAIL | GET /:id answers 301 and gives the stored URL | The specification table of Assignment 1 lists 301 with the value for GET /:id. | Show GET /:id: which status, and where is the URL in the answer? |
| A1-METHOD-03 | WARN | 301 answers have a Location header, so browsers follow them | A 301 without Location is not a redirect: a browser shows the body instead of going to the URL. The course test accepts either, so this is a design point, not a spec violation. | What does a browser do with your 301 answer? Why did you choose this? |
| A1-METHOD-04 | FAIL | A Location header holds the absolute stored URL | A relative or different Location sends the browser to the wrong place. | Where does your Location header come from? |
| A1-METHOD-05 | FAIL | GET /:id answers 404 for an unknown identifier | The specification table of Assignment 1 lists 404 for GET /:id. | When does GET /:id answer 404? |
| A1-METHOD-06 | FAIL | PUT /:id with a valid URL answers 200 and changes the target | The specification table of Assignment 1 lists 200 for PUT /:id. | Show PUT /:id: what does it change? |
| A1-METHOD-07 | FAIL | PUT /:id with an invalid URL answers 400 and keeps the old URL | The specification table of Assignment 1 lists 400 "error" for PUT /:id. | How does PUT /:id validate the URL? Show it with 'htInvalid_url/'. |
| A1-METHOD-08 | FAIL | PUT /:id for an unknown identifier answers 404 | The specification table of Assignment 1 lists 404 for PUT /:id. | What does PUT do for an id that does not exist? |
| A1-METHOD-09 | FAIL | DELETE /:id answers 204; afterwards GET and DELETE answer 404 | The specification table of Assignment 1 lists 204 and 404 for DELETE /:id. | Show DELETE /:id. |
| A1-METHOD-10 | WARN | 204 answers have no body | HTTP forbids a body in a 204 answer; clients may misread the next answer. | What does your DELETE /:id return as body? |
| A1-METHOD-11 | FAIL | GET / answers 200 and lists the identifiers | The specification table of Assignment 1 lists 200 with the keys for GET /. | What does GET / return? |
| A1-METHOD-12 | FAIL | DELETE / answers 404 | The specification table of Assignment 1 lists only 404 for DELETE /. | Why 404, and what does DELETE / do? |
| A1-METHOD-13 | FAIL | DELETE / removes the mappings | The course test script defines DELETE / as "Deletes all ID/URL pairs" (returning 404). In Assignment 2 it removes the caller's mappings. | What does DELETE / delete in your service? |
| A1-METHOD-14 | FAIL | POST / with an empty or missing URL answers 400 | The specification table of Assignment 1 lists 400 "error" for POST /. | How does POST / handle a missing URL? |
| A1-METHOD-15 | WARN | 400 answers say what is wrong | The specification table of Assignment 1 lists 400 with an "error" value; an empty answer does not tell the client anything. | What does a client see when its URL is rejected? |
| A1-ID-01 | FAIL | Many different URLs get different identifiers that each lead to their own URL | Assignment 1 maps every URL to a unique identifier (rubric: unique ID without conflicts). | Explain your identifier algorithm. How do you guarantee uniqueness? |
| A1-ID-02 | FAIL | After a delete, a new URL never takes the identifier of an existing mapping | Schemes such as len(store) + 1 hand out an identifier that is still in use, overwriting a mapping. | What happens to your counter or hash after a delete? |
| A1-ID-03 | WARN | The identifier of a deleted mapping is not handed out again | If a deleted identifier is reused, old short links silently lead to someone else's URL. | Can an old short link ever lead to a different URL? Is that acceptable? |
| A1-ID-04 | FAIL | Identifiers stay unique when URLs are created concurrently | The Flask development server handles requests in threads; an unprotected counter or check-then-insert can give two URLs the same identifier. | What happens when two requests create a mapping at the same moment? |
| A1-ID-05 | FAIL | Two URLs whose hashes collide still get separate mappings | Truncated hashes collide (24 bits after ~5,000 URLs on average). Without collision handling the second URL overwrites the first or gets the first one's identifier. | Your identifiers are truncated hashes. What happens when two URLs hash to the same prefix? |
| A1-ID-06 | WARN | Identifiers are as short as possible | Assignment 1 asks for identifiers that are as short as possible (rubric: report, hash function). | How long are your identifiers after N URLs, and what is the minimum possible? |
| A1-ID-07 | WARN | Identifiers contain only characters that are safe in a URL path | Characters such as / ? # % + or spaces must be encoded in a URL; short links then break or look odd. | Which characters can your identifiers contain? |
| A1-ID-08 | INFO | Observations on the identifiers | – | – |
| A1-URL-01 | FAIL | POST / rejects strings that are not URLs (400) | Assignment 1 (full points): check URL validity with a regular expression before creating a mapping. | Show your regular expression. Why does it accept this input? |
| A1-URL-02 | FAIL | PUT /:id rejects strings that are not URLs (400) and keeps the old URL | The specification table of Assignment 1 lists 400 "error" for PUT /:id; the full-points regex applies to updates too. | Does PUT use the same validation as POST? |
| A1-URL-03 | FAIL | URLs with control characters (newline, tab, NUL) are rejected | A URL with CR/LF that reaches a Location header can inject headers; it is never a valid URL. | What does your regex do with a newline in the URL? |
| A1-URL-04 | FAIL | Ordinary valid URLs are accepted and stored exactly | A validator that rejects valid URLs (unicode, apostrophes, fragments, queries, percent-encoding) breaks the service for real users; the course's own URLs are among them. | Why does your regex reject this URL? |
| A1-URL-05 | WARN | Less common valid URLs are accepted | These are valid URLs (upper case, ports, IP addresses, localhost, punycode, parentheses, long paths); rejecting them is a defensible choice only if the students can explain it. | Your regex rejects this valid URL. Was that deliberate? |
| A1-URL-06 | WARN | Questionable input is rejected | These strings are not valid URLs (no top-level domain, empty or invalid labels, impossible ports or IP addresses, spaces), but simple patterns accept them. | Your regex accepts this. Is it a valid URL? |
| A1-URL-07 | FAIL | A URL without scheme (uva.nl) is rejected or completed, never stored as is | The rubric names "uva.nl" as an extempore test. Stored as is, the redirect is relative and leads to /uva.nl on the shortener itself. | What happens with 'uva.nl'? Where does the redirect lead? |
| A1-URL-08 | INFO | Other schemes (ftp, mailto) | – | – |
| A1-URL-09 | FAIL | Values that are not strings are rejected with 400 | A number, list, object, null or boolean is not a URL; a crash (500) or acceptance is a bug. | What does POST / do when the value is not a string? |
| A1-URL-10 | FAIL | A very long URL does not crash the service | A 100,000-character value may be rejected (400/413/414) or stored, but must not cause a 500. | Do you limit the length of a URL? |
| A1-ROBUST-01 | FAIL | Malformed JSON bodies get a 4xx answer, not a crash or a new mapping | Invalid input must give a client error (400), never a server error (500). | How do you parse the request body? What if it is not valid JSON? |
| A1-ROBUST-02 | FAIL | Bodies without a JSON content type never cause a 500 | Clients such as curl send text/plain or form data unless told otherwise. | What does your service do with a form-encoded body? |
| A1-ROBUST-03 | FAIL | Odd identifiers in the path get 404, not a crash | GET/PUT/DELETE /:id must handle any string, including encoded and very long ones. | What does GET /:id do with an id that is not one of yours? |
| A1-ROBUST-04 | FAIL | Unsupported methods get a 4xx answer, not a crash | PATCH, or POST on /:id, are not part of the API: 405 (or 404) is the right answer. | Which methods does your API support? |
| A1-ROBUST-05 | FAIL | A 1 MB request body does not crash the service | Large bodies must be rejected or handled, never cause a 500 or bring the service down. | Do you limit the request size? |
| A1-ROBUST-06 | WARN | JSON answers declare Content-Type: application/json | Clients rely on the content type to parse the answer. | How do you build your answers? |
| A1-ROBUST-07 | FAIL | The service still answers after all checks | Earlier input must not have crashed or blocked the service. | Did the service crash? Check its log. |
| A1-DATA-01 | FAIL | URLs are given back exactly as they were stored | Changing a URL (case, trailing slash, order of the query, fragment) can lead to a different page. | Do you change URLs before storing them? |
| A1-DATA-02 | FAIL | Updating or deleting one mapping leaves the others unchanged | An update or delete must touch only its own mapping. | Show how PUT and DELETE find the mapping. |

## Assignment 2: `audit_a2.py`

After these checks, `audit_a2.py` runs every Assignment 1 check again through the multi-user shortener, with a token, and reports them as A2-METHOD-01 and so on.

| Check | Severity | What is checked | Why | Oral exam |
|---|---|---|---|---|
| A2-AUTH-01 | FAIL | POST /users creates a user (201) | The specification tables of Assignment 2 list 201 for POST /users. | Show how a user is created and stored. |
| A2-AUTH-02 | FAIL | POST /users with an existing username answers 409 | The specification tables of Assignment 2 list 409 "duplicate". | How do you detect duplicate usernames? |
| A2-AUTH-03 | WARN | The 409 answer says "duplicate" | The specification tables of Assignment 2 give the value "duplicate" with 409 (the course test checks it). | What does a client see when the username is taken? |
| A2-AUTH-04 | FAIL | POST /users without a username or password is refused (4xx) | Accounts without a name or password are invalid; the answer must be a client error, never 201 and never 500. | What does POST /users do with incomplete input? |
| A2-AUTH-05 | FAIL | Values that are not strings do not crash POST /users | A number, list, object or null as username or password must give a 4xx, not a 500. | What does POST /users do when the username is a number? |
| A2-AUTH-06 | FAIL | POST /users/login with the right password answers 200 and a token | The specification tables of Assignment 2 list 200 with the JWT. | Show the login and how the token is made. |
| A2-AUTH-07 | FAIL | Login with a wrong password answers 403 | The specification tables of Assignment 2 list 403 "forbidden" for a failed login. | What happens with a wrong password? |
| A2-AUTH-08 | FAIL | Login with an unknown username answers 403 | The specification tables of Assignment 2: "Check if username and password exist in the table and generate a JWT or else return 403". | What does login answer for a user that does not exist? |
| A2-AUTH-09 | WARN | 403 answers say "forbidden" | The specification tables of Assignment 2 give the value "forbidden" with 403 (the course test checks it). | What does a client see when the login fails? |
| A2-AUTH-10 | FAIL | Login with missing fields or broken JSON is refused (4xx) | A login without a password must not succeed, and broken input must not crash the service. | What does login do with incomplete input? |
| A2-AUTH-11 | FAIL | PUT /users with the right old password changes the password | The specification tables of Assignment 2 list 200 for PUT /users with the correct old password. | Show the password change. Which fields does PUT /users expect? |
| A2-AUTH-12 | FAIL | PUT /users with a wrong old password answers 403 and changes nothing | The specification tables of Assignment 2: "Update the user's password if the user presents the correct old password, or else return 403". | What does PUT /users do with a wrong old password? |
| A2-AUTH-13 | WARN | PUT /users for an unknown user answers 403 | The specification tables of Assignment 2 list only 200 and 403 for PUT /users. 404 is an allowed extra code, but it tells anyone which usernames exist. | Why this status for a user that does not exist? |
| A2-AUTH-14 | FAIL | Changing one user's password leaves other users alone | A password change must touch only that account. | How does PUT /users find the account? |
| A2-AUTH-15 | FAIL | PUT /users with missing fields or broken JSON is refused (4xx) | Incomplete input must not change a password or crash the service. | What does PUT /users do with incomplete input? |
| A2-AUTH-16 | FAIL | No answer contains a password | Passwords (or their hashes) must never be sent back to a client. | What do your answers to /users and /users/login contain? |
| A2-AUTH-17 | INFO | Observations on the authentication service | – | – |
| A2-JWT-01 | FAIL | The login token is a JWT: three base64url parts with a JSON header and payload | Assignment 2 asks for JSON Web Tokens built by hand: base64url(JSON header).base64url(JSON payload).signature. | Build a token on the whiteboard: what are its three parts? |
| A2-JWT-02 | FAIL | The token is signed | An unsigned token (alg none, empty signature) can be forged by anyone. | How is the token signed, and with which key? |
| A2-JWT-03 | FAIL | The token holds no password or password hash | A JWT is only encoded, not encrypted: anyone who has it can read the payload. | What does your token contain, and why? |
| A2-JWT-04 | WARN | The payload holds only what is needed | Assignment 2: "Make sure your JWTs do not contain unnecessary information". | Why does the token contain these claims? |
| A2-JWT-05 | WARN | The token expires | A token without exp stays valid forever, also after a password change. | How long is a token valid? How would you revoke one? |
| A2-JWT-06 | WARN | The parts are base64url without padding | RFC 7519 encodes JWT parts in base64url without '='. Standard base64 ('+', '/', '=') is not a valid JWT for other software. | Which base64 variant do you use, and why? |
| A2-JWT-07 | WARN | The token is not signed with a shared secret (HS*) | Assignment 2: keep the secret in the authentication service and do not share it with the shortener. With HMAC, the shortener can only check a token itself if it has the secret. | How does your shortener check an HS256 token without the secret? |
| A2-JWT-08 | INFO | Observations on the token | – | – |
| A2-JWT-09 | FAIL | The shortener accepts a valid token | Assignment 2: the shortener verifies the JWTs that the authentication service issues. If it refuses valid tokens, no user can manage mappings. | How does the shortener verify a token, and with which key? |
| A2-JWT-10 | FAIL | A token whose payload was changed is rejected | The shortener must check the signature; otherwise anyone can extend or alter a token. | Where and how does the shortener check the signature? |
| A2-JWT-11 | FAIL | An unsigned token (alg none) is rejected | Accepting alg none lets anyone write their own token. | Does your verification look at the alg in the header? |
| A2-JWT-12 | FAIL | A token with a missing or damaged signature is rejected | The signature is what makes the token trustworthy. | Show the signature check. |
| A2-JWT-13 | FAIL | A token cannot be changed to act as another user | If the shortener reads the user from an unchecked token, Alice can manage Bob's mappings. | How does the shortener know which user sends a request? |
| A2-JWT-14 | FAIL | Garbage tokens get 403, not a crash | Any string can arrive as a token; the answer must be 403 "forbidden". | What happens when the token cannot be decoded? |
| A2-JWT-15 | INFO | A token after a password change | – | – |
| A2-MULTI-01 | FAIL | Without a token, every management endpoint answers 403 | The specification tables of Assignment 2 add 403 "forbidden" to PUT /:id, DELETE /:id, GET /, POST / and DELETE /. | When does your shortener ask for a token? |
| A2-MULTI-02 | FAIL | With an invalid token, every management endpoint answers 403 | The specification tables of Assignment 2 add 403 "forbidden" for these endpoints. | What happens with an invalid token? |
| A2-MULTI-03 | FAIL | GET /:id works without a token | The specification tables of Assignment 2 have no 403 for GET /:id: short links are public. | Who may follow a short link? |
| A2-MULTI-04 | FAIL | GET / lists only the caller's mappings | Assignment 2: associate mappings with users so that only they can manage them. | How does GET / decide which keys to return? |
| A2-MULTI-05 | FAIL | Another user cannot change a mapping | Only the owner may manage a mapping; requiring a login is not enough. | Where does PUT /:id check the owner? |
| A2-MULTI-06 | FAIL | Another user cannot delete a mapping | Only the owner may delete a mapping. | Where does DELETE /:id check the owner? |
| A2-MULTI-07 | WARN | Another user's attempt is answered with 403 | The specification tables of Assignment 2 use 403 "forbidden" for this case. 404 hides that the mapping exists, which is defensible but not the specified code. | Why this status code? |
| A2-MULTI-08 | FAIL | DELETE / removes only the caller's mappings | Deleting all mappings of all users is a multi-user bug. | What does DELETE / delete? |
| A2-MULTI-09 | FAIL | Two users who shorten the same URL keep separate mappings | An identifier derived from the URL alone can hand an existing mapping (and its ownership) to a second user. | What happens when Bob shortens a URL that Alice already shortened? |
| A2-MULTI-10 | FAIL | Concurrent requests of two users keep identifiers and owners apart | Concurrent POSTs must not share identifiers or mix up owners. | What happens when two users create mappings at the same moment? |
| A2-SVC-01 | WARN | The shortener does not serve the authentication endpoints | Rubric: two separate services. A shortener that answers POST /users looks like one program. | Are your services separate programs? How do they communicate? |
| A2-SVC-02 | WARN | The authentication service does not serve the shortener | Rubric: two separate services. | Are your services separate programs? |
| A2-SRC-01 | FAIL | No library builds or checks the JWT | Assignment 2: "Do not use libraries that implement JWTs for you ... Using a library that does everything will cost you a few points." | Which libraries do you use for the token, and for what? |
| A2-SRC-02 | WARN | No JWT library is listed as a dependency | A JWT library in the requirements suggests it is used, even if no import was found. | Why is this package a dependency? |
| A2-SRC-03 | FAIL | The shortener holds no private key | Assignment 2: keep the secret in the authentication service; do not share it with the shortener. | Which key material does the shortener have, and why? |
| A2-SRC-04 | WARN | The two services do not contain the same secret | The same secret constant in both services means the shortener can sign tokens too. | Where is the signing secret, and who knows it? |
| A2-SRC-05 | WARN | The services are separate programs, not Blueprints of one app | Rubric: points for re-implementing the services, "and not used stuff like Blueprint". | How are your services started? Are they separate processes? |
| A2-SRC-06 | INFO | Observations on the source | – | – |

## Assignment 3.1: `audit_a3.py --part 3.1`

| Check | Severity | What is checked | Why | Oral exam |
|---|---|---|---|---|
| A3-COMPOSE-01 | FAIL | Both services run in containers | Assignment 3.1: deploy the services with Docker Compose. | Show docker compose ps. What does each container run? |
| A3-COMPOSE-02 | FAIL | The services' published ports listen on all interfaces | Assignment 3.1: the services must be accessible from outside the machine, not just from within the Docker container. | From which machines can your services be reached? |
| A3-COMPOSE-03 | FAIL | The services work in their containers | Assignment 3.1: the services must still work when they run with Docker. | Show a few requests to both services. |
| A3-COMPOSE-04 | WARN | The data is kept in named volumes or folders of the host | Assignment 3.1: write the data to a file and keep it in a Docker volume. Data written inside a container, or in an anonymous volume, is lost when docker compose down removes the container. | Where do your services write their data, and what keeps it? |
| A3-COMPOSE-05 | WARN | The services do not share a writable data folder | If the shortener can write the authentication service's data, it can change a password hash and log in as anyone. | Can the shortener read or change the accounts? |
| A3-COMPOSE-06 | FAIL | The shortener's container cannot read the private key | Assignment 2 and 3: the signing key stays in the authentication service. With the private key, the shortener (or whoever breaks into it) can sign tokens for any user. | Which key files does each container see, and why? |
| A3-COMPOSE-07 | FAIL | Accounts and mappings survive docker compose restart | Assignment 3.1: the services must keep their data across restarts. | Where do your services write their data? |
| A3-COMPOSE-08 | FAIL | Accounts and mappings survive docker compose down and up | Assignment 3.1: the data must also survive docker compose down, which removes the containers (but not the named volumes, unlike down -v). | Which volume keeps the data, and what does docker compose down -v do? |
| A3-COMPOSE-09 | INFO | Observations on the Compose project | – | – |
| A3-IMAGE-01 | FAIL | The shortener image holds no private key | Assignment 2 and 3: the signing key stays in the authentication service. A key in any layer of the shortener image, even one that a later layer deletes, lets anyone with the image sign tokens. | How do the keys get into your containers? |
| A3-IMAGE-02 | WARN | The other images hold no private key | A key built into an image is readable by anyone who can pull the image, and in Part 3.2 the images go to a registry. Mount the key instead (a volume, a Kubernetes Secret). | Where does the authentication container get its key? Who can download your image? |
| A3-IMAGE-03 | WARN | The images are small | Assignment 3.1: make the containers as efficient as possible. A python:3.x-slim image with Flask and cryptography holds about 150-200 MB of files. | What did you do to keep the images small? |
| A3-IMAGE-04 | WARN | The images start from a slim base image | A full python:3 image is several hundred MB larger than python:3-slim, and a general base such as ubuntu needs Python and its tools installed on top. | Why this base image? |
| A3-IMAGE-05 | WARN | The dependencies are installed before the code is copied | Assignment 3.1: pay attention to the ordering of your commands. Copying the code first invalidates the dependency layer on every code change, so every build installs all packages again. | What happens to your build when you change one line of code? |
| A3-IMAGE-06 | WARN | The images hold no files the service does not need | Assignment 3.1: include the minimum number of dependencies and source files. Caches, virtual environments and repositories make the image larger and may leak files; a .dockerignore and pip's --no-cache-dir keep them out. | What is in your build context, and what ends up in the image? |
| A3-IMAGE-07 | WARN | Flask's debugger is not running in the containers | With debug mode on, the Werkzeug debugger lets anyone who triggers an error run code in the container; reachable from other machines, that is a remote code execution hole. | Why does the container run in debug mode? |
| A3-IMAGE-08 | INFO | Observations on the images | – | – |

## Assignment 3.2: `audit_a3.py --part 3.2`

| Check | Severity | What is checked | Why | Oral exam |
|---|---|---|---|---|
| A3-K8S-01 | FAIL | The cluster has at least three nodes, all Ready | Assignment 3.2: a cluster on three VMs, one control plane and two workers. | Show kubectl get nodes. How did you set up the cluster? |
| A3-K8S-02 | WARN | One control plane and at least two workers | Assignment 3.2 uses one VM as the control plane and two as workers. | Which node has which role? |
| A3-K8S-03 | WARN | The system pods are running | A failing network plugin, DNS or kube-proxy pod breaks Services in ways that are hard to see. | Which network plugin do you use? Why does this pod fail? |
| A3-K8S-04 | FAIL | A Deployment for each service, with all replicas ready | Assignment 3.2: create Deployments for your services. | Show your Deployment files. |
| A3-K8S-05 | FAIL | At least one service runs three or more replicas | Assignment 3.2: at least one of the services must run with 3 replicas. | Which service did you replicate, and why that one? |
| A3-K8S-06 | WARN | The replicas run on more than one node | Replicas on one node do not survive the loss of that node and leave the workers unused. | On which nodes do the replicas run, and why? |
| A3-K8S-07 | FAIL | Each service has a Service with an endpoint for every ready pod | Assignment 3.2: create Services for your services. A selector that misses pods sends them no traffic. | Show your Service files. How does a Service find its pods? |
| A3-K8S-08 | FAIL | The services are reachable from outside the cluster | Assignment 3.2: create Services that make the services externally accessible (a NodePort or LoadBalancer Service, or an Ingress or proxy in front of them), and think about the best kind. | Why this Service type? How do you reach it from your computer? |
| A3-K8S-09 | FAIL | The services work through the given URLs | Assignment 3.2: the services must work when accessed from outside the cluster. | Which address and port do you use from your computer? |
| A3-K8S-10 | FAIL | Every shortener replica gives the same data | Assignment 3.2: the replicas must offer a consistent view of the stored data. | Where do the replicas keep their data? How does one replica see another's changes? |
| A3-K8S-11 | FAIL | Every authentication replica knows the same accounts and signs with the same key | Assignment 3.2: the replicas must offer a consistent view of the stored data, accounts included; and the shortener must accept the tokens of every replica. | Where do the authentication replicas keep the accounts and the signing key? |
| A3-K8S-12 | INFO | Concurrent writes through the Service | – | – |
| A3-K8S-13 | INFO | How the Service spreads requests over the replicas | – | – |
| A3-K8S-14 | WARN | No ConfigMap holds a private key | ConfigMaps are meant for configuration, not secrets: access to Secrets can be limited separately, and they are not shown by default. A private key belongs in a Secret. | Where is the signing key stored in the cluster? |
| A3-K8S-15 | FAIL | The shortener's pods cannot read the private key | Assignment 2 and 3: the signing key stays in the authentication service. With the private key, the shortener (or whoever breaks into it) can sign tokens for any user. | Which Secrets, ConfigMaps and volumes does each Deployment use, and why? |
| A3-K8S-16 | WARN | The services do not share a writable data folder | If the shortener can write the authentication service's data, it can change a password hash and log in as anyone. | Can the shortener read or change the accounts? |
| A3-K8S-17 | WARN | The replicas keep their data where all of them can reach it | emptyDir and hostPath are local to a pod or a node, and a ReadWriteOnce volume can be mounted on one node only: the replicas then keep separate data or must share one node. | Where do the replicas keep their data? |
| A3-K8S-18 | WARN | The pods do not restart | Restarts point to crashes or failing probes. | Why did this pod restart? |
| A3-K8S-19 | WARN | Flask's debugger is not running in the pods | With debug mode on, the Werkzeug debugger lets anyone who triggers an error run code in the pod; behind a NodePort, that is a remote code execution hole. | Why does the pod run in debug mode? |
| A3-K8S-20 | INFO | Observations on the workloads | – | – |
| A3-K8S-21 | FAIL | Accounts and mappings survive a rollout restart of the services | New pods must find the data of the old ones. | What happens to the data when a pod is replaced? |
| A3-K8S-22 | WARN | Requests from one computer can reach every replica | With sessionAffinity: ClientIP, or externalTrafficPolicy: Local, all requests from one computer (or through one node) reach the same pod: then K8S-10 and K8S-11 cannot see whether the other replicas hold the same data. | How do requests reach the replicas? Show that every replica gives the same data. |
| A3-K8S-23 | FAIL | The shortener's image in the registry holds no private key | Assignment 2 and 3: the signing key stays in the authentication service. The registry hands the image to anyone who pulls it, with every layer. | How do the keys get into your pods? |
| A3-K8S-24 | WARN | The other images in the registry hold no private key | A key built into an image goes to the registry with it, readable by anyone who can pull the image. A Kubernetes Secret keeps it out of the image. | Who can pull your images? |
