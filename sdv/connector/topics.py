"""topics.py -- the exact topic strings the twin connector uses (sdv/connector; SDV Phase 4 WP2).

Standard library only. No identifier is in this file: the thing's and the rule's
names come in at run time, from the device directory's environment file, and the tests use the placeholders
example-thing and example_rule.

The connector speaks plain MQTT on topic strings, not through an SDK shadow client, so that the device policy's list
is exactly what the code uses (prep gaps j, k). This module is that list; the limiter passes no other topic, and the
rendered device policy is held equal to it (WP6).

    client id    the thing's name: the policy allows a connection only under it.
    publish      the Basic Ingest topic of the one rule, with the thing's name as its fourth level (the policy pins
                 it, so the rule's topic(1) is an attribution the device cannot forge);
                 the `vss` shadow's update;
                 the `config` shadow's update and get.
    subscribe    the `config` shadow's get/accepted and get/rejected (a `config` written while the connector was
                 down is seen only through a get), its update/delta and update/rejected, and the `vss` shadow's
                 update/rejected (without the rejected topics a refused update is invisible).

Nothing else: no `vss` get (the device is that shadow's only writer), no update/accepted, no documents topic, no
delete, and no wildcard anywhere.

A name is checked before it is put into a topic: a thing's name is 1 to 128 of letters, digits, `:`, `_` and `-`; a
rule's name 1 to 128 of letters, digits and `_`. So no name can bring a topic level, a wildcard or a `$` with it.
A refusal says which name and never repeats it.

Does not demonstrate: that the service routes these topics as its documentation says, or that a policy naming them
authorises them (both are first seen in the account).
"""
from __future__ import annotations

import re
from typing import Any, Tuple

SHADOWS = ("vss", "config")

_THING = re.compile(r"[A-Za-z0-9:_-]{1,128}")
_RULE = re.compile(r"[A-Za-z0-9_]{1,128}")


class TopicsError(ValueError):
    """A thing or rule name that cannot go into a topic."""


class Topics:
    """The connector's topics for one thing and one rule."""

    def __init__(self, thing: Any, rule: Any) -> None:
        if not isinstance(thing, str) or not _THING.fullmatch(thing):
            raise TopicsError("the thing's name is not 1 to 128 of letters, digits, ':', '_' and '-'")
        if not isinstance(rule, str) or not _RULE.fullmatch(rule):
            raise TopicsError("the rule's name is not 1 to 128 of letters, digits and '_'")
        self.thing = thing
        self.rule = rule
        self.client_id = thing
        self.telemetry = "$aws/rules/%s/%s" % (rule, thing)
        vss = "$aws/things/%s/shadow/name/vss" % thing
        config = "$aws/things/%s/shadow/name/config" % thing
        self.vss_update = vss + "/update"
        self.vss_update_rejected = vss + "/update/rejected"
        self.config_update = config + "/update"
        self.config_get = config + "/get"
        self.config_get_accepted = config + "/get/accepted"
        self.config_get_rejected = config + "/get/rejected"
        self.config_update_delta = config + "/update/delta"
        self.config_update_rejected = config + "/update/rejected"
        self.publish: Tuple[str, ...] = (self.telemetry, self.vss_update, self.config_update, self.config_get)
        self.subscribe: Tuple[str, ...] = (self.config_get_accepted, self.config_get_rejected, self.config_update_delta,
                                           self.config_update_rejected, self.vss_update_rejected)
