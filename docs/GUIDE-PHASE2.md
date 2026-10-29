# Phase 2 গাইড — Laravel 11 (PHP 8.4) backend + cPanel hosting + MySQL

Phase 2: backend project setup, ৪টি database table (users / videos / payments / settings), local test, আর cPanel এ live hosting। আপনি নিজে করবেন — প্রতি step আমি লিখে দিচ্ছি।

> আগে Phase 1 worker image build/push/Vast.ai এর কাজ চলতে পারে পাশাপাশি — দুটো আলাদা।

---

## ১. আপনার PC তে PHP 8.4 + Composer install

Windows এ দুটো option:

**Option A — XAMPP (easiest):**
1. https://www.apachefriends.org/ থেকে XAMPP নেওয়া (আগে PHP 8.4 সাপোর্ট করছে — নতুন version নেন)
2. Composer: https://getcomposer.org/download/ → `composer.phar` নেওয়া, `composer.phar` কို PHP 8.4 folder এ রাখুন

**Option B — standalone PHP:**
1. https://windows.php.net/downloads/releases/ থেকে PHP 8.4 (NTS x64) zip নেওয়া
2. Composer: getcomposer.org থেকে composer.phar
3. `php -v` চেক: `php -v` → PHP 8.4.x দেখতে হবে

> Mac এ: `brew install php@8.4 composer`। Linux: `sudo apt install php8.4-cli php8.4-mbstring php8.4-xml php8.4-curl php8.4-mysql unzip` + composer。

## ২. Laravel project create

CMD/PowerShell তে:

```cmd
cd C:\Projects
composer create-project laravel/laravel backend
```

(composer.phar চালাচ্ছেন তবে: `php composer.phar create-project laravel/laravel backend`)

এটি ~2-5 min নেবে। শেষ হলে `C:\Projects\backend` তে একটি full Laravel 11 app থাকবে।

## ৩. backend-src এর ফাইল merge করুন

আমি repo তে `backend-src/` folder তে সব ফাইল দিয়েছি। repo clone থাকলে:

```cmd
cd C:\Projects\FastVideo-FastH3-Omni-8-Step-V1
```

তারপর `backend-src/` এর ভেতরকার ফাইল কপি করুন `C:\Projects\backend` তে:

| backend-src তে | backend তে copy করুন |
|---|---|
| composer.json | overwrite (composer.json) |
| .env.example | overwrite (.env.example) |
| bootstrap/app.php | overwrite (bootstrap/app.php) |
| app/Models/User.php | app/Models/User.php (overwrite) |
| app/Models/Video.php | app/Models/Video.php (new) |
| app/Models/Payment.php | app/Models/Payment.php (new) |
| app/Models/Setting.php | app/Models/Setting.php (new) |
| database/migrations/2026_*.php | database/migrations/ (৪টি new file) |
| database/seeders/DatabaseSeeder.php | database/seeders/DatabaseSeeder.php (overwrite) |
| routes/api.php | routes/api.php (new) |

**গুরুত্বপূর্ণ:** default Laravel এ আগেই একটি users migration থাকে — হতাশ করবেন না, শুধু delete করবেন:

```cmd
del C:\Projects\backend\database\migrations\0001_01_01_000000_create_users_table.php
```

(আমার users migration এ সব column আছে — default এর superset)

## ৪. Dependencies install + local test

```cmd
cd C:\Projects\backend
composer update
php artisan key:generate
```

Local test এ sqlite ব্যবহার করি (MySQL এর দরকার নেই):

```cmd
copy .env.example .env
set DB_CONNECTION=sqlite
set DB_DATABASE=database.sqlite    (CMD এ পরে reset দিতে পারেন — আসলে .env তে edit করুন: DB_CONNECTION=sqlite, DB_DATABASE="C:\Projects\backend\database.sqlite")
touch database.sqlite   (or: type nul > database.sqlite)
php artisan migrate
php artisan db:seed
php artisan serve
```

Browser তে: http://localhost:8000/up → `{"status":"ok"}`
http://localhost:8000/api/health → `{"status":"ok","service":"fasth3-video-backend"}`

চিন্তা নেই — এই পর্যন্ত সব local।

## ৫. cPanel hosting setup

### 5.1 Domain + SSL
1. cPanel → **Domains**: domain/subdomain পয়েন্ট করুন (খালি subdomain `app.yourdomain.com` বা main domain)
2. cPanel → **SSL/TLS** → **Manage SSL sites** → Let's Encrypt বা AutoSSL দিয়ে SSL দিন

### 5.2 MySQL database create
1. cPanel → **MySQL Databases**
2. New database: `fastvideo` (cPanel prefix সহ যেমন `cpanel_fastvideo` — পুরো name টা নোট করুন)
3. New user: `fastvideo_user` (password strong — নোট করুন)
4. user কে database এর ওপর full privileges দিন
5. সব দুটো নোট করুন — .env এ লাগবে

### 5.3 Project upload (FTP)
1. FileZilla বা সেটিংস মতো FTP client — cPanel এ FTP account (cPanel → FTP Accounts)
2. Local `C:\Projects\backend` এর ফাইল public_html এ upload করুন। **প্যাথ নোট:**
   - `backend/public/` এর **ভেতরের ফাইল** (index.php, .htaccess, css/, js/) → `public_html/` এ
   - `backend/` এর বাকি ফাইল (app/, bootstrap/, config/, routes/, storage/, vendor/, .env, artisan, composer.json...) → `public_html/` এ
   
   (অর্থাৎ public/ ফোল্ডার এর ভেতরের কন্টেন্ট public_html এর root এ যায়, বাকি সব public_html এর root এর সাথে এক স্তরে থাকে)
3. `.env` file edit করুন (server এ আপলোড করার আগে):
   ```
   APP_KEY=<local এ php artisan key:generate এর output>
   APP_URL=https://app.yourdomain.com
   DB_DATABASE=cpanel_fastvideo      (পুরো cPanel DB name)
   DB_USERNAME=fastvideo_user
   DB_PASSWORD=<your-password>
   DB_HOST=127.0.0.1
   APP_DEBUG=false
   WORKER_SECRET=<worker এর একই secret>
   WORKER_BASE_URL=<vast.ai worker url>
   ```
4. Permissions:
   ```
   chmod -R 775 storage/
   chmod -R 775 bootstrap/cache/
   mkdir -p storage/framework/{cache,sessions,views} storage/logs
   ```
   (FTP সাধারণত permission দেওয়া যায় — storage ফোল্ডার 775)

### 5.4 Migrations run করুন (server এ)

**Option A — SSH থাকলে:**
```bash
cd /home/youruser/public_html
php artisan migrate --force
php artisan db:seed
```

**Option B — SSH নেই (phpMyAdmin ব্যবহার):**
Local তে:
```cmd
cd C:\Projects\backend
php artisan migrate --pretend
```
Output তে SQL দেখা যাবে — কপি করে cPanel → phpMyAdmin → আপনার database → "SQL" tab → run করুন। Seeder এর জন্য অন্য SQL — সহজে করতে `php artisan db:seed --pretend` ব্যবহার করুন।

(migrations তে users/videos/payments/settings — ৪টি CREATE TABLE।)

### 5.5 Test
1. https://app.yourdomain.com/up → `{"status":"ok"}`
2. https://app.yourdomain.com/api/health → `{"status":"ok","service":"fasth3-video-backend"}`
3. phpMyAdmin তে tables দেখুন: users, videos, payments, settings — ৪টি থাকতে হবে
4. cPanel → **PHP Version** selector → 8.4 দিন (MultiPHP)

## ৬. Database schema রেফারেন্স

**users** — id, name, email(unique), email_verified_at, password, phone, avatar, is_admin(bool), remember_token, timestamps

**videos** — id, user_id(FK), title, prompt, enhanced_prompt, mode(t2v/i2v), resolution(768p/480p), dimensions, duration_seconds(5/10/15), status(pending/processing/completed/failed), job_id, worker_response(json), file_path, file_url, file_size, generation_time, error_message, cost_bdt, is_favorite, timestamps

**payments** — id, user_id(FK), provider(bkash/nagad), transaction_id, amount, currency(BDT), status(pending/completed/failed/refunded), status_message, package_type, credits, initiated_at, completed_at, timestamps

**settings** — id, key(unique), value, timestamps

## ৭. Troubleshooting

| Symptom | Fix |
|---|---|
| `/up` 500 | storage/bootstrap/cache permission; .env বারু দেখুন; `php artisan config:clear` |
| `/api/health` 404 | routes/api.php এর জন্য bootstrap/app.php ঠিক আছে তো দেখুন (api: __DIR__.'/../routes/api.php') |
| DB connection error | DB_HOST `localhost` বদলে `127.0.0.1` দিন; DB name তে cPanel prefix (`cpanel_`) অন্তর্ভুক্ত করুন |
| `Table 'users' doesn't exist` | migrations run করা হয়নি — SSH/phpMyAdmin দিয়ে চালান |
| APP_KEY empty | local এ `php artisan key:generate` → .env এ copy |
| SSL নেই | cPanel SSL/TLS → AutoSSL |
| Composer memory | `composer config --global memory-limit 2G` |

## ৮. Phase 2 শেষ — Phase 3 এর প্রস্তুতি

Phase 2 complete হলে Phase 3: Laravel API (auth with JWT, generate, status, callback, payment, history + middleware)। Worker callback কাজ করতে এই backend এ `/api/worker/callback` endpoint তৈরি হবে।

## নোট — সামনের phase গুলোর জন্য প্রস্তুতি
- `WORKER_SECRET` + `WORKER_BASE_URL` আগে থেকে .env তে রাখুন
- Gemini API key (gemini-2.0-flash, free tier) — Phase 3 তে prompt enhancement
- cPanel cron — Phase 6 auto-delete command এর জন্য (`php artisan schedule:run` প্রতি মিনিটে)
