# Temporary Meta webhook with Cloudflare Quick Tunnel

This procedure exposes only `GET` and `POST /webhooks/whatsapp` from the VM. The
operator panel and the rest of the API remain private. Cloudflare Quick Tunnels
are for temporary testing only: the `trycloudflare.com` address changes when the
tunnel is recreated and has no production availability guarantee.

## 1. Create the verification secret once

From `/opt/oncodir-oncoscreen` on the VM:

`sudo sh infrastructure/scripts/prepare-meta-quick-tunnel-secret.sh`

Copy the displayed Verify Token directly into Meta. Do not send it through chat,
store it in Git, or place it in shell history. The command refuses to overwrite
an existing secret.

## 2. Validate and start the tunnel

Run:

`sudo docker compose --env-file /etc/oncodir-oncoscreen/vm-test/vm-test.env --file infrastructure/compose.vm-test.yml --file infrastructure/compose.meta-quick-tunnel.yml config --quiet`

Then:

`sudo docker compose --env-file /etc/oncodir-oncoscreen/vm-test/vm-test.env --file infrastructure/compose.vm-test.yml --file infrastructure/compose.meta-quick-tunnel.yml up -d --build backend webhook-gateway cloudflared`

Read the generated URL without printing any secret:

`sudo docker compose --env-file /etc/oncodir-oncoscreen/vm-test/vm-test.env --file infrastructure/compose.vm-test.yml --file infrastructure/compose.meta-quick-tunnel.yml logs --tail=100 cloudflared`

Find the `https://...trycloudflare.com` address. In Meta, set:

- Callback URL: `https://...trycloudflare.com/webhooks/whatsapp`
- Verify Token: the token generated in step 1

Select **Verify and save**, then subscribe the webhook to the `messages` field.

## 3. Confirm isolation

Opening the Quick Tunnel root URL must return HTTP 404. Only the exact WhatsApp
webhook path is proxied. The existing operator panel remains reachable solely by
its existing local/SSH-tunnel route.

At this point Meta subscription verification can succeed. Actual signed inbound
events still require the correct project Phone Number ID and Meta App Secret to
be configured before switching from the mock provider.

## 4. Stop the temporary tunnel

Run:

`sudo docker compose --env-file /etc/oncodir-oncoscreen/vm-test/vm-test.env --file infrastructure/compose.vm-test.yml --file infrastructure/compose.meta-quick-tunnel.yml stop cloudflared webhook-gateway`

After restarting or recreating `cloudflared`, inspect its logs and update Meta if
the temporary URL changed. Replace this setup with a named tunnel or a stable
public HTTPS endpoint before production use.
