# Module 3 — Advanced track: containers and Kubernetes

Run the two services of Module 2 in containers: first with Docker Compose,
then on a Kubernetes cluster. This folder holds the Module 2 services as they
were (`auth_service/`, `shortener_service/`, `setup_local_keys.sh` and
`requirements.lock`); you may use your own Module 2 services instead.

## Part 3.1: containers

- Containerize both services with Docker, and write a Docker Compose file
  that manages the containers.
- Make the services persistent: whatever stores the data writes it to a
  file, and a Docker volume keeps that file. The data must survive restarting
  the services, and `docker compose down`, which removes the containers.
- Make the containers as efficient as possible.
- The services must be reachable from outside your machine, not only from
  within the containers.

## Part 3.2: Kubernetes

- Set up a Kubernetes cluster on three VMs, one control plane and two
  workers, with the supplied cluster-setup tutorial.
- Create a Deployment for each service, and run at least one of the services
  with three replicas.
- Create Services that make your services reachable from outside the
  cluster.
- All replicas of a service must offer a consistent view of the stored data.

## Check your work

The grading script `~/Cloud-Computing-SOA/Module-3/tests/test_microservices.py`
checks both parts; `python3 test_microservices.py --help` shows how to run
it. It needs Python 3 with `requests`.

## Questions

- Based on observations only, deduce how Kubernetes distributes requests over
  the replicas of a service. Give examples that support your conclusion.
- What was your experience with Kubernetes, and what were the main
  challenges?

## Safety

- Run containers only on the organiser-approved Docker host, and Kubernetes
  objects only on your own lab VMs or in the organiser-approved lab
  namespace. Do not reconfigure a shared cluster.
- Remove only the containers, volumes and Kubernetes objects that you
  created.
- Never commit or share private keys.
