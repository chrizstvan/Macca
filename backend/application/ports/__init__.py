"""Protocols the use cases need from the outer world.

Each port is a typing.Protocol so adapters in ``backend.infrastructure``
satisfy them structurally — no inheritance required. Tests can pass
fakes that implement the same shape.
"""
