# IsleWarden — Lộ trình

Trạng thái: **M0–M5 đã có bản chạy được** — Core + Agent + Server dựng và test end-to-end.
Toàn bộ solution build sạch (0 cảnh báo/lỗi); 79 test Core + 65 test Server pass (26/09/2026).

## M0 — Nền tảng ✅
- [x] Cấu trúc dự án + tài liệu thiết kế.
- [x] Mô hình `Policy` (JSON).
- [x] `ProcessScanner`: khớp blocklist theo tên (+ SHA-256 tuỳ chọn).
- [x] `FileIntegrityChecker`: SHA-256 + chữ ký Authenticode.
- [x] `Scanner` gộp + `ScanReport` JSON.
- [x] `IsleWarden.Agent` CLI: `--once` hoặc quét theo chu kỳ, chế độ observe.

## M1 — Vững chắc hoá Core ✅
- [x] Dự án test (`launcher/IsleWarden.Core.Tests`) với xUnit — 28 test.
- [x] Module **thứ tự khởi động** (`StartupOrderChecker`: game mở sau launcher).
- [x] Module **soi module/DLL** (`ModuleScanner`: DLL cấm + đường dẫn đáng ngờ; suy biến an toàn khi bị EAC chặn đọc).
- [x] Chuẩn hoá `Finding` + `Severity` enum + mã lỗi ổn định (`FindingCodes`).
- [x] Tách `IProcessSource`/`IModuleSource` để test không phụ thuộc máy thật.

## M2 — Toàn vẹn file nâng cao ✅
- [x] `AuthenticodeVerifier`: `WinVerifyTrust` đầy đủ (chuỗi chứng chỉ + timestamp), phân biệt không ký / sai chữ ký / sai bên ký.
- [x] Baseline hash file game tự sinh (`BaselineBuilder`) + so sánh theo build (`BaselineChecker`): thiếu/sửa/file lạ.
- [x] Cache hash theo (kích thước, mtime) + băm dần file lớn qua nhiều lần quét.
- [x] Tự dò thư mục game & build ID qua Steam (`SteamLocator` + `VdfParser`), policy dùng `{GameDir}`.

## M3 — Dịch vụ phía server ✅
- [x] `IsleWarden.Server` (ASP.NET minimal API, chạy được cả trên Linux VPS). Từ 26/09/2026 thay bằng server
      Python (FastAPI) trong `server/`, cùng HTTP API và schema database.
- [x] Cấp token ngắn hạn (chỉ lưu hash) + whitelist Steam ID; lưu SQLite.
- [x] Endpoint nhận báo cáo quét (lưu để tra soát) + phát policy/baseline cho launcher.
- [x] Ban list (Steam ID / thiết bị / linh kiện fingerprint) + xét duyệt thiết bị; endpoint admin có khoá.

## M4 — Vòng đời phiên ✅
- [x] Heartbeat client → server kèm báo cáo quét định kỳ.
- [x] Gỡ whitelist khi vi phạm (Enforce theo ngưỡng), khi admin ban, hoặc khi **mất heartbeat** (`SessionSweeper`).
- [x] Cầu nối whitelist ↔ The Isle: `none` / `file` / `rcon` (opcode addwhitelist/removewhitelist của Evrima).

## M5 — Vận hành ✅
- [x] Cảnh báo Discord webhook cho admin (phát hiện gian lận, thu hồi phiên, ban, mất tín hiệu).
- [x] Đóng gói: `build-release.ps1` → Agent 1 file `.exe` self-contained (~70 MB) + thư mục server.
- [x] Trang disclosure/consent tĩnh (`server/islewarden_server/static/consent.html`, tự đọc policy hiện hành).
- [x] Tài liệu vận hành cho admin (`docs/SERVER-SETUP.md`).

## Sau M5 — các tầng phát hiện bổ sung
- [x] **Nhật ký thực thi** (`ExecutionHistoryScanner` + `PrefetchReader`): đọc thư mục Prefetch của
      Windows để bắt công cụ đã tắt trước khi mở launcher. Lọc theo tên trước khi mở file, giới hạn
      cửa sổ 7 ngày, cần quyền quản trị — xem mục [Execution history (Prefetch)](REFERENCE.md#execution-history-prefetch) trong tài liệu tham khảo.
- [x] **Trang quản trị** (`dashboard` React+TS+Vite → `server/islewarden_server/static/admin`, truy vấn ở
      `dashboard.py` + `risk.py`): tổng quan, hồ sơ
      người chơi kèm phần mềm bị gắn cờ, tra cứu báo cáo, ban/gỡ ban/thu hồi phiên/theo dõi, nhật ký
      thao tác, dọn báo cáo cũ. Kèm bảng `findings` chuẩn hoá (tra cứu được), `admin_actions`
      (mọi quyết định tra lại được) và `ban_evidence` (nguồn nhãn để về sau đánh giá lại các luật).
- [x] **Chuyển server sang Python** (26/09/2026): `server/` (FastAPI + SQLite), cùng HTTP API, schema database và
      cấu hình với bản C#; đã đối chiếu từng response với bản C# trước khi gỡ. Bản C# được lưu trữ ngoài repo.
- [x] **Overlay lạ** (`OverlayScanner` + `WindowSource`, 26/09/2026): cửa sổ của tiến trình khác nằm trên game
      lúc game đang ở foreground, có style topmost/layered/click-through hoặc giấu khỏi quay màn hình. Đã nối vào
      `Scanner`, `Policy` (`overlayScan`) và `FindingCodes`; policy mẫu có sẵn allowlist các overlay phổ biến —
      xem mục [Overlay scan](REFERENCE.md#overlay-scan) trong tài liệu tham khảo.

## Điều khiển truy cập (theo `docs/ACCESS-CONTROL-REFERENCE.md` §6)
- [x] Tách các cổng độc lập **thiết bị → ban → thông báo → anti-cheat**; cổng nào chặn thì trả mã riêng
      (`AccessCodes`) + nhãn + chi tiết + mã tra cứu (`R-…` báo cáo, `B-…` ban). Launcher in từng cổng.
- [x] Suất chơi (lease) tách khỏi danh tính thiết bị; hạn tính theo đồng hồ server (`serverTime`); một nguồn
      ân hạn duy nhất (`LeaseGrace` = `HeartbeatSeconds × MissedHeartbeatGrace`, mặc định 75 giây).
- [x] Launcher trả suất chơi kèm lý do khi Ctrl+C / đóng cửa sổ / tắt máy; nối lại suất chơi sau khi bị tắt ngang
      trong thời gian ân hạn; heartbeat lỗi mạng thì thử lại dày hơn cho tới hết hạn.
- [x] Mỗi phiên lưu mã + lý do kết thúc (hiện ở hồ sơ người chơi); các đường kết thúc song song không ghi đè nhau.
- [x] Miễn trừ anti-cheat theo Steam ID do admin cấp (bắt buộc lý do, có hạn, ghi nhật ký), công tắc tổng
      `AllowAntiCheatBypass`; không bao giờ nới ban / thông báo / máy bị từ chối.
- [x] Tự duyệt máy, trừ máy có cờ rủi ro (trùng linh kiện với Steam ID khác hoặc tài khoản đang bị ban, không có
      fingerprint) → chờ admin, kèm lý do trên trang quản trị.
- [x] Không ban hay so trùng theo `cpuId` (mọi CPU cùng đời trả cùng giá trị).
- [x] **Lưới kick** (`server/islewarden_server/enforcer.py`, 26/09/2026): định kỳ đọc `playerlist` (0x40) qua RCON,
      kick (0x30) Steam ID đang online mà không có suất chơi sau `KickGraceSeconds`; người đang bị ban bị kick ngay;
      `ExemptSteamIds` cho staff. Tắt mặc định (`Whitelist:KickWithoutLease`); RCON lỗi thì không kick ai và báo Discord.
      Vẫn giữ whitelist của game làm lớp chính — xem mục [Whitelist on or off](REFERENCE.md#whitelist-on-or-off).
- [ ] Kiểm chứng với server thật: gỡ whitelist có đá người đang chơi không; RCON `kick` 0x30
      (`Whitelist:KickOnRevoke`, đang tắt mặc định) — `docs/TEST-WITH-REAL-SERVER.md` mục 3, bước 8–9; RCON
      `playerlist` 0x40 và định dạng câu trả lời của nó (`Whitelist:KickWithoutLease`) — bước 14–15.
- Cố ý không làm: trial, hàng chờ/ưu tiên (dùng `bQueueEnabled` + `VIPs=` sẵn có của Evrima), thu hồi slot người
  treo máy (cần dữ liệu trong game) — lý do ở `ACCESS-CONTROL-REFERENCE.md` §6.7.
- [ ] Proxy-DLL cạnh exe game + kiểm tra tinh chỉnh INI (`r.Fog`, `grass.DensityScale`…).
- [ ] Nonce/challenge cho từng lượt quét (chống phát lại báo cáo "sạch" cũ).

## Còn để mở (ngoài phạm vi M1–M5)
- [ ] Ký số bản phát hành Agent (chứng chỉ code-signing) trước khi phát cho người chơi.
- [ ] Fingerprint bền hơn (serial ổ đĩa/mainboard qua WMI) — xem `docs/HWID-BANNING.md`.
- [ ] Thử nghiệm thực địa chế độ Observe để tinh chỉnh danh sách cấm & ngưỡng báo nhầm.
