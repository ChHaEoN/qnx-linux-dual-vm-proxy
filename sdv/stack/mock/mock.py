# mock.py -- the actuation behaviour the slice's mock provider serves (sdv/stack)
#
# Project-written. Mounted read-only over the pinned mock-provider image's own /mock/mock.py, so
# the provider mocks exactly one datapoint: the hazard-light actuator. The image's sample file also
# animates Vehicle.Speed, which would make the mock provider a second writer of a signal the CAN
# provider owns; replacing the file is how the one-writer-per-signal rule is kept (the run's
# attribution table lists this file's paths as the mock provider's write set, and sdv/stack's
# tests read the paths from this file).
#
# Behaviour: the current value starts false; every actuator target the databroker reports is
# copied to the current value unchanged. Nothing else is mocked.
#
# The DSL is the mock provider's own (lib.dsl, lib.trigger inside the image); this file is only
# ever imported there.

from lib.dsl import (  # type: ignore[import-not-found]
    create_behavior,
    create_event_trigger,
    create_set_action,
    mock_datapoint,
)
from lib.trigger import EventType  # type: ignore[import-not-found]

mock_datapoint(
    path="Vehicle.Body.Lights.Hazard.IsSignaling",
    initial_value=False,
    behaviors=[
        create_behavior(
            trigger=create_event_trigger(EventType.ACTUATOR_TARGET),
            action=create_set_action("$event.value"),
        )
    ],
)
