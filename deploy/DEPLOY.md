# Деплой SplitDaddy на Hetzner (окремо від наявного проєкту)

Бот працює через **long polling** — без вхідних портів, домену та nginx. Тому з
наявним проєктом він не конфліктує. Ізоляція: окрема папка + власний `venv` +
окремий systemd-сервіс + свій файл БД.

> Заміни `__APP_USER__` (твій лінукс-користувач, напр. `vitaliy` або `deploy`)
> і `__APP_DIR__` (напр. `/home/vitaliy/apps/splitdaddy`) на свої значення.
> Нижче зручно задати їх одноразово як змінні оболонки.

---

## ⚡ Квікстарт під root (підстав лише IP сервера)

Заходиш як root → папка `/opt/splitdaddy`, сервіс під root. Заміни `SERVER` на
IP/хост свого Hetzner у всіх командах.

**1. З Mac — залити код** (з кореня `/Users/vitaliy/Projects/SplitDaddy`):

```bash
rsync -av --delete \
  --exclude '.venv' --exclude '*.db' --exclude '*.db-*' \
  --exclude '.env' --exclude '__pycache__' --exclude '.git' \
  ./ root@SERVER:/opt/splitdaddy/
```

**2. На сервері — оточення + конфіг:**

```bash
ssh root@SERVER
cd /opt/splitdaddy
python3 --version            # має бути 3.11+
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
cp .env.example .env
nano .env                    # впиши BOT_TOKEN=...  (DB_PATH=splitdaddy.db лишай)
```

**3. Зупини локальний бот на Mac** (інакше Telegram дасть Conflict):

```bash
# на Mac, в окремому терміналі:
launchctl unload ~/Library/LaunchAgents/com.splitdaddy.bot.plist
```

**4. На сервері — systemd-сервіс:**

```bash
sed -e 's#__APP_USER__#root#g' -e 's#__APP_DIR__#/opt/splitdaddy#g' \
  /opt/splitdaddy/deploy/splitdaddy.service | tee /etc/systemd/system/splitdaddy.service
systemctl daemon-reload
systemctl enable --now splitdaddy
systemctl status splitdaddy --no-pager
journalctl -u splitdaddy -f          # «Run polling for bot @splitdaddy_bot» = ок
```

Готово. Далі — розділ «Оновлення коду» нижче (rsync + `systemctl restart`).

> Безпечніша альтернатива (необов'язково): замість root створити окремого юзера
> `useradd -r -m -d /opt/splitdaddy splitdaddy` і вписати його в `User=`. Для
> старту root цілком підходить.

---

## 0. Перед стартом: зупини локальний бот на Mac

Один токен не можна полити з двох місць. На своєму Mac:

```bash
launchctl unload ~/Library/LaunchAgents/com.splitdaddy.bot.plist
```

(Повернути локально: `launchctl load ...`. Але тримати увімкненим варто лише
одне місце.)

---

## 1. Завантажити код на сервер

З Mac, з кореня проєкту (`/Users/vitaliy/Projects/SplitDaddy`):

```bash
# заміни user@server та шлях
rsync -av --delete \
  --exclude '.venv' --exclude '*.db' --exclude '*.db-*' \
  --exclude '.env' --exclude '__pycache__' --exclude '.git' \
  ./ user@SERVER:/home/__APP_USER__/apps/splitdaddy/
```

`--exclude '.venv'` і `*.db` — щоб не везти локальне середовище й локальну базу
(на сервері створимо свої).

---

## 2. На сервері: налаштувати оточення

```bash
ssh user@SERVER

# задаємо змінні (підстав свої)
export APP_USER=__APP_USER__
export APP_DIR=/home/$APP_USER/apps/splitdaddy
cd "$APP_DIR"

# Python venv (потрібен python3.11+). Перевір: python3 --version
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# конфіг
cp .env.example .env
nano .env   # впиши BOT_TOKEN=... ; DB_PATH=splitdaddy.db
```

Перевір, що запускається вручну (Ctrl+C, щоб зупинити):

```bash
.venv/bin/python -m bot.main
# має написати: Run polling for bot @splitdaddy_bot
```

---

## 3. Встановити systemd-сервіс

```bash
# підставити свої значення у шаблон і покласти в systemd
sed -e "s#__APP_USER__#$APP_USER#g" -e "s#__APP_DIR__#$APP_DIR#g" \
  "$APP_DIR/deploy/splitdaddy.service" | sudo tee /etc/systemd/system/splitdaddy.service

sudo systemctl daemon-reload
sudo systemctl enable --now splitdaddy

# статус і логи
systemctl status splitdaddy --no-pager
journalctl -u splitdaddy -f       # логи наживо (Ctrl+C — вийти)
```

Готово. Сервіс стартує при завантаженні сервера й перепіднімається після збою —
повністю окремо від іншого проєкту.

---

## Оновлення коду в майбутньому

```bash
# з Mac: залити зміни
rsync -av --delete --exclude '.venv' --exclude '*.db' --exclude '*.db-*' \
  --exclude '.env' --exclude '__pycache__' --exclude '.git' \
  ./ user@SERVER:/home/__APP_USER__/apps/splitdaddy/

# на сервері: оновити залежності (якщо мінялись) і перезапустити
ssh user@SERVER 'cd ~/apps/splitdaddy && .venv/bin/pip install -r requirements.txt && sudo systemctl restart splitdaddy'
```

## Щоденний бекап БД

`deploy/backup.sh` робить узгоджений онлайн-знімок `splitdaddy.db` у `backups/`
(без зупинки бота) і тримає останні 14 копій. Підключити в cron (під root):

```bash
chmod +x /opt/splitdaddy/deploy/backup.sh
( crontab -l 2>/dev/null; \
  echo "0 3 * * * /opt/splitdaddy/deploy/backup.sh >> /opt/splitdaddy/backup.log 2>&1" \
) | crontab -
crontab -l            # перевірити
/opt/splitdaddy/deploy/backup.sh   # прогнати вручну раз
ls -la /opt/splitdaddy/backups/
```

Відновлення з бекапу:

```bash
systemctl stop splitdaddy
cp /opt/splitdaddy/backups/splitdaddy-YYYYMMDD-HHMMSS.db /opt/splitdaddy/splitdaddy.db
systemctl start splitdaddy
```

## Корисні команди

```bash
sudo systemctl restart splitdaddy    # перезапуск
sudo systemctl stop splitdaddy       # зупинити
journalctl -u splitdaddy -n 100      # останні 100 рядків логів
journalctl -u splitdaddy --since today
```

## Чому це не заважає іншому проєкту

- **Порти:** бот не слухає жодного — long polling сам ходить до Telegram.
- **Залежності:** свій `.venv`, системний Python і пакети іншого проєкту не чіпає.
- **Процес:** окремий unit `splitdaddy`; рестарт/збій не впливають на сусіда.
- **Дані:** власний `splitdaddy.db` у своїй папці.
- **CPU/RAM:** навантаження мінімальне (бот переважно «спить» на polling).
