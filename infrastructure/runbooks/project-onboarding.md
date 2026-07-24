# Project onboarding

ONCODIR and ONCOSCREEN can be prepared independently. Neither a missing phone
number nor a missing FAQ collection blocks software development; the affected
feature remains disabled and safely escalates.

## Infrastructure track

When a server is available:

1. record ownership, hostname, operating system, storage, backup destination,
   firewall, SSH keys, panel access control, monitoring, and incident contacts;
2. provision separate local/staging/production credentials and resource
   identities;
3. complete the environment-separation manifests and restore exercise;
4. configure HTTPS and panel restriction; require MFA if the production panel
   remains publicly reachable;
5. run deployment validation and the production-readiness checklist.

## Meta track

For each project:

1. confirm legal/operational ownership and whether the shared Portfolio, WABA,
   and application topology is permitted;
2. obtain the dedicated phone number and authoritative phone-number ID;
3. create opaque credential/webhook bindings and inject their secrets outside
   Git;
4. approve project-specific templates and record language, parameter count,
   purpose, and approved body snapshot;
5. configure the public webhook, verify signatures/deduplication/statuses with
   a non-production setup, then enable the project deliberately.

Different app secrets remain supported. Never infer a project from message
content or the sender; resolve it from the receiving phone-number ID.

## FAQ and privacy-content track

For each project:

1. approve the public name, privacy warning, fallback messages, contacts,
   branding, and retention values;
2. prepare controlled Romanian FAQ and alternative-question files with author,
   reviewer, clinical review where medically adjacent, validity, and version;
3. prepare labelled Romanian evaluation items using `FAQ@version` or
   `ESCALATE`, including spelling, missing diacritics, paraphrases, ambiguity,
   and high-risk cases;
4. import and validate without publishing;
5. calibrate that project's global threshold and best/second-result gap;
6. publish only after at least 99% precision, less than 1% incorrect automatic
   answers, and zero incorrect identified high-risk answers are demonstrated.

If no safe numeric calibration exists, leave semantic retrieval disabled.
Exact matches may still return only published, currently valid approved
answers.
