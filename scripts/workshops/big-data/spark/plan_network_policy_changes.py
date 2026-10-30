#!/usr/bin/env python3
"""Read-only ownership preflight from public NetworkPolicy JSON.

No cluster access. Reject foreign desired-name collisions and preserve foreign
legacy policies. This is snapshot validation, not an atomic mutation guard:
organisers must exclude concurrent policy writers during reconciliation.
"""
import json
import re
import sys

MANAGED = {
    'digitafrica.eu/managed-by': 'organiser',
    'digitafrica.eu/module': 'spark',
    'digitafrica.eu/workshop': 'big-data',
}
LEGACY = re.compile(r'^spark-direct-group-[0-9]+-pilot$')
NAME = re.compile(r'^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$')
NAMESPACE = re.compile(r'^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$')


def require(value, reason):
    if not value:
        raise ValueError(reason)


def metadata(policy, namespace):
    require(isinstance(policy, dict) and policy.get('kind') == 'NetworkPolicy',
            'expected_networkpolicy_object')
    data = policy.get('metadata')
    require(isinstance(data, dict), 'missing_policy_metadata')
    name = data.get('name')
    require(isinstance(name, str) and len(name) <= 253 and NAME.fullmatch(name),
            'invalid_policy_name')
    require(data.get('namespace') == namespace, 'policy_namespace_mismatch')
    labels = data.get('labels', {})
    require(isinstance(labels, dict), 'invalid_policy_labels')
    return name, data, all(labels.get(k) == v for k, v in MANAGED.items())


def plan(request):
    require(isinstance(request, dict), 'expected_request_object')
    namespace = request.get('namespace')
    require(isinstance(namespace, str) and len(namespace) <= 63
            and NAMESPACE.fullmatch(namespace), 'invalid_namespace')
    action = request.get('action')
    require(action in ('plan', 'apply', 'remove'), 'invalid_action')
    snapshot = request.get('current')
    require(isinstance(snapshot, dict) and snapshot.get('kind') in ('List', 'NetworkPolicyList')
            and isinstance(snapshot.get('items'), list), 'invalid_policy_snapshot')
    current, managed, legacy_preserved = {}, set(), set()
    for policy in snapshot['items']:
        name, data, owned = metadata(policy, namespace)
        require(name not in current, 'duplicate_existing_policy')
        current[name] = (data, owned)
        if owned:
            managed.add(name)
        elif LEGACY.fullmatch(name):
            legacy_preserved.add(name)

    desired = request.get('desired', [])
    require(isinstance(desired, list), 'invalid_desired_policies')
    require(action != 'remove' or not desired, 'remove_must_have_no_desired_policies')
    desired_names = set()
    for policy in desired:
        name, data, owned = metadata(policy, namespace)
        require(owned, 'desired_policy_missing_ownership_labels')
        require(not data.get('ownerReferences'), 'desired_policy_has_controller_owner')
        require(name not in desired_names, 'duplicate_desired_policy')
        desired_names.add(name)
        if name in current:
            require(current[name][1], 'foreign_desired_policy_collision: ' + name)

    delete_names = managed - desired_names
    # Do not overwrite/delete controller-owned objects even if labels match.
    for name in (desired_names & set(current)) | delete_names:
        require(not current[name][0].get('ownerReferences'),
                'policy_has_controller_owner: ' + name)
    return {
        'action': action,
        'namespace': namespace,
        'create_or_update': sorted(desired_names),
        'delete': sorted(delete_names),
        'preserve_unverified_legacy': sorted(legacy_preserved),
    }


def main():
    try:
        require(not sys.argv[1:], 'unsupported_arguments')
        raw = sys.stdin.read(2097153)
        require(len(raw) <= 2097152, 'request_too_large')
        result = plan(json.loads(raw))
    except (ValueError, TypeError, KeyError):
        print('ERROR: NetworkPolicy ownership preflight blocked; inspect the public policy snapshot and ownership.', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
