# sdv/frame: the kind 4 claim frame and its reference judge

| file | what it is |
|---|---|
| `vssframe.py` | The kind 4 `vss` claim codec inside the repo's frame (`ipc-test/common/frame.h`: header of seq and tstamp, then the payload `monitor.c` reads). Encode and decode, little-endian, slot-implied VSS identities, the catalogue digest from the generated contract, the profile id and the age. It refuses a malformed frame and packs a well-formed one that breaks a rule, so injection can reach the monitor. A slot value is a float or an int; an int packs as its float. Standard library only; no gRPC. |
| `rules.py` | The Python reference judge of reasons 8, 9, 10 and 21 to 27, in the specification's order, first failure wins, stateless. Rule 26 is computed with the specification's expression, the same polynomial tan (coefficients exported as `TAN_SIN_COEFFS` and `TAN_COS_COEFFS`) and the generated conversion constants. It is the oracle the C monitor will be tested against (Phase 2). |

The digest, AGE_MAX, the profile table and the conversion constants come from the generated
contract (`sdv-out/gen/vss_contract.py`, `sdv/vss/README.md`); `SDV_GEN` names another generation
directory. By default the judge binds only the profiles the specification has the guest compile, so an
uncompiled profile gets reason 8 here, as the Phase 2 guest will give it; a test binds another one
explicitly (`extra_ids=`), or a profile of its own (`profiles=`, under an id no bound profile has: a
collision is refused, never a replacement).

What the layout forbids is never written by the codec, and `decode` refuses all of it. The
specification has the monitor reject these with reason 10 (Phase 2): the flags' reserved bits b5..b7,
non-zero p[8..23], non-zero p[44..47], non-zero bytes in an absent slot, and a non-zero age (p[41..42])
with no value present. `decode` refuses more on its own: a length other than 64 bytes, a verdict or
reason byte in a request (p[6..7]), in a reply a verdict other than 0 or 1 or a reason that is not zero
exactly when the verdict is, a zero or sentinel seq, and a kind other than 4. An injection of any of
these (the bridge's reserved-bit mode, spec 14.4, and any test that sets one of those bytes) is a byte
patch on the packed frame, not a codec option; the `vssframe.py` docstring has the list.
`decode(..., stamp=True)` reads a `:7161` answer, which is a reply with stamps, accepted or rejected.

Tests: `tests/test_sdv_frame.py` (standard library; the tests that need the generated contract skip
without it).

## What this does not demonstrate

That the C monitor agrees with this judge (Phase 2 tests that), or that any limit is right. Kind 4
is a plausibility check on data that crossed the untrusted Linux side; the digest stops an honest
mismatch only.
