"""Dependency-injected execution sequence for a warm Spark-to-Livy transition.

No CLI or Docker operations are provided here. The future live caller must
supply a real participant fence, the shared submission lock, fresh observations,
bounded operations, runtime readiness checks and protected evidence recording.
The existing planner validates the observations. Cooperative locking does not
exclude arbitrary administrator Docker operations.
"""
from copy import deepcopy

from livy_transition import plan_transition
from teardown_validation import require


def _plan(observation):
    return plan_transition(
        observation['containers'], observation['networks'], observation['volumes'],
        observation['master_status'], image_ids=observation['image_ids'],
        expected_hashes=observation['expected_hashes'],
        livy_inventory=observation.get('livy_inventory'),
    )


def _service_ids(observation):
    return {
        c['Config']['Labels']['com.docker.compose.service']: c['Id']
        for c in observation['containers']
    }


def execute_transition(*, participant_fence, submission_lock, observe,
                       stop_client, start_services, verify_ready, record_event):
    """Execute once; never remove resources or automatically roll back failures.

    participant_fence and submission_lock are context-manager factories.
    observe returns fresh planner inputs plus a nonempty daemon_id.
    stop_client receives the validated full container ID.
    start_services receives a tuple of missing service names and a mapping of
    their existing IDs. Its live implementation must prohibit recreation,
    dependency startup, image pulls and builds.
    verify_ready performs bounded runtime/gateway checks, not a readiness claim
    for all participants. record_event persists minimal non-secret evidence.
    """
    phase = 'acquire-fence-and-lock'
    try:
        with participant_fence(), submission_lock():
            phase = 'initial-validation'
            initial = observe()
            planned = _plan(initial)
            daemon = initial.get('daemon_id')
            require(isinstance(daemon, str) and bool(daemon.strip()),
                    'Docker daemon identity is missing.')
            identities = _service_ids(initial)
            images = deepcopy(initial['image_ids'])
            hashes = deepcopy(initial['expected_hashes'])
            networks = sorted((n['Name'], n['Id']) for n in initial['networks'])

            def checked():
                current = observe()
                current_plan = _plan(current)
                require(current.get('daemon_id') == daemon,
                        'Docker daemon changed during transition.')
                require(current['image_ids'] == images
                        and current['expected_hashes'] == hashes,
                        'Image or proposed configuration identities changed.')
                require(sorted((n['Name'], n['Id']) for n in current['networks']) == networks,
                        'Project network identities changed.')
                current_ids = _service_ids(current)
                require(all(current_ids.get(name) == identifier
                            for name, identifier in identities.items()),
                        'An existing service disappeared or was replaced.')
                return current, current_plan

            record_event('planned', deepcopy(planned))
            phase = 'pre-stop-validation'
            _, fresh = checked()
            require(fresh == planned, 'Transition plan changed before execution.')

            if fresh['stop_client_id'] is not None:
                phase = 'stop-direct-client'
                record_event('stopping-direct-client',
                             {'container_id': fresh['stop_client_id']})
                stop_client(fresh['stop_client_id'])

            phase = 'pre-start-validation'
            _, fresh = checked()
            require(fresh['stop_client_id'] is None,
                    'Direct client remains running; Livy access will not start.')
            if fresh['start_services']:
                phase = 'start-livy-services'
                record_event('starting-livy-services',
                             {'services': list(fresh['start_services'])})
                start_services(tuple(fresh['start_services']),
                               deepcopy(fresh['existing_start_service_ids']))

            phase = 'post-start-validation'
            current, fresh = checked()
            require(fresh['stop_client_id'] is None and not fresh['start_services'],
                    'Requested runtime transition did not complete.')
            identities.update(_service_ids(current))

            phase = 'runtime-readiness'
            verify_ready()
            _, final_plan = checked()
            require(final_plan['stop_client_id'] is None
                    and not final_plan['start_services'],
                    'Runtime stopped or direct access resumed during readiness verification.')
            result = {
                'status': 'runtime-transition-verified',
                'service_ids': deepcopy(identities),
                'preserved_shared_ids': deepcopy(planned['preserve_service_ids']),
                'participant_readiness': 'not-established-by-this-executor',
            }
            record_event('runtime-transition-verified', deepcopy(result))
            return result
    except Exception as error:
        # Do not print arbitrary adapter exception text: it may contain secrets.
        # Failure evidence must not mask the original execution failure.
        try:
            record_event('failed', {'phase': phase, 'error_type': type(error).__name__})
        except Exception:
            pass
        raise
