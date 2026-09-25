# IsleWarden — Thiết kế hệ thống chống gian lận cho server The Isle

> Công cụ chống gian lận cho server The Isle EVRIMA **do bạn vận hành**.
> Code mới hoàn toàn, dùng kỹ thuật công khai. Đây **không** phải bản sao,
> không dịch ngược, không tái tạo mã đã làm rối của bất kỳ launcher nào khác.

---

## 0. Tóm tắt

IsleWarden gồm một **launcher/agent phía người chơi** (tự nguyện dùng để vào
server của bạn) và một **dịch vụ phía server** (cấp token, whitelist, nhận báo
cáo, cảnh báo admin). Mục tiêu là răn đe và phát hiện các công cụ gian lận phổ
biến, chứ không phải bảo vệ tuyệt đối ở mức kernel.

## 1. Nguyên tắc

1. **Chỉ trên hạ tầng bạn sở hữu** — server, API, whitelist của bạn; và máy
   người chơi *tự nguyện* chạy launcher để vào server bạn.
2. **Minh bạch (disclosure + consent)** — người chơi được thông báo rõ launcher
   kiểm tra những gì trước khi quét. Ghi lại phiên bản disclosure đã đồng ý.
3. **Tối thiểu hoá dữ liệu** — chỉ thu tín hiệu cần để quyết định cho vào hay
   không (tên tiến trình khớp blocklist, hash file game). Không hút dữ liệu
   riêng tư không liên quan.
4. **Fail-safe, không phá máy người chơi** — mặc định chế độ *observe* (chỉ ghi
   log). Hành động chặn chỉ là *không cấp token vào server*, không xoá/không sửa
   máy người chơi.

## 2. Vì sao server The Isle cần launcher đồng hành

The Isle EVRIMA gần như không cho phía server soi máy client qua mạng. Do đó
phần lớn "anti-cheat" thực dụng cho server cộng đồng nằm ở **launcher client
bắt buộc**: người chơi chạy launcher để lấy token, launcher tự kiểm tra máy rồi
báo cho server; server chỉ whitelist những ai vượt qua kiểm tra. Vì vậy IsleWarden
chia làm hai tầng bổ sung cho nhau:

| Tầng | Chạy ở đâu | Dữ liệu chạm tới | Độ tin cậy |
|------|-----------|------------------|------------|
| Server-side | Máy/VPS của bạn | Log & trạng thái server bạn sở hữu | Cao, không tranh cãi |
| Client-side (launcher) | Máy người chơi, opt-in | Tiến trình/file trên máy họ, có consent | Vừa (user-mode có thể bị qua mặt) |

## 3. Kiến trúc tổng thể

```
   Người chơi                         Hạ tầng của bạn
 ┌───────────────┐   1.xác thực   ┌──────────────────────┐
 │ IsleWarden    │ ─────────────► │ IsleWarden.Server     │
 │ Agent/Launcher│   2.token+     │  - cấp token ngắn hạn │
 │  - quét TT    │ ◄───────────── │  - whitelist Steam ID │
 │  - hash file  │   3.heartbeat  │  - nhận báo cáo scan  │
 │  - mở game    │ ─────────────► │  - ban list           │
 └───────────────┘                └───────────┬──────────┘
                                               │ whitelist / RCON
                                               ▼
                                    ┌──────────────────────┐
                                    │  The Isle Dedicated   │
                                    │  Server (của bạn)     │
                                    └──────────────────────┘
                                               │ log / cảnh báo
                                               ▼
                                     Discord webhook (admin)
```

### Thành phần

- **IsleWarden.Core** — thư viện .NET chứa các module phát hiện (thuần logic,
  test được, không phụ thuộc UI/mạng).
- **IsleWarden.Agent** — ứng dụng client: đọc policy, chạy quét theo chu kỳ,
  xuất báo cáo JSON, (về sau) xin token + gửi heartbeat.
- **IsleWarden.Server** — dịch vụ phía server: cấp token, quản lý whitelist &
  ban, nhận báo cáo, đẩy cảnh báo. *(Lộ trình M3.)* Ban đầu viết bằng ASP.NET; từ
  26/09/2026 là server Python trong thư mục `server/`.
- **IsleWarden.Admin** — cảnh báo Discord + log tập trung. *(Lộ trình M5.)*

## 4. Các tầng phát hiện

### 4.1 Server-side (sạch — làm trước)
- **Whitelist/blacklist Steam ID**: chỉ cho token nếu không nằm trong ban list.
- **Phân tích log server**: relog quá nhanh (nghi combat-log), spam chat, từ
  cấm; nếu có mod cấp toạ độ thì phát hiện teleport/tốc độ bất thường.
- **Toàn vẹn cấu hình server**: theo dõi `Game.ini`/mod của server bạn không bị
  sửa ngoài ý muốn.

### 4.2 Client-side qua launcher (opt-in, có disclosure)
- **Quét tiến trình theo blocklist**: khớp theo tên (không phân biệt hoa
  thường) và tuỳ chọn theo SHA-256, để hạ nhầm lẫn. Ví dụ: Cheat Engine,
  ArtMoney, injector đã biết.
- **Quét module/DLL** nạp vào tiến trình game: dấu hiệu inject.
- **Toàn vẹn file game**: SHA-256 + chữ ký Authenticode của các file quan trọng.
- **Thứ tự khởi động**: game phải được mở sau/qua launcher (chống chạy game
  "chui" không kiểm tra).
- **Heartbeat**: mất heartbeat → token hết hạn → server gỡ khỏi whitelist.

## 5. Mô hình token & whitelist

1. Người chơi mở launcher, đăng nhập Steam (OpenID) rồi Discord; phải có role được phép trong Discord server.
2. Launcher chạy quét lần đầu; nếu sạch, server cấp **token ngắn hạn** và ghi
   Steam ID vào whitelist của game server.
3. Trong lúc chơi, launcher gửi **heartbeat + báo cáo quét** định kỳ.
4. Nếu phát hiện vi phạm (hoặc mất heartbeat), server **gỡ khỏi whitelist** →
   game server không cho vào lại. Không có hành động nào tác động vào máy người chơi.
   *(Gỡ whitelist có đá người **đang** ở trong server hay không thì chưa kiểm chứng với Evrima; tuỳ chọn
   `Whitelist:KickOnRevoke` gửi thêm RCON kick — xem `ACCESS-CONTROL-REFERENCE.md` §6.7.)*
5. Mỗi lý do chặn là một cổng riêng có mã riêng (thiết bị, ban, thông báo, anti-cheat, suất chơi) — chi tiết ở
   `SERVER-SETUP.md` mục 7.

## 6. Chính sách (`policy.json`)

Điều khiển bằng file (và về sau tải từ server):

- `mode`: `observe` (chỉ log) hoặc `enforce`.
- `intervalSeconds`: chu kỳ quét.
- `disclosure` / `disclosureVersion`: văn bản thông báo & phiên bản consent.
- `blockedProcesses[]`: `{ name, reason, severity, sha256? }`.
- `protectedFiles[]`: `{ path, sha256?, requireSignature, expectedSigner? }`.
- `gameProcessName`: tên tiến trình game để soi module/thứ tự khởi động.

## 7. Minh bạch & pháp lý

- Hiển thị disclosure **trước** khi quét; lưu lại consent + phiên bản.
- Chỉ triển khai cho server bạn sở hữu; nêu rõ trong nội quy/Discord.
- Tôn trọng luật dữ liệu cá nhân: không lưu dữ liệu ngoài phạm vi cần thiết,
  nêu thời gian lưu trữ, cho cơ chế khiếu nại (ticket).

## 8. Công nghệ

- **Launcher + thư viện quét: .NET 10 / C#** — khớp toolchain sẵn có trên máy (SDK 10.0.401), tốt cho
  Windows API (tiến trình, chữ ký, WMI, DPAPI).
- **Server: Python 3.10+ (FastAPI + SQLite)** — thư mục `server/`. Ban đầu server cũng là C# (ASP.NET
  minimal API) để dùng chung một ngôn ngữ; ngày 26/09/2026 chuyển sang Python, giữ nguyên HTTP API và schema
  database. Hai bên không còn dùng chung code, chỉ chung giao thức HTTP.
- Client: console Windows. Cảnh báo: Discord webhook.

## 9. Cấu trúc dự án

```
IsleWarden/
├─ launcher/                   (C#: launcher cho người chơi)
│  ├─ IsleWarden.Agent/        (launcher CLI)
│  ├─ IsleWarden.Core/         (thư viện phát hiện + giao thức)
│  ├─ IsleWarden.Core.Tests/
│  └─ IsleWarden.slnx
├─ server/                     (Python: server anti-cheat)
├─ dashboard/                  (React: trang quản trị, build vào server/)
├─ config/                     (policy mẫu)
└─ docs/
```

## 10. Lộ trình (chi tiết trong ROADMAP.md)

- **M0** — Scaffold + policy model + quét tiến trình + hash/chữ ký file + CLI
  observe. ⟵ *bản đầu tiên, đã có trong repo.*
- **M1** — Test tự động cho Core; module thứ tự khởi động + soi module DLL.
- **M2** — Toàn vẹn file game nâng cao (WinVerifyTrust đầy đủ chuỗi + timestamp).
- **M3** — IsleWarden.Server: token + whitelist + nhận báo cáo.
- **M4** — Heartbeat + gỡ whitelist khi vi phạm/mất tín hiệu.
- **M5** — Cảnh báo Discord + đóng gói cài đặt + tài liệu người chơi.

## 11. Giới hạn (nói thẳng)

Anti-cheat **user-mode** như thế này có thể bị qua mặt bởi cheat chạy ở
kernel-mode hoặc bằng cách sửa/giả lập launcher. Nó có giá trị **răn đe** và bắt
được đa số công cụ phổ thông, nhưng không phải lá chắn tuyệt đối. Với server
nghiêm túc nên **kết hợp EasyAntiCheat (EAC)** của game và coi IsleWarden là lớp
bổ sung ở tầng quản trị server.
