# Deploy

[English](DEPLOY.md) · **Português**

O Home Sweet Home é um arquivo Python só, sem dependências: qualquer Linux com Python 3
serve, como um Raspberry Pi, um servidor em casa ou um notebook velho. Os passos abaixo
são para Debian / Raspberry Pi OS / Ubuntu.

> **Sem login.** Quem alcança a porta usa o app. Deixe só na rede de casa ou ponha o nginx
> com senha na frente (abaixo). Não abra a porta no roteador.

## 1. Rodar à mão (para testar)

```bash
git clone https://github.com/hi-mundo/HomeSweetHome.git
cd HomeSweetHome
python3 server.py              # http://<ip>:8080
PORT=9000 python3 server.py    # outra porta
```

Para com `Ctrl+C`. Os dados ficam em `data/lar.db` (mude com `LAR_DB`).

## 2. systemd (recomendado)

Sobe junto com o sistema, reinicia se cair e manda os logs para o journal. A unit está em
[`deploy/homesweethome.service`](deploy/homesweethome.service) e usa a porta **424**.

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

Abra `http://<ip-do-pi>:424` (o IP aparece com `hostname -I`).

**Porta.** Porta abaixo de 1024 normalmente exige root. A unit dá só a permissão
`CAP_NET_BIND_SERVICE`, então o app continua rodando com o seu usuário. Para outra porta,
mude `Environment=PORT=` em `/etc/systemd/system/homesweethome.service` e rode
`sudo systemctl daemon-reload && sudo systemctl restart homesweethome`.

**Proteção.** A unit deixa o sistema só leitura para o app, que só escreve em `data/`
(`ProtectSystem=strict`, `ReadWritePaths=`). Essa pasta precisa existir antes de subir.

### No dia a dia

| Tarefa | Comando |
|---|---|
| Status | `systemctl status homesweethome` |
| Logs (ao vivo) | `journalctl -u homesweethome -f` |
| Reiniciar | `sudo systemctl restart homesweethome` |
| Parar / desativar | `sudo systemctl disable --now homesweethome` |
| Atualizar | `cd ~/HomeSweetHome && ./deploy/update.sh` (abaixo) |
| Backup | `sqlite3 ~/HomeSweetHome/data/lar.db ".backup lar-$(date +%F).db"` (ou copie o arquivo com o serviço parado) |

Os pratos em `pratos/` são relidos sozinhos; não precisa reiniciar depois de editar.

### Atualizar

O [`deploy/update.sh`](deploy/update.sh) faz a atualização inteira com segurança:

1. Sai sem mexer em nada se já está na última versão.
2. Faz backup do banco em `data/backups/lar-AAAA-MM-DD-HHMMSS.db` (cópia consistente com o app
   rodando; mantém os últimos 10).
3. `git pull --ff-only` (recusa se alguém editou arquivos no Pi).
4. Roda os testes; se falharem, volta ao commit anterior e não reinicia.
5. Reinicia o serviço (pede a senha do sudo) e confere se o app responde. Se não responder,
   volta o código e o banco.

```bash
cd ~/HomeSweetHome && ./deploy/update.sh
KEEP=30 ./deploy/update.sh          # guardar mais backups
```

Para restaurar um backup à mão: `sudo systemctl stop homesweethome`, copie o arquivo por cima
de `data/lar.db` e rode `sudo systemctl start homesweethome`.

## 3. nginx na frente (opcional)

Serve para ter um endereço melhor (`http://cozinha.lan`), HTTPS ou senha. O app fica numa
porta local e o nginx atende a rede.

1. Na unit, mude para `Environment=PORT=8080` e reinicie. (As linhas de capability podem ficar
   ou sair.)
2. Instale o nginx e crie a senha:

   ```bash
   sudo apt install -y nginx apache2-utils
   sudo htpasswd -c /etc/nginx/homesweethome.htpasswd casa
   ```

3. `/etc/nginx/sites-available/homesweethome`:

   ```nginx
   server {
       listen 80;
       server_name cozinha.lan;          # ou _ para qualquer nome

       auth_basic "Home Sweet Home";      # tire as duas linhas para não pedir senha
       auth_basic_user_file /etc/nginx/homesweethome.htpasswd;

       location / {
           proxy_pass http://127.0.0.1:8080;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       }
   }
   ```

4. Ative:

   ```bash
   sudo ln -s /etc/nginx/sites-available/homesweethome /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```

O app continua ouvindo em `0.0.0.0`; para o nginx ser a única entrada, bloqueie a porta 8080
no firewall (`sudo ufw allow 80 && sudo ufw deny 8080`). Para HTTPS num domínio público, use
`certbot --nginx`; na rede de casa, uma CA local como o `mkcert` é mais simples.

## Problemas comuns

| Sintoma | Solução |
|---|---|
| `status=226/NAMESPACE` | `data/` não existe: `mkdir -p ~/HomeSweetHome/data` e reinicie. |
| `PermissionError` ao abrir a porta | Porta abaixo de 1024 sem as linhas de capability; mantenha-as ou use porta ≥ 1024. |
| `Address already in use` | Outra coisa usa a porta: `sudo ss -ltnp \| grep :424`. |
| Abre mas não salva | `data/` sem permissão de escrita para o usuário do serviço: `chown -R $USER data`. |
