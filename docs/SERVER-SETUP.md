# Vận hành server IsleWarden

Hướng dẫn cho admin: chạy dịch vụ, cấu hình đồng bộ whitelist sang The Isle, cấu hình đăng nhập Steam + Discord,
ban theo Steam ID / máy, và tạo baseline file game. Mọi lệnh chạy từ thư mục bản phát hành server
(`dist/server`, hoặc `server/` trong mã nguồn).

## 1. Chạy server

Server viết bằng Python (cần Python 3.10 trở lên, chạy được trên Windows lẫn Linux). Lần đầu cài thư viện:

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Rồi chạy (trên Windows thay `.venv/bin/` bằng `.venv\Scripts\`):

```
.venv/bin/python -m islewarden_server --host 127.0.0.1 --port 5088
```

Để server nghe ở `127.0.0.1` và đặt reverse proxy có HTTPS phía trước. Cách chạy thành dịch vụ systemd trên Linux
có trong `server/README.md`.

Cấu hình đọc từ `appsettings.json` mục `IsleWarden`, hoặc ghi đè bằng biến môi trường
`IsleWarden__<Khoá>` (ví dụ `IsleWarden__AdminKey`). Các khoá quan trọng:

| Khoá | Ý nghĩa |
|------|---------|
| `AdminKey` | Khoá cho endpoint quản trị (header `X-Admin-Key`). **Bắt buộc** — chưa đặt thì `/api/admin/*` bị khoá. |
| `FingerprintPepper` | Chuỗi bí mật cố định để băm fingerprint. Đặt một lần rồi giữ nguyên. |
| `PolicyPath` | File policy phát cho launcher (mặc định `server-policy.json`). Sửa file là server tự nạp lại. |
| `EnforceThreshold` | Mức phát hiện tối thiểu để chặn ở chế độ Enforce (mặc định `High`). |
| `HeartbeatSeconds` / `MissedHeartbeatGrace` | Chu kỳ heartbeat và số chu kỳ được lỡ. Mặc định 30 × 2,5 = **75 giây ân hạn** trước khi suất chơi hết hạn — đủ cho mạng chớp hay launcher khởi động lại mà không rớt. |
| `AutoApproveDevices` | `true`: máy mới vào được ngay — **trừ máy có cờ rủi ro** (trùng linh kiện với máy của Steam ID khác hoặc tài khoản đang bị ban, không gửi fingerprint), luôn chờ duyệt. `false`: admin duyệt tay mọi máy. |
| `AllowAntiCheatBypass` | Công tắc tổng cho miễn trừ anti-cheat (mục 5). `false` = mọi miễn trừ mất tác dụng ngay, ví dụ trong giải đấu. Mặc định `true`. |
| `Whitelist.Mode` | `none` (chỉ log) · `rcon` · `file`. |
| `Whitelist.KickOnRevoke` | Gửi thêm RCON `kick` (0x30) khi suất chơi cuối của người chơi kết thúc. **Opcode chưa kiểm chứng với server thật** — mặc định `false`, xem `TEST-WITH-REAL-SERVER.md` mục 3 trước khi bật. |
| `Whitelist.KickWithoutLease` | Lưới an toàn: cứ `KickPollSeconds` giây (mặc định 20) server hỏi game ai đang online bằng RCON `playerlist` (0x40), rồi kick (0x30) Steam ID nào không có suất chơi sau `KickGraceSeconds` giây (mặc định 60). Người đang bị ban bị kick ngay. **Cả hai opcode chưa kiểm chứng với server thật** — mặc định `false`, chạy bước 14–15 trong `REFERENCE.md` trước khi bật. RCON lỗi thì không ai bị kick. |
| `Whitelist.ExemptSteamIds` | Steam ID không bao giờ bị kick vì thiếu suất chơi: staff chơi không cần launcher. Nên trùng với `WhitelistIDs=` trong `Game.ini` (server không đọc được file đó). |
| `PublicUrl` | Địa chỉ công khai của server anti-cheat, ví dụ `https://ac.example.com`. Steam và Discord trả trình duyệt về đây sau khi đăng nhập. |
| `Discord.Required` | `true` (mặc định): người chơi phải đăng nhập Discord, ở trong Discord server và có role được phép. `false` chỉ để thử nghiệm. |
| `Discord.ClientId` / `ClientSecret` / `BotToken` | Lấy từ Discord application (mục 3). |
| `Discord.GuildId` / `RequiredRoleIds` | ID Discord server và (các) role được vào chơi. Có một trong các role là đủ; để trống danh sách = chỉ cần là thành viên. |
| `Discord.RoleRecheckMinutes` | Bao lâu kiểm tra lại role của người đang chơi (mặc định 10 phút). Mất role → suất chơi kết thúc. |
| `Discord.WebhookUrl` | Webhook nhận cảnh báo. |

Chế độ `observe`/`enforce` nằm trong file policy (`server-policy.json`), không phải appsettings.
Bắt đầu bằng `observe` để đo tỉ lệ báo nhầm, khi yên tâm thì đổi `mode` sang `enforce`.

## 2. Đồng bộ whitelist sang The Isle

- **`none`** (mặc định, an toàn): chỉ ghi log dự định thêm/xoá — dùng khi chạy thử.
- **`rcon`**: đẩy qua RCON của The Isle (lệnh `addwhitelist` / `removewhitelist`). Cần
  `Whitelist.RconHost`, `RconPort`, `RconPassword`. Server phải bật whitelist trong `Game.ini`.
- **`file`**: ghi file whitelist (mỗi dòng một Steam ID) tại `Whitelist.FilePath`, ghi kiểu
  nguyên tử để game không đọc phải file dở.

Ở mode `rcon` có thể bật thêm `Whitelist.KickWithoutLease` để kick người đang ở trong game mà không có suất chơi.
Nên giữ `bServerWhitelist=true` và coi đây là lớp thứ hai. Nếu tắt whitelist của game thì lưới này thành cổng duy nhất:
ai cũng vào được, người không mở launcher bị kick sau khoảng một phút, và lúc RCON lỗi thì server thành server mở.
Bảng so sánh hai cách nằm ở mục "Whitelist on or off" trong `REFERENCE.md`.

## 3. Đăng nhập người chơi: Steam + Discord

Không có mã mời. Người chơi đăng nhập Steam (chứng minh Steam ID) rồi Discord (chứng minh đang ở trong Discord
server và có role được phép). **Cấp role trong Discord = cho phép vào chơi; gỡ role = chặn** (người đang chơi bị
thu hồi suất chơi ở lần kiểm tra lại kế tiếp, mặc định trong vòng 10 phút).

Chuẩn bị một lần:

1. Vào https://discord.com/developers/applications → *New Application*.
2. Trang **OAuth2**: chép *Client ID* và *Client Secret*; thêm Redirect `https://<PublicUrl>/login/discord/callback`.
3. Trang **Bot**: *Reset Token* rồi chép token. Không cần bật Privileged Gateway Intents.
4. Mời bot vào Discord server: mở
   `https://discord.com/oauth2/authorize?client_id=<Client ID>&scope=bot&permissions=0` và chọn server. Bot không
   cần quyền gì, chỉ cần có mặt để đọc role của thành viên.
5. Trong Discord bật *Developer Mode* (User Settings → Advanced), chuột phải vào server → *Copy Server ID*
   (`GuildId`), chuột phải vào role → *Copy Role ID* (`RequiredRoleIds`).
6. Đặt các giá trị bằng biến môi trường, ví dụ `IsleWarden__Discord__ClientSecret`, `IsleWarden__Discord__BotToken`,
   `IsleWarden__Discord__RequiredRoleIds__0`.

Người chơi chạy:

```
IsleWarden.Agent login --server https://<server>
IsleWarden.Agent play --launch
```

`login` mở trình duyệt (Steam → Discord) rồi nhận khoá thiết bị. Mỗi tài khoản Discord chỉ liên kết được một Steam ID
và ngược lại; muốn đổi thì admin gỡ liên kết ở hồ sơ người chơi (nút *Gỡ liên kết* trong mục Discord).

## 4. Ban

Ban nhanh theo Steam ID (kèm mọi thiết bị + fingerprint đã ghi nhận). Suất chơi đang chạy bị thu hồi ngay
với mã `banned` và whitelist bị gỡ — không đợi heartbeat kế tiếp. Linh kiện `cpuId` không bao giờ bị ban (mọi CPU
cùng đời có cùng giá trị, ban theo nó là chặn nhầm cả loạt người):

```
curl -X POST http://<server>/api/admin/bans/steam -H "X-Admin-Key: <KEY>" ^
     -H "Content-Type: application/json" -d "{\"steamId\":\"7656119...\",\"reason\":\"aimbot\"}"
```

Endpoint khác: `GET/POST/DELETE /api/admin/bans`, `GET /api/admin/devices`,
`POST /api/admin/devices/{id}/approve|reject`, `GET /api/admin/sessions`, `GET /api/admin/whitelist`.

## 5. Miễn trừ anti-cheat (streamer, staff)

Streamer chạy OBS, overlay, công cụ quay màn hình… dễ dính phát hiện liên tục. Admin cấp miễn trừ theo **Steam ID**
(trên trang quản trị: hồ sơ người chơi → *Miễn trừ anti-cheat*, hoặc qua API):

```
curl -X POST http://<server>/api/admin/players/7656119.../bypass -H "X-Admin-Key: <KEY>" ^
     -H "Content-Type: application/json" -d "{\"reason\":\"streamer, OBS\",\"expiresUtc\":\"2026-12-31T23:59:59Z\"}"
curl -X DELETE http://<server>/api/admin/players/7656119.../bypass -H "X-Admin-Key: <KEY>"
curl http://<server>/api/admin/bypasses -H "X-Admin-Key: <KEY>"
```

Miễn trừ chỉ nới **đúng hai chỗ**: cổng anti-cheat (lúc xin vào và mỗi heartbeat) và bước chờ duyệt máy. Nó
**không** nới ban, máy bị từ chối, role Discord hay thông báo; báo cáo quét vẫn được ghi (Discord ghi rõ "đang được miễn trừ").
Server tra miễn trừ theo Steam ID của chính thiết bị đang xin ở mỗi lần gọi — launcher không giữ cờ nào, nên không
mang miễn trừ của người này sang tài khoản khác được. Bắt buộc có lý do; nên đặt hạn. Mọi lần cấp/gỡ vào nhật ký admin.

Khác với `WhitelistIDs=` / `VIPs=` trong `Game.ini`: hai danh sách đó nằm ở server game — người trong `WhitelistIDs=`
vào được **không cần launcher**, còn `VIPs=` chỉ là ưu tiên hàng chờ khi server đầy. Miễn trừ ở đây vẫn bắt chạy
launcher, chỉ không chặn vì phát hiện.

## 6. Baseline file game (chống sửa file)

Trên một máy có **bản game sạch**, tạo baseline rồi tải lên server theo build ID:

```
IsleWarden.Agent baseline --out 24664737.json
curl -X PUT http://<server>/api/admin/baselines/24664737 -H "X-Admin-Key: <KEY>" ^
     --data-binary "@24664737.json"
```

Launcher tự tải baseline đúng build khi vào server. Mỗi lần game cập nhật (đổi build ID), tạo lại baseline mới.

## 7. Vòng đời phiên (tóm tắt)

1. `play` → launcher quét, gửi báo cáo, xin **suất chơi** (lease). Server xét lần lượt các cổng độc lập:
   **thiết bị → ban → Discord → thông báo → anti-cheat**. Cổng nào chặn thì trả mã riêng của cổng đó (bảng dưới), kèm nhãn,
   chi tiết và mã tra cứu — launcher in ra từng cổng để người chơi biết *cái gì* đang chặn.
2. Qua hết → server cấp suất chơi (token riêng, tách khỏi khoá thiết bị) và thêm Steam ID vào whitelist.
3. Launcher gửi heartbeat + báo cáo định kỳ; hạn suất chơi tính theo đồng hồ server (`serverTime`). Mất heartbeat
   quá thời gian ân hạn (75 giây) → `SessionSweeper` cho hết hạn và gỡ whitelist.
4. Thoát chủ động (Ctrl+C, đóng cửa sổ launcher, tắt máy) → launcher **trả suất chơi kèm lý do**, server gỡ whitelist ngay.
   Launcher bị tắt ngang rồi mở lại trong thời gian ân hạn → **nối lại** suất chơi cũ, người chơi không rớt.
5. Phát hiện vi phạm giữa chừng (Enforce), admin ban, admin từ chối máy, admin thu hồi → thu hồi suất chơi + gỡ whitelist ngay.
   Mất role Discord, rời Discord server hay bị gỡ liên kết → thu hồi ở lần kiểm tra lại kế tiếp (`Discord.RoleRecheckMinutes`).

Gỡ whitelist chắc chắn chặn lần vào **sau**. Người đang ở trong server có bị đá theo không thì chưa kiểm chứng với
Evrima — bật `Whitelist.KickOnRevoke` để gửi thêm RCON kick ngay lúc suất chơi kết thúc, hoặc `Whitelist.KickWithoutLease`
để định kỳ kick ai đang online mà không có suất chơi (cả hai đều chưa kiểm chứng).

| Mã | Cổng | Ý nghĩa | Mã tra cứu |
|----|------|---------|-----------|
| `device-unknown` | Thiết bị | Máy chưa đăng nhập hoặc khoá sai | |
| `device-pending` | Thiết bị | Chờ admin duyệt (có thể do cờ rủi ro — admin xem lý do ở tab Thiết bị) | |
| `device-rejected` | Thiết bị | Admin từ chối máy | |
| `banned` | Ban | Steam ID / máy / linh kiện nằm trong ban list | `B-<id ban>` |
| `discord-not-linked` | Discord | Steam ID chưa liên kết Discord (hoặc admin đã gỡ liên kết) — chạy lại `login` | |
| `discord-not-member` | Discord | Tài khoản Discord không còn trong Discord server | |
| `discord-role-missing` | Discord | Chưa có hoặc đã mất role được vào chơi | |
| `consent-required` | Thông báo | Nội dung thông báo đổi, cần đồng ý lại | |
| `anticheat-blocked` | Anti-cheat | Phát hiện đạt ngưỡng chặn (chỉ ở Enforce) | `R-<id báo cáo>` |
| `lease-expired` | Suất chơi | Mất tín hiệu launcher quá thời gian ân hạn | |
| `lease-revoked` | Suất chơi | Admin thu hồi | |
| `lease-released` | Suất chơi | Launcher tự trả (kèm lý do: `launcher-stopped`, `launcher-closed`, `system-shutdown`) | |
| `lease-invalid` | Suất chơi | Token sai hoặc phiên không tồn tại | |

Mỗi phiên lưu lại mã + lý do kết thúc; trang quản trị hiện ở cột *Kết thúc vì* trong hồ sơ người chơi. Người chơi gửi
mã tra cứu `R-…` thì admin mở thẳng `/admin/#/reports/<id>`.
