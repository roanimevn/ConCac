# Discord Sports Schedule Bot

Bot Discord thông báo lịch thi đấu bằng **embed**, báo **đúng giờ** (trước giờ đá + đúng lúc bắt đầu).

**Giải hỗ trợ:** Premier League · LaLiga · Bundesliga · Serie A · Champions League (C1) · Europa League (C2) · Conference League (C3) · AFC Champions League Elite & Two · V.League 1 & 2 · Formula 1 · Formula 2 · Formula 3

## 1. Tạo bot trên Discord

1. Vào <https://discord.com/developers/applications> → **New Application** → tab **Bot** → **Reset Token** và copy token.
2. Không cần bật Privileged Intents.
3. Tab **OAuth2 → URL Generator**: chọn scope `bot` + `applications.commands`; quyền: **View Channels**, **Send Messages**, **Embed Links** (thêm **Mention Everyone** nếu muốn bot nhắc role không-mentionable). Mở URL để mời bot vào server.

## 2. Cài đặt và chạy

Cần Python 3.10+.

```bash
cd discord-sports-bot
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp env.example .env                                     # đổi tên thành .env rồi điền DISCORD_TOKEN
python check_sources.py                                 # kiểm tra các nguồn dữ liệu (không cần token)
python bot.py
```

Bot phải chạy liên tục để báo đúng giờ → nên đặt trên VPS/Raspberry Pi/máy luôn bật (systemd, Docker, `pm2`, `screen`…).

## 3. Dùng trong server

| Lệnh | Quyền | Chức năng |
|---|---|---|
| `/setup channel [role] [digest]` | Manage Server | Chọn kênh nhận thông báo (+ role cần nhắc, bật/tắt bản tin sáng). Lần đầu tự bật tất cả giải |
| `/subscribe <giải>` / `/unsubscribe <giải>` | Manage Server | Bật/tắt từng giải (hoặc "Tất cả") |
| `/leagues` | ai cũng dùng | Xem giải nào đang bật |
| `/schedule [giải] [ngày]` | ai cũng dùng | Xem lịch 1–14 ngày tới |
| `/today` | ai cũng dùng | Lịch 24 giờ tới |
| `/testnotify` | Manage Server | Gửi thử một thông báo |
| `/status` | Manage Server | Xem nguồn nào đang lỗi, cập nhật lần cuối |

## 4. Bot báo giờ như thế nào?

- **Báo trước & đúng giờ:** mặc định báo **15 phút trước** và **đúng giờ bắt đầu** (`NOTIFY_OFFSETS=15,0`). Ví dụ `30,10,0` để báo 3 lần.
- **Độ chính xác:** vòng lặp ngủ đến đúng mốc kế tiếp (tối đa 30 giây mỗi lần thức), nên độ trễ thường chỉ vài giây.
- **Bản tin sáng:** 07:00 (giờ `TIMEZONE`) mỗi ngày gửi "lịch 24 giờ tới" gom theo giải. Đặt `DAILY_DIGEST_HOUR=-1` để tắt.
- **Nhiều trận cùng giờ** được gom vào một tin nhắn (tối đa 10 embed/tin) để không spam.
- **Dời lịch:** lịch được cập nhật lại từ nguồn mỗi 2 giờ (`REFRESH_MINUTES`). Trận bị dời giờ sẽ được báo lại theo giờ mới; trận hoãn/huỷ bị bỏ qua.
- **Chống gửi trùng:** mỗi thông báo được ghi vào SQLite (`data/bot.db`) nên khởi động lại bot không bị báo lặp.
- **Múi giờ:** embed hiển thị giờ `TIMEZONE` (mặc định UTC+7) **và** thẻ giờ động của Discord – mỗi người thấy theo múi giờ của riêng mình.
- **Giới hạn:** nếu bot tắt đúng lúc đến mốc báo, thông báo đó bị bỏ (chỉ bù nếu trễ ≤ `LATE_GRACE_SECONDS` = 2 phút).
- **F1/F2/F3:** mặc định chỉ báo Qualifying / Sprint / Race. Muốn báo cả buổi tập: `NOTIFY_PRACTICE=true`.

## 4b. Trạng thái hiển thị của bot

Mặc định: avatar hiện **🌙 Chờ (Idle)**, dưới tên bot hiện chữ **"Đang cập nhật giải đấu..."**.

| Chỗ hiển thị | Biến | Mặc định |
|---|---|---|
| Chấm tròn ở avatar | `BOT_STATUS` = `online` · `idle` · `dnd` · `invisible` | `idle` |
| Dòng ngay dưới tên bot | `BOT_ACTIVITY` | `Đang cập nhật giải đấu...` |
| Dòng phụ trong hồ sơ bot | `BOT_ACTIVITY_DETAIL` | (trống) |
| Kiểu hoạt động | `BOT_ACTIVITY_TYPE` = `playing` · `watching` · `listening` · `competing` · `custom` | `playing` |

Nên dùng `playing`: danh sách thành viên hiện đúng chữ trần. Kiểu `custom` bị Discord tự chèn 🤔 (bot không gắn được emoji), còn `watching` hiện tiền tố tiếng Anh "Watching".

Trên Render, biến môi trường đè lên mặc định trong code: nếu đã tự thêm các biến `BOT_*` thì xoá hoặc sửa cho khớp.

## 5. Nguồn dữ liệu (đọc kỹ)

Không có một API miễn phí nào phủ hết các giải này, nên bot dùng 3 nguồn:

| Giải | Nguồn | Ghi chú |
|---|---|---|
| EPL, LaLiga, Bundesliga, Serie A, C1, C2, C3, ACL Elite/Two | ESPN (API công khai, không cần key) | API **không chính thức**, có thể đổi mà không báo trước |
| V.League 1 & 2 | TheSportsDB (key miễn phí) | Bản free chỉ trả ~15 trận sắp tới/giải; dữ liệu do cộng đồng nhập nên có thể chậm hoặc thiếu |
| F1, F2, F3 | Dataset mở của f1calendar.com (GitHub `sportstimes/f1`, MIT) | F2/F3 không có API chính thức miễn phí; lịch do cộng đồng duy trì |

> **Mình chưa gọi thử được các API thật** (môi trường soạn code không có mạng). Parser đã test với dữ liệu mẫu theo định dạng đã biết, nhưng hãy chạy `python check_sources.py` trước khi dùng. Hai điểm dễ sai nhất:
> - **AFC Champions League Two** đang dùng slug ESPN `afc.cup`. Nếu báo lỗi: `python check_sources.py --slug <slug khác>` để dò, rồi đặt `SOURCE_ACLT=<slug>` trong `.env`.
> - **V.League 2** tự dò ID theo tên trên TheSportsDB; nếu không khớp, đặt `SOURCE_VL2=<idLeague>` (xem ID ở URL `thesportsdb.com/league/<id>`).

Nếu cần độ phủ/độ tin cậy cao hơn (đặc biệt V.League), cân nhắc API trả phí như API-Football hoặc thêm một provider mới – mỗi provider chỉ cần một hàm `fetch()` trả về `list[Event]` (xem `providers/espn.py`).

## 6. Chạy trên Render (Web Service, gói Free)

Repo đã có sẵn `keep_alive.py` (Flask) và `render.yaml`. Cách làm:

1. Đẩy thư mục lên GitHub. Trên Render: **New → Blueprint** → chọn repo (hoặc **New → Web Service** rồi tự điền: Build `pip install -r requirements.txt`, Start `python bot.py`, Instance Type **Free**).
2. Đặt biến môi trường: `DISCORD_TOKEN`, **`CHANNEL_ID`** (kênh nhận thông báo), tuỳ chọn `ROLE_ID`, `SEED_LEAGUES`.
3. Deploy xong, vào tab **Logs** xem dòng `Đã nạp cấu hình từ env…`, rồi gõ `/status` trong Discord.
4. **Nên thêm một pinger bên ngoài** (UptimeRobot / cron-job.org) gọi `https://<tên-service>.onrender.com/health` mỗi 5 phút. Bot đã tự ping chính nó, nhưng pinger ngoài có thêm một lợi ích: nếu Render lỡ cho ngủ hoặc restart, request kế tiếp sẽ đánh thức bot dậy.

**Hạn chế của gói Free – cần biết:**

| Vấn đề | Hệ quả | Cách xử lý đã làm |
|---|---|---|
| Ngủ sau 15 phút không có request đến | Bot rớt kết nối Discord, lỡ thông báo | Flask `/health` + self-ping mỗi 5 phút + pinger ngoài |
| Filesystem tạm (xoá khi restart/redeploy/ngủ) | Mất SQLite → mất `/setup`, `/subscribe` | Cấu hình qua `CHANNEL_ID`/`SEED_LEAGUES`, tự nạp lại mỗi lần khởi động. Lệnh `/setup`, `/subscribe` vẫn dùng được nhưng **chỉ có hiệu lực đến lần restart kế tiếp** |
| Render có thể restart Free service bất cứ lúc nào | Có thể lỡ một mốc báo; nếu restart ngay sau mốc báo (≤2 phút) có thể báo lặp 1 lần vì mất lịch sử chống trùng | Chấp nhận |
| 750 giờ Free/tháng cho **cả workspace** | 1 service chạy 24/7 ≈ 720–744 giờ → vừa đủ; có service Free thứ hai là hết giờ và bị khoá đến đầu tháng sau | Chỉ chạy 1 service Free |

**Lỗi `429 Too Many Requests` / Cloudflare `Error 1015` lúc đăng nhập:** Discord tạm chặn IP của Render vì nhiều bot dùng chung IP đó. Đây **không phải lỗi token hay lỗi code**. Bot sẽ tự chờ 5 phút rồi thử lại (rồi 10, 20, 30 phút) thay vì sập liên tục. Nếu bị chặn hơn 1–2 giờ: tạo Web Service mới ở **region khác** (vd. Singapore; region không đổi được sau khi tạo) hoặc dùng VPS/máy có IP riêng.

Nếu cần chạy ổn định, đổi `plan: free` thành `starter` (7 USD/tháng): hết ngủ, và có thể gắn Persistent Disk (`DB_PATH=/var/data/bot.db`) để `/setup` không bị mất.

## 7. Cấu trúc

```
bot.py               # bot, scheduler, lệnh slash
keep_alive.py        # Flask: /health cho Render Web Service
render.yaml          # Blueprint deploy Render
config.py            # cài đặt (.env) + danh sách giải
embeds.py            # dựng embed
db.py                # SQLite: kênh, đăng ký giải, chống gửi trùng
models.py            # lớp Event
providers/           # espn.py · thesportsdb.py · sportstimes.py
check_sources.py     # kiểm tra nguồn dữ liệu
```
