# Kiểm thử IsleWarden với server The Isle

Hai mức kiểm thử. Mức 1 **không cần server game** và chạy được trong vài giây — dùng cho
phần lớn công việc hằng ngày. Mức 2 dựng server EVRIMA thật, chỉ cần khi muốn xác nhận
lần cuối trước khi bàn giao.

Chỉ chế độ whitelist `rcon` là cần tới server game. Mọi thứ còn lại — quét, đăng ký,
cấp token, heartbeat, `SessionSweeper`, ban, Discord webhook, mode `none` và `file` —
kiểm thử được mà không cần The Isle chạy.

---

## 1. Không cần server game

### 1.1 Test tự động

```
dotnet test launcher/IsleWarden.slnx
cd server; .venv\Scripts\python -m pytest
```

Lệnh đầu test launcher và thư viện quét (C#); lệnh sau test server (Python). Bộ test server
(`server/tests`) dựng một **server RCON giả** nói đúng giao thức nhị phân của Evrima
(`fake_rcon.py`), nên kiểm tra được đúng byte đi trên đường truyền:

- frame xác thực `0x01 + mật khẩu + 0x00`, rồi frame lệnh `0x02 + opcode + tham số + 0x00`;
- opcode `0x82` khi thêm, `0x83` khi xoá, `0x10` khi thông báo;
- tham số nhiều giá trị giữ nguyên dấu phẩy, không bị escape;
- server game **không trả lời** → client coi như đã gửi xong (không ném lỗi);
- RCON **không kết nối được** → người chơi sạch vẫn được cấp token và bảng `whitelist`
  vẫn đúng, chỉ ghi log lỗi;
- câu trả lời `playerlist` bị chia thành nhiều gói vẫn được đọc đủ.

`test_enforcer.py` kiểm tra lưới kick (`KickWithoutLease`) với danh sách người chơi giả và đồng hồ giả:
đủ thời gian ân hạn mới kick, người có suất chơi và staff trong `ExemptSteamIds` không bị đụng tới, người đang
bị ban bị kick ngay, người vừa bị kick vào lại thì không được ân hạn lần hai, RCON lỗi hoặc danh sách không có
Steam ID thì không kick ai.

Điểm cuối quan trọng nhất: server game sai cổng hoặc đang sập thì luồng cấp token không
được sập theo.

### 1.2 Mock RCON để xem bằng mắt

Khi muốn thấy server thực sự gửi gì ra ngoài, chạy mock ở một cửa sổ:

```bash
cd server
.venv\Scripts\python tools\mock_rcon.py --port 8888 --password bimat
```

Rồi trỏ server vào nó (cửa sổ khác, cũng trong thư mục `server`):

```bash
$env:IsleWarden__Whitelist__Mode = "rcon"; $env:IsleWarden__Whitelist__RconHost = "127.0.0.1"; $env:IsleWarden__Whitelist__RconPort = "8888"; $env:IsleWarden__Whitelist__RconPassword = "bimat"; .venv\Scripts\python -m islewarden_server --dev
```

Mỗi lần cấp/thu hồi phiên, mock in ra frame đã giải mã:

```
[23:25:44] conn 127.0.0.1:57790
[23:25:44]   auth      password="bimat" -> ok
[23:25:44]   exec 0x82 addwhitelist     arg="76561198000000001"
```

Sai mật khẩu sẽ hiện `-> MISMATCH` — cách nhanh nhất để soi lỗi cấu hình. Thêm `--silent`
để mock nhận lệnh mà không trả lời, dựng lại tình huống server game im lặng.

Bật thêm `IsleWarden__Whitelist__KickOnRevoke=true` thì khi suất chơi cuối của người chơi kết thúc, mock in thêm
frame kick — lý do là đúng nhãn của hệ thống đã ngắt (mất tín hiệu, admin thu hồi, launcher trả...):

```
[01:12:09]   exec 0x83 removewhitelist  arg="76561198000000001"
[01:12:09]   exec 0x30 kick             arg="76561198000000001,Launcher đã trả suất chơi."
```

Muốn xem lưới kick chạy thì thêm `--players 76561198000000002` cho mock (mock sẽ báo Steam ID đó đang online) và
`$env:IsleWarden__Whitelist__KickWithoutLease = "true"` cho server. Cứ 20 giây mock in một frame `playerlist`, và
sau `KickGraceSeconds` thì kick Steam ID đó vì nó không có suất chơi:

```
[03:47:53]   exec 0x40 playerlist       arg=""
[03:47:59]   exec 0x30 kick             arg="76561198000000002,Không có suất chơi: mở launcher IsleWarden và đăng nhập Steam + Discord rồi vào lại."
```

### 1.3 Mode `file`

```
IsleWarden__Whitelist__Mode=file
IsleWarden__Whitelist__FilePath=whitelist.txt
```

Ghi mỗi dòng một Steam ID, ghi kiểu nguyên tử (file `.tmp` rồi thay thế).

> **Lưu ý:** Evrima giữ whitelist trong `Game.ini` (`WhitelistIDs=`), không đọc file danh
> sách rời. Mode `file` dùng để kiểm thử hoặc cho công cụ khác của bạn đọc — muốn đồng bộ
> thật vào game thì dùng mode `rcon`. Nếu nhà cung cấp hosting của bạn có cơ chế whitelist
> theo file riêng, kiểm tra tài liệu của họ trước khi dựa vào mode này.

---

## 2. Tự host server The Isle EVRIMA

Server files là **bản tải anonymous miễn phí** — không cần tài khoản Steam sở hữu game.

### 2.1 Tải bằng SteamCMD

```bash
steamcmd +login anonymous +force_install_dir C:\theisleserver +app_update 412680 -beta evrima validate +quit
```

- App ID **412680** = The Isle Dedicated Server.
- **Bắt buộc có `-beta evrima`.** Thiếu là tải về bản Legacy cũ, client hiện tại không join được.
- Chạy được cả Windows và Linux.

### 2.2 Cổng cần mở

| Mục đích | Cổng | Giao thức |
|----------|------|-----------|
| Kết nối game | 7777 | UDP |
| Nhiều server trên một máy | 7777–7779 | UDP |
| Hàng chờ (queue) | 10000 | TCP |
| RCON | 8888 | TCP |

### 2.3 Cấu hình

Chạy server **một lần rồi tắt** để nó tự sinh file cấu hình mặc định, sau đó sửa file đó —
đừng viết tay từ đầu, vì tên section thay đổi theo bản build. File nằm ở
`TheIsle/Saved/Config/WindowsServer/` (Linux: `LinuxServer/`).

**`Engine.ini`** — thiếu khối này là server không khởi động được:

```ini
[EpicOnlineServices]
DedicatedServerClientId=<id>
DedicatedServerClientSecret=<secret>
```

Hai giá trị này đi kèm bộ server files mặc định. Giữ nguyên, đừng thay.

**`Game.ini`** — các khoá liên quan tới IsleWarden nằm ở **hai section khác nhau**:

```ini
[/Script/TheIsle.TIGameSession]
ServerName=IsleWarden Test
MaxPlayerCount=10
bQueueEnabled=true
bRconEnabled=true
RconPassword="<mat khau dai>"
RconPort=8888

[/Script/TheIsle.TIGameStateBase]
bServerWhitelist=true
AdminsSteamIDs=<SteamID64 của bạn>
```

> **Đặt sai section là bị bỏ qua âm thầm, không có lỗi nào báo ra.** Danh sách quyền truy
> cập (`bServerWhitelist`, `AdminsSteamIDs`, `WhitelistIDs`, `VIPs`) thuộc
> `TIGameStateBase`; mọi thứ về danh tính server và RCON thuộc `TIGameSession`.

`bServerWhitelist=true` là điều kiện để opcode `addwhitelist`/`removewhitelist` có tác dụng
thật — bật whitelist rồi thì **chỉ** người trong danh sách vào được, đúng như cơ chế
IsleWarden dựa vào.

Sửa `Game.ini` thì **tắt server trước**: Evrima ghi lại file cấu hình khi shutdown, nên sửa
lúc đang chạy sẽ bị ghi đè.

### 2.4 Nối server IsleWarden vào

`appsettings.json`:

```json
"Whitelist": {
  "Mode": "rcon",
  "RconHost": "127.0.0.1",
  "RconPort": 8888,
  "RconPassword": "<mat khau dai>"
}
```

`RconPort` mặc định của IsleWarden đã là `8888`, trùng mặc định của game.

> **Whitelist đẩy qua RCON chỉ sống trong RAM.** Nó mất khi server restart hoặc nạp lại
> config — lúc đó game chỉ còn `WhitelistIDs=` trong `Game.ini`. Và **không có opcode nào
> đọc whitelist về**, chỉ có `togglewhitelist` (0x81) / `addwhitelist` (0x82) /
> `removewhitelist` (0x83). Hệ quả khi kiểm thử: restart server giữa lúc có người chơi thì
> người đang giữ phiên hợp lệ cũng không rejoin được, vì lệnh thêm whitelist (`WhitelistBridge.grant`) chỉ chạy lúc *bắt đầu*
> phiên. Đưa SteamID admin/staff vào `WhitelistIDs=` trong `Game.ini` để RCON chết vẫn vào
> được mà sửa.

---

## 3. Kịch bản end-to-end

Chạy ở chế độ `observe` trước (trong `server-policy.json`), chỉ đổi sang `enforce` khi đã
yên tâm về tỉ lệ báo nhầm.

| Bước | Làm gì | Kỳ vọng |
|------|--------|---------|
| 1 | Tạo baseline trên máy có bản game sạch, upload theo build ID | `GET /api/baselines/<buildId>` trả về baseline đó |
| 2 | Cấp role trong Discord, chạy `IsleWarden.Agent login` (đăng nhập Steam rồi Discord) | Máy hiện trong `GET /api/admin/devices`; hồ sơ người chơi hiện tài khoản Discord |
| 3 | `IsleWarden.Agent play --launch` | RCON gửi `0x82`; Steam ID vào `Game.ini`/whitelist; join được server |
| 4 | Tắt launcher, chờ quá hạn heartbeat | `SessionSweeper` gỡ whitelist (RCON `0x83`); lần join sau bị chặn |
| 5 | Ban theo Steam ID | Whitelist bị gỡ ngay, mọi thiết bị + fingerprint của người đó bị ban |
| 6 | Sửa một file game rồi `play` lại | `observe`: chỉ log + Discord · `enforce`: từ chối cấp token |
| 7 | Tắt server game, rồi `play` | Launcher vẫn được cấp token, server chỉ ghi log lỗi RCON |
| 8 | Đang ở **trong** server, admin thu hồi phiên (`KickOnRevoke=false`) | **Chưa biết — đây là điều cần kiểm chứng:** gỡ whitelist có đá người đang chơi không, hay chỉ chặn lần vào sau? Ghi lại kết quả |
| 9 | Lặp lại bước 8 với `KickOnRevoke=true` | Người chơi bị đá, lý do trong game là nhãn suất chơi (vd "Admin đã thu hồi suất chơi."). Không bị đá → soi log RCON: opcode 0x30 hoặc khuôn `steamId,lý do` có thể sai |
| 10 | Đang chơi, **đóng cửa sổ** launcher | Trong vài giây server ghi `lease-released` / `launcher-closed` và gỡ whitelist (không đợi 75 giây) |
| 11 | Đang chơi, **kill** launcher bằng Task Manager rồi mở lại `play` trong < 75 giây | Launcher báo "Đã nối lại suất chơi", không rớt khỏi server, không sinh `game-started-before-launcher` |
| 12 | Cấp miễn trừ anti-cheat cho một Steam ID, chạy công cụ bị chặn rồi `play` (Enforce) | Được vào, launcher in `[miễn trừ] Anti-cheat`; báo cáo vẫn ghi, Discord ghi "đang được miễn trừ" |
| 13 | Đang chơi, gỡ role được vào chơi trong Discord | Trong vòng `Discord.RoleRecheckMinutes` suất chơi kết thúc với mã `discord-role-missing`; `login` và `play` bị từ chối cho tới khi có lại role |
| 14 | Bật `KickWithoutLease=true`, vào game **không mở launcher** bằng một Steam ID có trong `WhitelistIDs=` nhưng không có trong `ExemptSteamIds` (hoặc chạy server game với `bServerWhitelist=false`) | Log server cho thấy `playerlist` thấy bạn, khoảng `KickGraceSeconds` sau thì bị kick. Nếu log báo `playerlist` không có Steam ID nào thì định dạng trả lời khác với mô tả của các thư viện — ghi lại câu trả lời mà log in ra |
| 15 | Vẫn bật `KickWithoutLease`, làm hỏng RCON (sai mật khẩu hoặc cổng) rồi vào game không mở launcher | Không ai bị kick; sau 3 lần đọc lỗi, kênh Discord nhận cảnh báo "không kick được" |

Bước 7 là bước dễ bị bỏ qua nhất và cũng là bước dễ gây sự cố thật nhất. Bước 8–9 trả lời câu hỏi quan trọng nhất
còn bỏ ngỏ: thu hồi suất chơi có thực sự đưa người chơi ra khỏi server hay không. Bước 14–15 quyết định có bật được
lưới kick hay không.

Xem `docs/SERVER-SETUP.md` cho lệnh cụ thể của từng endpoint quản trị.

---

## 4. Sau mỗi bản cập nhật Evrima

Bản cập nhật đổi build ID, làm baseline cũ hết hiệu lực:

1. Cập nhật server: `steamcmd +login anonymous +force_install_dir ... +app_update 412680 -beta evrima validate +quit`
2. Tạo baseline mới trên máy có bản game sạch rồi upload theo build ID mới
   (`docs/SERVER-SETUP.md` mục 6).

Baseline sai build chỉ sinh finding mức `info`, không làm người chơi mất trạng thái "sạch" —
nhưng cũng có nghĩa là tầng chống sửa file tạm thời không bảo vệ gì.

---

## 5. Lỗi thường gặp

| Hiện tượng | Nguyên nhân hay gặp |
|------------|---------------------|
| Server không khởi động | Thiếu khối `[EpicOnlineServices]` trong `Engine.ini` |
| Client không tìm thấy server | Tải sai nhánh (thiếu `-beta evrima`), hoặc chưa mở 7777/UDP |
| Tự host ở nhà, máy khác vào được nhưng máy mình thì không | NAT loopback của router |
| Mock RCON hiện `MISMATCH` | `RconPassword` hai bên không khớp |
| Log `Whitelist mode=rcon nhưng thiếu cấu hình RconHost` | Chưa đặt `Whitelist.RconHost` |
| RCON gửi thành công nhưng không ai vào được | `bServerWhitelist` còn `false` trong `Game.ini` |
| Sửa `Game.ini` xong khởi động lại thì mất thay đổi | Sửa lúc server đang chạy — Evrima ghi lại config khi shutdown |
| Restart server xong người đang chơi không rejoin được | Whitelist qua RCON chỉ sống trong RAM; cần đẩy lại tập phiên đang hoạt động |
| Bị thu hồi phiên nhưng người chơi vẫn ở trong server | Gỡ whitelist có thể chỉ chặn lần vào sau — thử `Whitelist:KickOnRevoke=true` (bước 9 ở mục 3) hoặc `Whitelist:KickWithoutLease=true` (bước 14) |
| Bật `KickWithoutLease` rồi staff bị kick | Steam ID của họ chưa có trong `Whitelist:ExemptSteamIds` |
| Bật `KickWithoutLease` mà không ai bị kick | `Whitelist:Mode` không phải `rcon`, RCON lỗi (xem cảnh báo Discord), hoặc câu trả lời `playerlist` không có SteamID64 (log server in ra câu trả lời) |
| `AdminsSteamIDs`/`WhitelistIDs`/`VIPs` không có tác dụng | Đặt trong `TIGameSession` thay vì `TIGameStateBase` — bị bỏ qua âm thầm |
| Tick rate thất thường | Evrima nhạy với single-thread; đừng chạy server chung máy với client khi test đông |

---

## Nguồn

- [The Isle — How to Host a Dedicated Server](https://www.theisle.info/how-to/host-a-dedicated-server)
- [Steam Community — How to: Host a Dedicated Evrima Server](https://steamcommunity.com/sharedfiles/filedetails/?id=2952501611)
