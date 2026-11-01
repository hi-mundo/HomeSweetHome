# Deploy

**English** · [Português](DEPLOY.pt-BR.md)

Home Sweet Home is a single Python file with no dependencies, so any Linux box with Python 3
works: a Raspberry Pi, a home server, an old laptop. These guides assume Debian / Raspberry Pi
OS / Ubuntu.

> **No login.** Anyone who can reach the port can use the app. Keep it on your home network,
> or put nginx with a password in front of it (see below). Do not open the port on your router.

## 1. Run by hand (to try it)

```bash
git clone https://github.com/hi-mundo/HomeSweetHome.git
cd HomeSweetHome
python3 server.py              # http://<ip>:8080
PORT=9000 python3 server.py    # another port
```

Stop with `Ctrl+C`. Data lives in `data/lar.db` (override with `LAR_DB`).

## 2. systemd (recommended)

Starts on boot, restarts if it crashes, logs to the journal. The unit is in
[`deploy/homesweethome.service`](deploy/homesweethome.service) and listens on port **424**.

```bash
sudo apt install -y git python3
git clone https://github.com/hi-mundo/HomeSweetHome.git ~/HomeSweetHome
cd ~/HomeSweetHome
mkdir -p data
sed -e "s|__USER__|$USER|g" -e "s|__DIR__|$PWD|g" deploy/homesweethome.service \
  | sudo tee /etc/systemd/system/homesweethome.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now homesweethome
```

Open `http://<pi-ip>:424` (find the IP with `hostname -I`).

**Firewall.** If `ufw` is active (`sudo ufw status`), open the port for your home network only.
Replace `192.168.15.0/24` with your network (the first three numbers of the Pi's IP, then `.0/24`):

```bash
sudo ufw allow from 192.168.15.0/24 to any port 424 proto tcp comment "Home Sweet Home"
```

`sudo ufw allow 424` also works, but accepts connections from any address that can reach the Pi.

**Port.** Ports below 1024 normally need root. The unit grants only
`CAP_NET_BIND_SERVICE`, so the app still runs as your user. To use another port, edit
`Environment=PORT=` in `/etc/systemd/system/homesweethome.service`, then
`sudo systemctl daemon-reload && sudo systemctl restart homesweethome`.

**Hardening.** The unit makes the system read-only for the app and lets it write only to
`data/` (`ProtectSystem=strict`, `ReadWritePaths=`). That folder must exist before starting.

### Day to day

| Task | Command |
|---|---|
| Status | `systemctl status homesweethome` |
| Logs (live) | `journalctl -u homesweethome -f` |
| Restart | `sudo systemctl restart homesweethome` |
| Stop / disable | `sudo systemctl disable --now homesweethome` |
| Update | `cd ~/HomeSweetHome && ./deploy/update.sh` (see below) |
| Backup | `sqlite3 ~/HomeSweetHome/data/lar.db ".backup lar-$(date +%F).db"` (or copy the file while stopped) |

Dish files in `pratos/` are reloaded automatically; no restart needed after editing them.

### Updating

[`deploy/update.sh`](deploy/update.sh) does the whole update safely:

1. Exits without touching anything if you are already on the latest version.
2. Backs up the database to `data/backups/lar-YYYY-MM-DD-HHMMSS.db` (consistent copy while the
   app runs; keeps the last 10).
3. `git pull --ff-only` (refuses if files were edited on the Pi).
4. Runs the tests; if they fail, goes back to the previous commit and does not restart.
5. Restarts the service (asks for your sudo password) and checks that the app answers.
   If it does not, it rolls back both the code and the database.

```bash
cd ~/HomeSweetHome && ./deploy/update.sh
KEEP=30 ./deploy/update.sh          # keep more backups
```

To restore a backup by hand: `sudo systemctl stop homesweethome`, copy the file over
`data/lar.db`, then `sudo systemctl start homesweethome`.

## 3. nginx in front (optional)

Useful for a nicer address (`http://cozinha.lan`), HTTPS, or a password. Run the app on a
local-only port and let nginx face the network.

1. In the unit, set `Environment=PORT=8080` and restart. (The capability lines can stay or go.)
2. Install nginx and a password file:

   ```bash
   sudo apt install -y nginx apache2-utils
   sudo htpasswd -c /etc/nginx/homesweethome.htpasswd casa
   ```

3. `/etc/nginx/sites-available/homesweethome`:

   ```nginx
   server {
       listen 80;
       server_name cozinha.lan;          # or _ for any name

       auth_basic "Home Sweet Home";      # remove both lines for no password
       auth_basic_user_file /etc/nginx/homesweethome.htpasswd;

       location / {
           proxy_pass http://127.0.0.1:8080;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       }
   }
   ```

4. Enable it:

   ```bash
   sudo ln -s /etc/nginx/sites-available/homesweethome /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```

The app still listens on `0.0.0.0`, so block direct access to port 8080 with your firewall
(`sudo ufw allow 80 && sudo ufw deny 8080`) if you want nginx to be the only way in.
For HTTPS on a public domain, use `certbot --nginx`; on a home network, a local CA such as
`mkcert` is simpler.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `status=226/NAMESPACE` | `data/` does not exist: `mkdir -p ~/HomeSweetHome/data` and restart. |
| `PermissionError` binding the port | Port below 1024 without the capability lines; keep them or use a port ≥ 1024. |
| Works on the Pi (`curl 127.0.0.1:424`) but not from other devices | Firewall: see the `ufw` step above. |
| `Address already in use` | Something else uses the port: `sudo ss -ltnp \| grep :424`. |
| Page opens but nothing saves | `data/` not writable by the service user: `chown -R $USER data`. |
