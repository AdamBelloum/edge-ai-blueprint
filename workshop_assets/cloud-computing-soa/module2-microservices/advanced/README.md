# Module 2 — Advanced track: microservices and JSON Web Tokens

Extend your URL shortener from Module 1 to several users. Write a second
service, the authentication service, that keeps a table of users and hands
out a JSON Web Token (JWT) after a successful login. The URL shortener then
requires users to be authenticated, and associates every mapping with the
user who created it, so that only that user can manage it.

## Specification

Authentication service:

| Path and method | Parameters | Description | Returns (HTTP code, value) |
|---|---|---|---|
| `/users` POST | `:username`, `:password` | Create a user with this username and password | 201; 409, "duplicate" |
| `/users` PUT | `:username`, `:old-password`, `:new-password` | Change the password if the old password is correct, else 403 | 200; 403, "forbidden" |
| `/users/login` POST | `:username`, `:password` | Return a JWT if the username and password exist, else 403 | 200, JWT; 403, "forbidden" |

URL shortener: the specification of Module 1, with 403 "forbidden" added.

| Path and method | Returns (HTTP code, value) |
|---|---|
| `/:id` GET | 301, value; 404 |
| `/:id` PUT | 200; 400, "error"; 404; 403, "forbidden" |
| `/:id` DELETE | 204; 404; 403, "forbidden" |
| `/` GET | 200, keys; 403, "forbidden" |
| `/` POST | 201, id; 400, "error"; 403, "forbidden" |
| `/` DELETE | 404; 403, "forbidden" |

You may add return codes to existing paths, as long as the API stays CRUD.

Also:

- Put nothing in the JWTs that is not needed.
- Keep the secret of the authentication service secret: the URL shortener
  must not have it.
- Build the JWT yourself: generate the JSON, encode it in base64 and sign
  it. Libraries for the single steps are fine; a library that creates or
  checks JWTs for you costs points.

Both services may keep their data in memory. You may add functionality and
require additional parameters in request bodies.

## Rules

- Run the URL shortener on `127.0.0.1:5000` and the authentication service on
  `127.0.0.1:5001`, in a Python environment with the packages in
  `../requirements.lock`.
- Write the services yourself. If you use someone else's code, cite the source
  in a comment and be ready to explain how it works.

## Check your work

Start both services, each in its own terminal. In a third:

```bash
cd ~/Cloud-Computing-SOA/Module-2/tests
python test_microservices.py
```

The grading script sends its requests in a fixed format; read it to see what
your services must accept.

## Questions

- Your services listen on two ports, but most microservice architectures are
  reachable on a single one. How can you give all your microservices one
  entry point?
- During peak traffic, one of your services can easily be overloaded. How
  would you scale up each service independently of the others?
- In a microservice architecture, many services are spread over several
  servers. How would you manage such a system? Which metrics (health,
  location, ...) would you need, and how would you collect them?
