# The repository description — pinned

This file is the authoritative text of the GitHub "About" field. The claims gate
compares it against the live value and fails when they differ.

**Why it exists.** The description is the highest-exposure sentence this project
has — it is what GitHub search, the owner's profile and every link preview show
— and it was the one surface the gate structurally could not see, because it is
repository metadata rather than a file. It drifted for exactly that reason: it
described an AWS Graviton cloud twin long after `README.md` and
[`findings.md`](findings.md) had recorded that no cloud leg was ever built and
that every figure labelled "cloud" came from a local Windows PC. Nothing could
have caught that, because nothing was looking.

**How to change the description.** Edit the block below, commit it, and set the
same text in the repository settings. Either order works; the gate fails until
they match, which is the point. The gate applies the same denylist and the same
figure verification to this file as it does to `README.md`, so a claim that
cannot be re-derived from committed data fails here too.

**What the gate does NOT do:** it cannot change the About field. That is a
settings action, so a drift failure tells the owner to go and fix it by hand.

```text
A study of DRIVE OS-style dual-VM partitioning on a Jetson Orin Nano: L4T keeps the metal and the GPU, and QNX SDP 8.0 is a KVM guest beside it, started with a startup-qemu-virt rebuilt from source (not a QNX-supported configuration). Code and design only; measured and functional results are held locally under the QNX licence.
```
