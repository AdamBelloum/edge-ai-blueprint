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