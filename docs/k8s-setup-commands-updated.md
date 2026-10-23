# <span style="color:#17365d; font-weight:normal">K8s setup on Debian 11 / 12 / 13</span>

In this document, we will walk you through the process of setting up your very own Kubernetes<sup>1</sup> cluster on the VMs provided by the University.

<span style="color:#ff0000">Note: While it’s very tempting to do this alone, this process is extremely impractical to do thrice; thus, we highly recommend you follow the steps in this document together with everyone in your group. This way, all of you get the experience of setting up a Kubernetes cluster.</span>

Your TA should have emailed the credentials of the VMs (IP address, username and password) to you. To login to your VMs, use the following command:

1. `ssh <username>@<IP>`

And then enter your password.

You are now logged in on your VM; every command you run this way, you run on the VM instead of your local machine.

To logout again, use:

2. `exit`

## <span style="color:#345a89">Conventions</span>

The rest of this document assumes that you are at least a little familiar with Unix shells on Debian or Ubuntu. If you aren’t, one of your team members probably is, and can explain the terms or procedures you don’t understand.

That said, this document does try to explain the commands and procedures used as best as possible. Feel free to skip over the explanations if you already know them; but they might help you to understand what exactly is going on.

Any text in `monospace` is something that is a command or that directly relates to a command (like command output).

Additionally, the text is also full of references with background material or sources. Most of them are as footnotes<sup>2</sup>, but when referenced explicitly in the text, they can also be given directly as a [link](https://www.youtube.com/watch?v=dQw4w9WgXcQ).

## <span style="color:#345a89">Debian 11 only: switching to the archive mirror</span>

First, check which Debian version your VM runs:

3. `grep VERSION_CODENAME /etc/os-release`

If this prints `VERSION_CODENAME=bookworm` (Debian 12) or `VERSION_CODENAME=trixie` (Debian 13), skip to the next section.

If it prints `VERSION_CODENAME=bullseye` (Debian 11), you have to do one extra step. Debian 11 reached its end of life in August 2026, and its security updates have been moved to `archive.debian.org`. The default package sources still list them, but downloading them fails with `404 Not Found`. Point apt to the archive instead:

4. `printf 'deb http://archive.debian.org/debian bullseye main\ndeb http://archive.debian.org/debian-security bullseye-security main\n' | sudo tee /etc/apt/sources.list`

Do this on every VM that runs Debian 11.

## <span style="color:#345a89">Installing Docker</span>

Kubernetes is merely an orchestrator for containers; the containers themselves are run in a third-party container engine. In this tutorial, we will install the Docker<sup>3</sup> engine (based on [this](https://docs.docker.com/engine/install/debian/) document). Kubernetes will use *containerd*, the container runtime that comes with Docker; you can still use the `docker` command yourself, for example to build and test your images.

First, make sure that the dependencies for the installation process are installed:

5. `sudo apt-get update && sudo apt-get install ca-certificates curl gnupg lsb-release`

Note that apt will probably ask you if you are sure you want to install these packages and their dependencies. You probably are, so type ‘y’ and then hit enter. To avoid this, we will use the ‘-y’ flag in subsequent commands that do this automatically.

Then, we add Docker’s repository to Debian’s apt package manager. To do so, use the following four commands:

6. `sudo install -m 0755 -d /etc/apt/keyrings`
7. <code>curl -fsSL <a href="https://download.docker.com/linux/debian/gpg">https://download.docker.com/linux/debian/gpg</a> | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg</code>
8. `sudo chmod a+r /etc/apt/keyrings/docker.gpg`
9. ```
   echo \
     "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
     "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
     sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
   ```

Commands 6 to 8 download the GPG<sup>4</sup> key for Docker’s repository, and command 9 modifies apt’s files to add the repository.

Now, we can update the package list (command 10) and then download the Docker engine and related tools (command 11):

10. `sudo apt-get update`
11. `sudo apt-get -y install docker-ce docker-ce-cli containerd.io`

After running command 10, you should now see the Docker repository (download.docker.com) being refreshed as well.

If you are curious what you are installing exactly, this is what each of the three packages does<sup>5</sup>:

- **containerd.io:** The actual thing that manages and works with containers. This is also the main part that is used by Kubernetes.
- **docker-ce:** Interface to interact with containerd.io (instead of interacting to it with Kubernetes). Although this is called an interface, it itself runs as a daemon (service) on the node, so cannot be interacted with directly.
- **docker-ce-cli:** The actual command-like interface to docker-ce that you use when running `docker` commands.

The Docker engine is now installed. However, we would like to do two additional steps before we start to use it: first, we want to auto-start the Docker engine once the VM boots; and secondly, we want to use the docker-related commands without `sudo`-rights.

The first step can be done by running:

12. `sudo systemctl enable docker`

Which “enables” the Docker engine (named `docker`) to start up once the system does.

The second tweak requires two steps:

13. `sudo usermod -aG docker "$USER"`
14. `exit`

The first command adds your user (`$USER`) to the docker group, which is the group of all users who can use docker without sudo. Then, you need to logout of your VM and login again (`exit`, then run the SSH command) to refresh your permissions.

You can check that you have the correct permissions by running:

15. `groups`

You should now see ‘`docker`’ in the list.

You should repeat this process on every VM you want to add to the Kubernetes cluster (which is probably all of them).

## <span style="color:#345a89">Preparing containerd and the node for Kubernetes</span>

Kubernetes does not talk to Docker itself, but directly to containerd, using the Container Runtime Interface (CRI)<sup>6</sup>. The `containerd.io` package from Docker’s repository ships a configuration file in which exactly this CRI plugin is disabled, so we replace it with containerd’s default configuration:

16. `containerd config default | sudo tee /etc/containerd/config.toml > /dev/null`
17. `sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml`
18. `sudo systemctl restart containerd`

Command 17 tells containerd to use systemd to manage the resources (CPU, memory) of containers. kubeadm configures the kubelet to do the same, and both have to match<sup>7</sup>.

Kubernetes also needs the node to forward network packets between its network interfaces, and it requires that swap is turned off:

19. `echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/k8s.conf`
20. `sudo sysctl --system`
21. `sudo swapoff -a`
22. `sudo sed -i '/ swap / s/^/#/' /etc/fstab`

Command 19 writes the setting to a file so that it survives a reboot, and command 20 applies it right away. Command 21 turns swap off, and command 22 comments out any swap entry in `/etc/fstab` so that swap stays off after a reboot (if your VM has no swap, these two commands simply do nothing).

Like for Docker, you have to do this on every node.

## <span style="color:#345a89">Installing Kubernetes</span>

The next step is installing the Kubernetes software which you will use to run your cluster. This does not make your VMs a cluster, however; in this section, we only install the software which we will use to make a cluster in the next section.

We will follow the “Installing kubeadm, kubelet and kubectl” section from [this](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/#installing-kubeadm-kubelet-and-kubectl) document.

First, install a few extra dependencies that we didn’t install for Docker:

23. `sudo apt-get -y install apt-transport-https net-tools`

Next, we add another repository for Kubernetes as well, like we did for Docker. This can be done by running:

24. `curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.37/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg`
25. `echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.37/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list`

Command 24 downloads the GPG key for this repository, and command 25 adds it to apt’s database (very similar to the commands for Docker). Note the `v1.37` in both commands: every minor version of Kubernetes has its own repository<sup>8</sup>, so this repository only ever offers Kubernetes 1.37.x.

With the repository added, install the required packages. For Kubernetes, these are<sup>9</sup>:

- **kubelet:** A daemon (service) running on each node that launches and removes images and containers.
- **kubectl:** The interface to the control plane that can be used to manage pods, services, etc.
- **kubeadm:** Tool that helps setting a cluster up by automatically generating the required configuration files.

We can install them with apt-get again:

26. `sudo apt-get update && sudo apt-get -y install kubelet kubectl kubeadm`

Be sure to run `sudo apt-get update` as well, since apt won’t download the package lists from the new repository otherwise (resulting in errors like “package kubelet is unknown”).

This time, though, we want to notify apt that we don’t want it to update the packages automatically. We do this by marking the packages as *hold:*

27. `sudo apt-mark hold kubelet kubectl kubeadm`

We do this because updating a Kubernetes cluster might break all sort of dependencies between nodes, and so we don’t want apt to do this at arbitrary moments. Additionally, Kubernetes provides its own tools<sup>10</sup> for upgrading the cluster.

Like for Docker, you have to install Kubernetes on every node that you want added to your cluster.

## <span style="color:#345a89">Setting up your cluster: Control node</span>

We can now finally move to setting up your cluster.

As you know, a Kubernetes cluster exists of two types of nodes: control nodes (part of the control plane) and worker nodes.

This means that you have to divide your VMs into control and worker nodes.

Because you only have three VMs, we suggest you to setup one control node and two worker nodes.

To begin, first <ins>SSH into your control node</ins> so that all subsequent commands are executed there.

Then, store the IP address of the control node in a shell variable called `IP`, and check that it worked:

28. `IP=$(ip -4 -o a | grep -i "ens3" | cut -d ' ' -f 2,7 | cut -d '/' -f 1 | awk '{print $2}')`
29. `echo $IP`

Command 29 should print exactly one IP address. If it prints nothing, your network interface is not called `ens3`: run `ip -4 -o a`, look up the name of the interface that has the VM’s IP address (for example `eth0` or `enp1s0`), and replace `ens3` in command 28 with that name.

We use kubeadm to setup the control plane for us. To let it do so, run:

30. `sudo kubeadm init --pod-network-cidr=192.168.0.0/16 --control-plane-endpoint=$IP --apiserver-cert-extra-sans=$IP`

These commands might look scary, so we’ll break them down for you:

- `IP=$(ip -4 … awk '{print $2}')`: Fetches the IP address of the current node and stores it in the variable `IP`. To fully understand how this works, we recommend you run the part in between the brackets incrementally; first everything up to the first bar, then everything (including the first part) up to the second bar, etc. You should be able to see how each part reduces the output from `ip`-tool until only the IP is left.
- `sudo kubeadm init`: Tells the kubeadm to initialize a new cluster on your control node.
- `--pod-network-cidr`: We tell kubeadm that we would like to use a particular subnet (range of IP addresses) for the pod network. In a Kubernetes cluster, each pod will be assigned its own IP, and this subnet determines how those IPs look like.
- `192.168.0.0/16`: The subnet to use for the pods. The `/16` means that the first 16 bits (the first two numbers, since each number is 8 bits long) are set; thus, all pods will be assigned an IP that starts with ‘`192.168`’.
- `--control-plane-endpoint`: This tells kubeadm the IP of the control plane. Because we use only one node, it should be the IP of the node you are running this command on.
- `$IP`: This will expand to the IP address we stored in command 28. We thus specify the current node as the control plane endpoint.
- `--apiserver-cert-extra-sans`: This tells kubeadm to add the following string of IP addresses and hostnames to the certificates that Kubernetes generates.
- `$IP`: Once again, this will expand to the IP address we stored in command 28. This time, it specifies that external hosts may connect to this cluster via this IP as well.

Note that commands 28 and 30 have to be run in the same shell session, because `$IP` only exists in the shell where it was set. Also do not merge them into one line (`IP=$(…) sudo kubeadm init … $IP`): the shell expands `$IP` *before* it assigns the new value, so kubeadm would receive an empty IP address.

The command will run for a while as it sets up the cluster (potentially a few minutes or so). Eventually, you’ll see something like:

```
...

You can now join any number of control-plane nodes by copying certificate authorities
and service account keys on each node and then running the following as root:

  kubeadm join <IP>:6443 --token <token> \
        --discovery-token-ca-cert-hash <hash> \
        --control-plane

Then you can join any number of worker nodes by running the following on each as root:

kubeadm join <IP>:6443 --token <token> \
        --discovery-token-ca-cert-hash <hash>
```

Make sure that you copy the <ins>**last**</ins> join command (including the backslash and the `--discovery-token-ca-cert-hash` line) and store it somewhere temporarily. This command will be used to join this cluster from another node as a worker node. The other command (the first one) can be used to extend the cluster with more control nodes; but since you have only one of those, this is not relevant for you. Thus, again, copy only the <ins>last</ins> one.

Before adding other nodes, we have to tell the kubelet on the control node which IP address it should use:

31. `echo "KUBELET_EXTRA_ARGS=--node-ip=$IP" | sudo tee /etc/default/kubelet`
32. `sudo systemctl restart kubelet.service`

These commands change the arguments that are passed to the kubelet service on the control node. The first (command 31) writes the new arguments to the `/etc/default/kubelet` file, which the kubelet service reads when it starts, and the second restarts the kubelet service so it uses those arguments.

But what are the arguments that we are setting here? Once again, we break down the command:

- `KUBELET_EXTRA_ARGS=--node-ip=$IP`: Tells kubelet the IP-address of the node that its running on. `$IP` once again expands to the IP address from command 28. This is mostly important if your VM has more than one network interface; otherwise, kubelet would pick an address by itself.
- The rest of the command is basically there to write the arguments to the file `/etc/default/kubelet`, and is a bit of shell magic:
  - `echo`: Echoes whatever follows back to *stdout*<sup>11</sup>. You can use this command yourself to have the computer repeat a silly message back to you (try ‘`echo "Hello there"`’).
  - `|` (the bar after the arguments): *pipes*<sup>12</sup> the stdout of the command before it (the echo command) to *stdin*<sup>13</sup> of the command after it. This pattern of ‘`echo <text> | …`’ is often used to automatically provide input to some program you would otherwise have to manually type.
  - `sudo tee /etc/default/kubelet`: Writes whatever is passed to it on stdin to the given file. We need `sudo tee` instead of `sudo echo … > file`, because the redirection (`>`) would be executed by your own shell, which is not allowed to write to that file.

After you have executed these two commands, it’s time to initialize the worker nodes.

## <span style="color:#345a89">Setting up your cluster: Worker nodes</span>

The next few steps will have to be repeated on each of your worker nodes.

First, logout of your control node if you were still logged-in (run `exit`). Then, login on the worker node you’d like to add. You should execute the following commands on that same node.

Now you should retrieve the ‘`kubeadm join …`’ command that you copied from the control node. It will probably look something like this:

33. ```
    sudo kubeadm join <IP>:6443 --token <token> \
    --discovery-token-ca-cert-hash <hash>
    ```

(Pay attention to also copy the backslash and the `--discovery-token-ca-cert-hash` line).

Note that we have prepended this command with `sudo`, whereas the command given to you by Kubernetes is not; you should do this too, or else the command will fail to run (saying something about not having enough permissions).

<span style="color:#006fc0">Tip: If you still forgot to prepend sudo, simply run: ‘`sudo !!`’; the ‘`!!`’ automatically expands to the previous command.</span>

This command logs in (`join`) on the node with IP-address `<IP>` and on port `6443`. The other two arguments function as a kind of credentials; this prevents anybody with access to that port to just joining the cluster. These will thus also be different every time someone runs `kubeadm init`. The token is only valid for 24 hours.

If you have no longer access to the original join command from `kubeadm init`, or if the token has expired, run the following on the control node to print a new one:

34. `sudo kubeadm token create --print-join-command`

(See also [this](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/#join-nodes) page.)

Once the join command has completed, it should say something along the lines of “This node has joined the cluster”. With that done, you can set the kubelet arguments on the worker node too, just like you did on the control node:

35. `IP=$(ip -4 -o a | grep -i "ens3" | cut -d ' ' -f 2,7 | cut -d '/' -f 1 | awk '{print $2}')`
36. `echo "KUBELET_EXTRA_ARGS=--node-ip=$IP" | sudo tee /etc/default/kubelet`
37. `sudo systemctl restart kubelet.service`

(Note that, while the commands are the same, the arguments technically aren’t; the IP will differ depending on which node you run it. If you had to replace `ens3` on the control node, do the same here.)

You should repeat this process on every node you intend to add as a worker node.

## <span style="color:#345a89">Setting up your cluster: The conclusion</span>

There are only a few steps left to setting up your cluster. Run them on the control node.

First, we finally execute the three commands that the `kubeadm init`-command itself recommends to us:

38. `mkdir -p $HOME/.kube`
39. `sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config`
40. `sudo chown $(id -u):$(id -g) $HOME/.kube/config`

These three commands basically copy the default configuration for the kubectl command from the root user (located at `/etc/kubernetes/admin.conf`) to the directory for the current user (`/home/<username>/.kube/config`). Command 38 creates the target directory (`$HOME` expands to your user’s directory), command 39 copies the configuration file and command 40 changes the file’s owner to you (allowing you access to the file).

To elaborate a little on command 40:

- `sudo chown`: Runs the shell tool to **ch**ange **own**ership (as sudo, because the file currently belongs to the super user).
- `$(id -u):$(id -g)`: Defines the `<user>:<group>` to transfer the ownership to. The correct user ID for your user is obtained by `$(id -u)`, and the ID for your user group is obtained by `$(id -g)` (every user also has a group with the same name; check `groups` again).

The only thing that remains to be done is to select a *networking plugin*<sup>14</sup>. This is a third-party plugin that implements the network between the pods according to the CNI (Container Network Interface) specification defined by Kubernetes.

In this tutorial, we’ll setup Calico<sup>15</sup>, one of the most used and versatile network plugins for Kubernetes.

Installing a network plugin is usually rather straightforward. For most plugins, this is simply applying a configuration YAML<sup>16</sup> in much like the same way you would deploy a service yourself.

For Calico, however, this is slightly more complicated, as it requires *three* YAML configuration files to be applied:

41. <code>kubectl create -f <a href="https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/v3_projectcalico_org.yaml">https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/v3_projectcalico_org.yaml</a></code>
42. <code>kubectl create -f <a href="https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/tigera-operator.yaml">https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/tigera-operator.yaml</a></code>
43. <code>kubectl create -f <a href="https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/custom-resources.yaml">https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/custom-resources.yaml</a></code>

The first file teaches Kubernetes the new resource types that Calico uses (so-called Custom Resource Definitions), the second installs the Calico *operator*, a program that installs and manages Calico for you, and the third one tells the operator how Calico should be configured. Its default pod network is `192.168.0.0/16`, which is exactly the subnet we passed to `kubeadm init`. (Command 41 is for Kubernetes 1.36 and newer; if you downgraded to Kubernetes 1.34 or 1.35, use `v3_projectcalico_org-v1beta1.yaml` instead of `v3_projectcalico_org.yaml`.)

And that’s it! Your Kubernetes cluster should now be set up. It can take a few minutes until all nodes are `Ready`.

If you like, you can see your nodes coming online by running:

44. `watch kubectl get nodes`

The watch-command simply calls the command you give it every two seconds and displays its results. Press Ctrl+C to stop it.

The same can be done for all the system pods:

45. `watch kubectl get -A pods`

Once those are all online, you should be able to run your own services as is required by the assignment.

## <span style="color:#345a89">Troubleshooting</span>

Unfortunately, setting up a cluster won’t always go right. This can be due to entering commands wrong or in the wrong order, or due to external things like network errors.

Please, please, *please* try to find a solution yourself first before asking any of the TAs. Not only does this reduce workload for the TAs, finding solutions yourself is also much more educational and a really important skill to practice.

Good resources on Kubernetes include the many GitHub issues<sup>17</sup> that have been filed over the years or the official Kubernetes documentation<sup>18</sup>. But probably even more efficient than visiting those locations is just to use a search-engine like Google to search across all sites.

That said, there are a few techniques that we list here to help you debug the problem and solve some issues:

**Inspecting logs**

Like Docker, Kubernetes keeps track of the output of the containers it runs as logs.

To inspect them, first determine the pod name by running:

46. `kubectl get pods`

This returns all of your pods. Alternatively, you can use the `-A` flag to specify you want to see pods from *all* namespaces, including the system namespaces:

47. `kubectl get -A pods`

Once you know the name of the pod to inspect, run:

48. `kubectl logs <pod_name>`

Note, though, that this command only searches in the default namespaces (usually called `default`). However, as stated before, not all pods that run in your cluster belong to that namespace, and this command will fail to find them. To fix this, use the `-n` or `--namespace` option:

49. `kubectl -n <namespace> logs <pod_name>`

This should then give you the output of the pod since it started running.

Also note that, while Kubernetes’ “Ready” flag is very useful, pods can still report that they are ready and then encounter issues (especially your own services). It thus often makes sense to also look in seemingly healthy pods if you cannot find the problem in non-ready ones.

If the problem is with a node itself (for example, it stays `NotReady`), look at the logs of the kubelet on that node:

50. `sudo journalctl -u kubelet -n 50`

**Restarting pods**

Sometimes, Kubernetes pods can benefit from a reboot, like any service or computer.

Because Kubernetes runs its containers through containerd and not through Docker, `docker ps` and `docker restart` do not see them. Instead, simply delete the pod; if it is managed by a Deployment (like your own services), Kubernetes immediately creates a fresh replacement:

51. `kubectl delete pod <pod_name>`

To restart all pods of a Deployment at once, run:

52. `kubectl rollout restart deployment <deployment_name>`

You can see the result with `kubectl get pods` again.

**Resetting your cluster**

You can relatively easily tear a cluster down and then set it up again. This is useful if you change your mind midway through the setup process or if kubeadm crashed after the preflight-phase.

To reset your cluster, login to each node that is part of your cluster, and run the following commands on each of them:

53. `sudo kubeadm reset`

(You will be prompted if you are sure; type ‘y’, then hit enter)

54. `sudo rm -rf /etc/cni /var/lib/cni /opt/cni /var/log/calico /var/lib/calico /etc/kubernetes`
55. `rm -rf ./.kube`

The first command instructs kubeadm to remove most of the cluster, and the other two commands remove any configuration files that are left and that are not removed by kubeadm.

Once the files are cleared, you should restart your node (`sudo reboot`) to also clear any rules that Kubernetes may have added to your routing tables.

If you want to be extra thorough, you can also remove all container images that Kubernetes downloaded. For this, you need the `crictl` tool:

56. `sudo apt-get -y install cri-tools`
57. `sudo crictl --runtime-endpoint unix:///run/containerd/containerd.sock rmi --prune`

Once the reboot of all nodes is complete, you can setup your cluster again as specified from “Setting up your cluster: Control node” and onwards.

**Downgrading your cluster**

Sometimes, the newer Kubernetes versions have bugs. For example, a bug in a new version may cause some feature (like NodePorts) to fail in some situations.

One way to work around those bugs is to downgrade your Kubernetes cluster.

First, tear the cluster down as described in the “Resetting your cluster” section (remember to do so for all nodes!).

Then, on all nodes, remove the existing Kubernetes installation:

58. `sudo apt-mark unhold kubelet kubeadm kubectl`
59. `sudo apt-get -y remove --purge kubelet kubeadm kubectl`

Also remove the package’s dependencies to force apt to download the proper versions for those too:

60. `sudo apt-get -y autoremove`

Because every minor version of Kubernetes has its own repository, you now have to switch to the repository of the version you want, for example 1.36:

61. `echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.36/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list`
62. `sudo apt-get update`

To see a list of available versions, you could run:

63. `sudo apt-cache madison kubeadm`

(the same command works for kubelet or kubectl too)

Then, you can re-install Kubernetes again, but now with the desired versions:

64. `sudo apt-get -y install kubelet=<version> kubeadm=<version> kubectl=<version>`

Note that all versions have to be the same. For example, to install version 1.36.5-1.1:

65. `sudo apt-get -y install kubelet=1.36.5-1.1 kubeadm=1.36.5-1.1 kubectl=1.36.5-1.1`

Don’t forget to re-mark the packages as hold, to prevent apt from upgrading it:

66. `sudo apt-mark hold kubelet kubeadm kubectl`

Once that is installed, you can go back to “Setting up your cluster: Control node” and follow the tutorial from there onwards.

**Freeing space**

One final issue you may run into, especially when using the more resource-limited VMs, is that the disk space may quickly get used up by Docker. This is because Docker tends to cache a lot, especially old version of images you rebuilt or old containers.

One of the easiest way to clean up disk space is to run:

67. `docker system prune -af`

(You can omit the `-f` from the command, in which case you will be prompted if you are sure)

This will clean all the unused containers, systems, volumes and other Docker resources. Essentially, it will only leave you with the currently running containers and everything needed to do so. Note that this only cleans what *Docker* stored; images that Kubernetes downloaded are cleaned with command 57 instead.

Another tip when you’re running low on disk space is to use the `du`-command, which gives you the **d**isk **u**sage of a particular directory. By using just a little bit of shell-fu, you can get the biggest files and directories on your system:

68. `sudo du -h -x / 2>/dev/null | sort -rh | head -n 10`

This command will list the disk usage (`du`) of files in the root directory (`/`), using human-readable size identifiers (`-h`; otherwise, you will see the raw number of bytes instead of KB, MB, etc). The `-x` keeps `du` on the root file system, so it does not descend into virtual file systems such as `/proc`, and `2>/dev/null` hides the error messages about files that disappear while `du` runs. The result of that is sorted from high-to-low (`sort -r`; the `-h` means it will sort based on the human-readable identifiers, not raw numbers) and then only take the top 10 of that (`head -n 10`). Finally, the `sudo` is only used to also search the contents of root-only directories, and is only necessary if you plan to search the whole filesystem instead of a local directory.

Once you found large files or folders this way, you can get more precise information by changing the ‘`/`’ in the command to be that of a particular folder.

---

<sup>1</sup> https://kubernetes.io/<br>
<sup>2</sup> Like this<br>
<sup>3</sup> https://www.docker.com/<br>
<sup>4</sup> Gnu Privacy Guard is an open source protocol for key exchange. Not too relevant to the course per-se but if you’re interested, you can find here a good introductory video: https://www.youtube.com/watch?v=DMGIlj7u7Eo<br>
<sup>5</sup> https://www.tutorialworks.com/difference-docker-containerd-runc-crio-oci/<br>
<sup>6</sup> https://kubernetes.io/docs/concepts/architecture/cri/<br>
<sup>7</sup> https://kubernetes.io/docs/setup/production-environment/container-runtimes/#containerd-systemd<br>
<sup>8</sup> https://kubernetes.io/blog/2023/08/15/pkgs-k8s-io-introduction/<br>
<sup>9</sup> https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/#installing-kubeadm-kubelet-and-kubectl<br>
<sup>10</sup> https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-upgrade/<br>
<sup>11</sup> https://www.howtogeek.com/435903/what-are-stdin-stdout-and-stderr-on-linux/<br>
<sup>12</sup> https://www.howtogeek.com/435903/what-are-stdin-stdout-and-stderr-on-linux/<br>
<sup>13</sup> https://www.howtogeek.com/435903/what-are-stdin-stdout-and-stderr-on-linux/<br>
<sup>14</sup> https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/network-plugins/<br>
<sup>15</sup> https://docs.tigera.io/calico/latest/getting-started/kubernetes/self-managed-onprem/onpremises<br>
<sup>16</sup> [https://www.redhat.com/en/topics/automation/what-is-yaml#:~:text=YAML%20is%20a%20data%20serialization,is%20for%20data%2C%20not%20documents.](https://www.redhat.com/en/topics/automation/what-is-yaml#:~:text=YAML%20is%20a%20data%20serialization,is%20for%20data%2C%20not%20documents.)<br>
<sup>17</sup> https://github.com/kubernetes/kubernetes/issues<br>
<sup>18</sup> https://kubernetes.io/docs/home/
