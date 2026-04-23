# DigitAfrica EDGE-AI BP

---
This is the repository for deploying the Edge-AI Blueprint for DigitAfrica. Current repository is a scaffold for further developments in the project.

## What this deploys (high level)

Current implementation supports the following deployments:
* Tier - 0 : Bare metal implementation, deploying Jupyter notebooks on a single node, allowing playbooks to run on top. Implementation is deploying the following:
  *  Jupyter as a docker container
  *  cAdvisor for container-level statistics
  *  NodeExporter for node-level statistics
* Tier - 0 - k3s : K3s based implementation, deploying a single-node K3s cluster, and Jupyterhub on top. 
* Tier - 1: K3s implementation, deploying a multi-node K3s cluster, with Jupyterhub. Once it is instantiated, users can login with their accounts, and deploy their notebooks.

For all the cases, we assume that the use cases will deploy their functionality through scripts/notebooks on the infrastructure.

Current code has been tested using a three-node cluster, based on the Raspberry-Pi 5 platform.

---

## Configuration for the BP

Hosts need to be declared in the ```inventories/prod/hosts.ini``` file.

```
### TIER 0 NODES ###
[tier0]
; digitafrica-edge-node1 ansible_host=10.64.45.176 ansible_ssh_pass="1234" ansible_become_pass="1234" tier0_k3s_mode="none"
; digitafrica-edge-node1 ansible_host=10.64.45.176 ansible_ssh_pass="1234" ansible_become_pass="1234" tier0_k3s_mode="single"

### TIER 1 NODES ###
[tier1_server]
digitafrica-edge-node1 ansible_host=10.64.45.176 ansible_ssh_pass="1234" ansible_become_pass="1234"

[tier1_agents]
digitafrica-edge-node2 ansible_host=10.64.45.179 ansible_ssh_pass="1234" ansible_become_pass="1234"


[tier1:children]
tier1_server
tier1_agents

[all:vars]
ansible_user=ubuntu
ansible_become=true
```

Depending on the type of the deployment (Tier-0/1) only the respective configs need to be present.

### Key variables in `inventories/prod/group_vars/all.yml`

| Variable | Default | Description |
|---|---|---|
| `k3s_disable_traefik` | `false` | `false` enables Traefik Ingress. `true` disables it (services fall back to NodePort). |
| `k3s_disable_servicelb` | auto-derived | Automatically set to `true` when Traefik is enabled. Do not set manually. |
| `tier0_expose_mode` | `ingress` | `ingress` routes Tier-0 services through Traefik. `nodeport` exposes them on raw ports (backward compatible). |
| `jupyterhub_public_url` | `http://<host>/jupyter` | **Must match the server IP or DNS name.** Used to generate OIDC callback URLs and the final access URL. |

> **Important:** Change `jupyterhub_public_url` to match your actual server address before deploying. For example:
> ```yaml
> jupyterhub_public_url: "http://10.64.45.176/jupyter"
> ```
> If you use a DNS name instead of an IP, also add the hostname to `tls_domains`.

---

## Networking — Traefik Ingress

All services are exposed through the **Traefik Ingress controller** that ships with k3s. There are no NodePort assignments to manage.

| Service | Path | Notes |
|---|---|---|
| JupyterHub (Tier-0 k3s) | `http://<host>/jupyter/` | Single-node k3s |
| JupyterHub (Tier-1) | `http://<host>/jupyter/` | Multi-node k3s |
| Model cache (Tier-0) | `http://<host>/models/` | Static file server |

Visiting the path without a trailing slash (e.g. `/jupyter`) redirects automatically to `/jupyter/`.


### Falling back to NodePort

If you want to skip Traefik and use plain NodePort (e.g. for debugging or constrained environments), set these in `group_vars/all.yml`:

```yaml
k3s_disable_traefik: true
tier0_expose_mode: "nodeport"
```

Services will then be reachable at `http://<host>:30888` (JupyterHub) and `http://<host>:30080` (model cache).

---

## Deploying the BP

To install on the nodes declared at the hosts.ini file, ensure that the deploying machine has ```ansible``` and ```ssh-pass``` installed, and ssh access to all the machines.

```bash
ansible-galaxy collection install -r requirements.yml
```

To install the BP, use the following command:

```bash
ansible-playbook -i inventories/prod/hosts.ini playbooks/site.yml
```

You can uninstall the current version of the BP using the following command:

```bash 
ansible-playbook -i inventories/prod/hosts.ini playbooks/site.yml -e digitafrica_uninstall=true
```

# OIDC Authentication Implementation

## Overview

In the Tier-1 deployment, authentication has been implemented using **OpenID Connect (OIDC)**.

JupyterHub is configured to delegate authentication to an external Identity Provider (IdP).  
In this setup, the IdP is **Keycloak**.

This replaces the previous DummyAuthenticator and allows real user-based authentication.

---

## What is OIDC?

OpenID Connect (OIDC) is an authentication protocol built on top of OAuth 2.0.

It allows applications (such as JupyterHub) to authenticate users through an external Identity Provider (such as Keycloak).

The flow is:

1. User accesses JupyterHub.
2. JupyterHub redirects the user to Keycloak.
3. User logs in on Keycloak.
4. Keycloak returns an authentication token to JupyterHub.
5. JupyterHub validates the token and creates a user session.

---

## Key Components Explained

### Client ID

The `client_id` identifies JupyterHub inside Keycloak.

It tells Keycloak:
“This authentication request is coming from the JupyterHub application.”

It must match the Client ID configured in Keycloak.

---

### Client Secret

The `client_secret` is a private credential shared between JupyterHub and Keycloak.

It is used to:
- Prove that JupyterHub is a trusted application
- Secure the token exchange process

This value must be kept confidential.

---

### Issuer URL

The `issuer_url` points to the Keycloak realm endpoint

JupyterHub uses this to construct:

- Authorization endpoint
- Token endpoint
- Userinfo endpoint

---

### OAuth Callback URL

The callback URL is where Keycloak redirects the user after successful login

This must be configured in Keycloak under:

- Valid Redirect URIs
- Web Origins

---

## Implementation Details

The OIDC authenticator was implemented in the Helm values file:

```yaml
hub:
  config:
    JupyterHub:
      authenticator_class: generic-oauth

    GenericOAuthenticator:
      client_id: "{{ oidc_client_id }}"
      client_secret: "{{ oidc_client_secret }}"
      authorize_url: "{{ oidc_issuer_url.rstrip('/') }}/protocol/openid-connect/auth"
      token_url: "{{ oidc_issuer_url.rstrip('/') }}/protocol/openid-connect/token"
      userdata_url: "{{ oidc_issuer_url.rstrip('/') }}/protocol/openid-connect/userinfo"
      scope: {{ oidc_scope | to_json }}
      username_claim: "{{ oidc_username_claim }}"
      tls_verify: false
      validate_server_cert: false
      oauth_callback_url: "{{ jupyterhub_public_url.rstrip('/') }}/hub/oauth_callback"

    Authenticator:
      allow_all: true
```

These variables are defined in the Ansible inventory or group variables and rendered into the Helm chart during deployment.

# Reference

For related architecture and identity integration design, refer to:

DigitAfrica User Portal:
https://gitlab.inria.fr/digitafrica/blueprints/services/user-portal