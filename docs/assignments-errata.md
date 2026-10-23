# Errata: Assignment 1–3 and the K8s setup tutorial

Problems found in the original PDFs (`Assignment 1.pdf`, `Assignment 2.pdf`, `Assignment 3.pdf`). The Markdown conversions (`Assignment 1.md` … `Assignment 3.md`) deliberately keep the original text, so these issues are still present there; the one sentence they change is listed under “Changed in the Markdown”. Links were checked on 2026-10-19. The K8s setup tutorial is covered in the last section.

## Assignments: content errors

| Document | Location | Original text | Problem / suggested fix |
|---|---|---|---|
| Assignment 3 | 3.2 → Grading → Report, item c | “Anything you did for the bonus part of assignment **3.1**.” | Copy-paste from 3.1; should be **3.2**. |
| Assignment 3 | Introduction | “Then, in the second **assignment**, you will setup a Kubernetes cluster” | Should be “in the second **part**”. |
| Assignment 2 | Authentication table, `/users - PUT` | `:username–a` | En dash instead of the hyphen used everywhere else (`:username-a`). |
| Assignment 2 | URL shortener table, `/ - DELETE` | `403,”forbidden”` | Opening quote is a closing quote; elsewhere `403,“forbidden”`. |
| Assignment 1 | Body text | “Implementing the specification will earn you **a** 8.” | “an 8”. |
| Assignment 1 | Assignment | “The idea of this service **is act** as a repository of URLs” | “is to act”. |
| Assignment 1 | Background | “has emerged **in the few years ago**” | “in the past few years”. |
| Assignment 1 | Tips, item b | “you must support **to** the specification” | “you must adhere to the specification” / “support the specification”. |
| Assignment 2 | Background | “a user can login once **keep** the token” | “login once **and** keep the token”. |
| Assignment 2 | Report, item b.iv | “any of the **question** i - iii” | “questions”. |
| Assignment 1–3 | Important Notes | “**detailled** explanation” | “detailed”. |
| Assignment 3 | Submission, item 2 | “**A**lso explain …” | Only the letter “A” is bold (formatting slip). |

## Changed in the Markdown

| Document | Location | Original text | Markdown text | Reason |
|---|---|---|---|---|
| Assignment 1 | Assignment, after the specification table | “…the specification says nothing about the contents of the body of a request; this is left for you to decide.” | “…the specification says nothing about the contents of the body of a request; the grading script (*test_api.py*) sends its requests in a fixed format, so read it to see what your service must accept.” | The grading script sends `{"value": URL}` for `POST /` and `{"url": URL}` for `PUT /:id`. A service that expects other fields would lose points for a choice the original text allows. The workshop's advanced track says the same. |

## Assignments: links

| Document | Reference | Link | Status |
|---|---|---|---|
| Assignment 1 | [2] Jersey web page | https://jersey.java.net | Dead (domain no longer resolves). Current: https://eclipse-ee4j.github.io/jersey/ |
| Assignment 1 | [3] Jersey JAX-RS tutorial | http://theopentutorials.com/… | Dead (HTTP 500). |
| Assignment 1 | [5] bhaveshthaker.com | http://www.bhaveshthaker.com/13/… | Dead (domain no longer resolves). |
| Assignment 1 | [6] IBM developerWorks | http://www.ibm.com/developerworks/library/wa-aj-tomcat/ | Article removed; redirects to a generic IBM Developer page. |
| Assignment 2 | [4] Introduction to microservices | https://www.nginx.com/blog/introduction-to-microservices/ | Article removed; redirects to the F5 NGINX product page. |
| Assignment 3 | Footnote 1 | http://sewiki.iai.uni-bonn.de/teaching/lectures/ise/2008/assignment_i | Dead (no response). |
| Assignment 1 | [1] Flask | http://flask.pocoo.org/, …/en/2.0.x/quickstart/ | Works (redirects to the current Flask docs). |
| Assignment 1 | [7], [9] mkyong.com | http://www.mkyong.com/webservices/jax-rs/… | Blocks automated checks (HTTP 403); could not be verified, probably still opens in a browser. |
| Assignment 2 | [3] medium.com | https://medium.com/swlh/… | Blocks automated checks (HTTP 403); could not be verified, probably still opens in a browser. |

All other links in the three assignments returned HTTP 200.

## K8s setup tutorial

`k8s-setup-commands.md` keeps the text of `k8s-setup-commands.pdf`. `k8s-setup-commands-updated.md` is the corrected version for students. Command numbers are given as PDF → updated version.

| Topic | PDF | Problem | Updated version |
|---|---|---|---|
| Debian 11 package sources | not covered | Debian 11 is end-of-life. Its security updates are only on archive.debian.org, so `apt-get install` fails with `404 Not Found`. | new commands 3–4 |
| Docker repository text | “two commands”, “command 6”, “command 9”, “docker.download.com” | There are four commands (4–7), the package list update is command 8, and the host is download.docker.com. | commands 6–11 |
| containerd | not covered | The `containerd.io` package disables the CRI plugin, so `kubeadm init` fails. | new commands 16–18 |
| IP forwarding and swap | not covered | Required by kubeadm and the kubelet. | new commands 19–22 |
| Kubernetes package repository | 15–16 (`apt.kubernetes.io`) | Shut down; `apt-get update` fails with `404`. | 24–25 (`pkgs.k8s.io`, v1.37) |
| `kubeadm init` | 19 | In `IP=$(…) sudo kubeadm init … $IP` the shell expands `$IP` before assigning it, so kubeadm gets an empty address. | 28–30 |
| kubelet arguments | 20–21, 23–24 | `--network-plugin` and `--pod-infra-container-image` no longer exist; the kubelet does not start. | 31–32, 35–37 (`--node-ip` in `/etc/default/kubelet`) |
| Expired join token | link only | | new command 34 |
| Calico | 28–29 (`docs.projectcalico.org`) | Redirects to the archived Calico 3.25. | 41–43 (Calico v3.33.0) |
| Restarting pods | 36–38 (`docker ps`, `docker restart`) | Docker no longer sees the Kubernetes containers. | 51–52 |
| Removing images after a reset | 42–43 (`docker container prune`, `docker image prune -a`) | Does not remove the images Kubernetes uses. | 56–57 (`crictl rmi --prune`) |
| Downgrading | 44–49 (example `1.19.6-00`) | One repository per minor version, new version format, held packages must be unheld first. | 58–66 |
| Disk usage | 51 | `–h` and `–n` contain en dashes; the command fails when copied. | 68 |
| Typos | “sends up the cluster”, “Control Network Interface”, `–n`, “sorted from low-to-high” | | fixed |

### Testing

On 2026-10-21 all commands in `k8s-setup-commands-updated.md` were run in order on a two-node cluster (one control node, one worker) for Debian 11, 12 and 13, with Docker Engine 29, containerd 2.3/2.4, Kubernetes v1.37.1 and Calico v3.33.0. Afterwards both nodes were `Ready`, all system pods were running, cluster DNS worked, and a Deployment with 3 replicas was reachable through a NodePort on both nodes. On Debian 12, resetting the cluster, downgrading to v1.36.5 and setting it up again were tested as well.

The nodes were systemd containers on Docker Desktop (arm64), not the OpenLab VMs. Differences from a real VM: the network interface was `eth0` instead of `ens3`, `kubeadm init` and `kubeadm join` needed `--ignore-preflight-errors=SystemVerification` (the containers have no kernel configuration), and swap, mount propagation and the DNS server were set up to match a VM. The SSH login/logout steps (1, 2, 14) and the interactive `watch` (44, 45) were not run as such. A dry run on one set of OpenLab VMs before the lab is still recommended.
