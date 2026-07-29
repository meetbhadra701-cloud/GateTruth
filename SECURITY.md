# Security Policy

## Reporting a vulnerability

GateTruth executes untrusted, model-generated RTL and untrusted repositories inside
a pinned Docker container. If you find a way for a submission to escape that sandbox —
read host files, reach the network, exhaust host resources, or influence another
submission's score — please report it privately rather than opening a public issue.

- **Preferred:** open a [GitHub security advisory](https://github.com/meetbhadra701-cloud/GateTruth/security/advisories/new)
  (private).
- Or email the maintainer (address on the project's arXiv paper / GitHub profile).

Please include the steps to reproduce and the affected version or commit. We aim to
acknowledge reports within a few days and to fix confirmed sandbox-escape issues before
any coordinated disclosure.

## Scope

In scope: sandbox escape from a scored submission, score integrity (making the harness
report a score not produced by the pinned flow), and denial of service against the
scoring host.

Out of scope: the intended behavior that a submission's RTL runs inside the container;
findings that require maintainer-level access; and issues in the upstream open-source
EDA tools (report those to their projects).
