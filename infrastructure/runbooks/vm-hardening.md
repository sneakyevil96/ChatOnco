# Debian VM security baseline

This baseline applies to the team-managed Debian host used for synthetic
ONCODIR/ONCOSCREEN testing. It does not authorize real participant data. The
final network, encryption, backup, MFA, and monitoring controls still require
review before production.

Do not record temporary addresses, passwords, private keys, or deployment
secrets in this runbook. Keep one established SSH session open while changing
SSH or firewall configuration, validate before reload, and prove a new
key-only connection before closing the recovery session.

## Required baseline

- administer through a named sudo-capable user and an ED25519 public key;
- disable SSH passwords, keyboard-interactive authentication, empty passwords,
  and direct root login;
- disable X11, agent, and network tunnel forwarding; retain local forwarding
  for the loopback-only operator-panel tunnel;
- limit authentication attempts and login grace time;
- default-deny inbound host traffic and allow SSH only from the reviewed
  internal administration network;
- expose the VM-test proxy only on `127.0.0.1`; never publish PostgreSQL;
- enable NTP, AppArmor, UFW, Docker, and unattended Debian upgrades;
- disable unattended automatic reboots;
- retain compressed system journals for at most 90 days, bounded to 200 MB
  while keeping at least 1 GB free;
- keep deployment secret files root-owned with mode `0600` outside Git.

The current SSH hardening values are:

```text
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PubkeyAuthentication yes
PermitRootLogin no
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding local
PermitTunnel no
MaxAuthTries 3
LoginGraceTime 30
```

OpenSSH uses the first obtained value for most keywords. Inspect the effective
configuration with `sudo sshd -T`; do not assume that a later file overrides
an earlier value. Always run `sudo sshd -t` before `sudo systemctl reload ssh`.

The provisional journald drop-in is:

```text
[Journal]
Storage=persistent
Compress=yes
SystemMaxUse=200M
SystemKeepFree=1G
MaxRetentionSec=90day
```

Unattended upgrades must update package lists and apply eligible upgrades
daily, autoclean weekly, and leave reboots to a reviewed maintenance window.
Docker images and application dependencies are updated through the reviewed
application release process, not unattended upgrades.

## Verification

From the reviewed repository revision on the VM:

`sudo sh infrastructure/scripts/verify-vm-test-host.sh`

The script is read-only. It checks effective SSH policy, UFW defaults and the
presence of an SSH rule, critical services, NTP, unattended upgrades, host
listeners, secret-file metadata, disk usage, application readiness, and the
reboot-required marker. It deliberately does not display secret contents.

Review the actual SSH source network separately: the checker confirms an
allow rule exists but cannot decide which institutional CIDR is authorized.
Review `sudo ufw status verbose` whenever the administration network changes.

## Local health timer

The optional systemd timer records a local success or failure every five
minutes for application readiness, required Compose services, and root-disk
usage. It is not a substitute for external alerting: a failed VM cannot report
its own outage.

Install reviewed unit files and start the timer:

`sudo install -m 0644 infrastructure/systemd/oncodir-vm-healthcheck.service infrastructure/systemd/oncodir-vm-healthcheck.timer /etc/systemd/system/`

`sudo systemctl daemon-reload && sudo systemctl enable --now oncodir-vm-healthcheck.timer`

Run one check immediately and inspect its journal without message content:

`sudo systemctl start oncodir-vm-healthcheck.service`

`sudo systemctl status oncodir-vm-healthcheck.service --no-pager`

`sudo journalctl -u oncodir-vm-healthcheck.service --since today --no-pager`

The units assume the reviewed repository is at `/opt/oncodir-oncoscreen` and
deployment configuration is under `/etc/oncodir-oncoscreen/vm-test`. Revise
the unit deliberately if those deployment-owned paths change.

## Controls pending external decisions

Do not perform the controlled reboot until the VM has a known post-reboot
address or administrators have console access. Before real participant data,
obtain and record approval for:

- stable addressing and DNS;
- encrypted VM storage and the party responsible for its keys;
- encrypted off-host PostgreSQL backup storage and separate encryption keys;
- VPN, allowlisting, or an identity-aware protection for the operator panel;
- external monitoring and named alert recipients;
- the MFA decision required by the final panel exposure model.

Do not install fail2ban by default on this internal key-only endpoint. Reassess
it if SSH exposure expands or the authentication model changes.
