"""Pine Script export — INTENTIONALLY UNIMPLEMENTED IN v1.

Per spec §18 rule #10: do not generate Pine code until a walk-forward PASS verdict
exists. v1 has no walk-forward. Calling this module is a build-time policy violation.
"""


def generate_pine_script(*args, **kwargs):
    raise NotImplementedError(
        "Pine Script generation is forbidden until a walk-forward PASS verdict exists "
        "(spec §18 rule #10). v1 of SFPE-5M does not include walk-forward."
    )
