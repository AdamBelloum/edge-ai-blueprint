## Install everything
```ansible-galaxy collection install -r requirements.yml```
```ansible-playbook -i inventories/prod/hosts.ini playbooks/site.yml```

### Uninstall everything
```ansible-playbook -i inventories/prod/hosts.ini playbooks/site.yml -e digitafrica_uninstall=true```

### Uninstall and wipe data
```ansible-playbook -i inventories/prod/hosts.ini playbooks/site.yml -e digitafrica_uninstall=true -e remove_data=true```

### Uninstall only Tier-0 notebooks (example: limit)
```ansible-playbook -i inventories/prod/hosts.ini playbooks/site.yml -e digitafrica_uninstall=true --limit tier0```

### Install only Tier-1 k3s/apps (example)
```ansible-playbook -i inventories/prod/hosts.ini playbooks/site.yml --limit tier1```