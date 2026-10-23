# Module 1 — Advanced track: a URL shortener

Write a RESTful URL-shortening service. It is a repository of URLs, in which
every URL is mapped to a unique, and as short as possible, identifier. Other
programs use its API to resolve an identifier to the full URL, or to manage
the mappings.

## Specification

| Path and method | Parameters | Returns (HTTP code, value) |
|---|---|---|
| `/:id` GET | `:id`: identifier of a URL | 301, value; 404 |
| `/:id` PUT | `:id`: identifier of a URL | 200; 400, "error"; 404 |
| `/:id` DELETE | `:id`: identifier of a URL | 204; 404 |
| `/` GET | | 200, keys |
| `/` POST | `:url`: URL to shorten | 201, id; 400, "error" |
| `/` DELETE | | 404 |

The specification is ambiguous on purpose: finding an interpretation that
follows REST and CRUD principles is part of the task. Support every path, and
return every listed code in situations where it makes sense. The
specification does not say what the request bodies contain; the grading
script sends its requests in a fixed format, so read it to see what your
service must accept.

For full points, also:

- give new URLs identifiers that are as short as possible;
- check URLs with a regular expression before creating or updating a mapping.

You may add functionality and require additional parameters in the request
body, but not in the URL. The service may keep its data in memory.

## Rules

- The workshop environment has Python with Flask. Run the service on
  `127.0.0.1:5000`.
- Write the service yourself. If you use someone else's code, cite the source
  in a comment and be ready to explain how it works.

## Check your work

Start the service in one terminal. In another:

```bash
cd ~/Cloud-Computing-SOA/Module-1/tests
python test_api.py
```

## Question

How would you implement a URL shortener in which several users can create
and remove their own mappings?
