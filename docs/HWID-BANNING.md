# Ban theo máy (HWID) trong IsleWarden

Tài liệu này trả lời câu hỏi "làm sao nhận biết HWID để cấm vĩnh viễn?" ở mức
**cơ chế chung**, áp dụng cho anti-cheat launcher của **server bạn**. Nó không
mổ xẻ cách một launcher cụ thể của server khác định danh máy, và **không** hướng
dẫn né/giả HWID — mục đích ở đây là để bạn *chặn* kẻ phá trên server của mình.

## 1. Vì sao cần HWID ban

Ban theo Steam ID dễ bị lách: kẻ phá tạo tài khoản Steam mới rồi vào lại. HWID
ban gắn lệnh cấm với **chiếc máy** thay vì chỉ tài khoản, nên account mới trên
cùng máy vẫn bị chặn. Đây là công cụ răn đe, không phải rào chắn tuyệt đối (mục 6).

## 2. Cơ chế nhận biết (tổng quát)

1. Launcher client thu một số **mã định danh ổn định** của máy.
2. Ghép lại rồi **băm SHA-256** thành một chuỗi `DeviceId`.
3. Gửi `DeviceId` cho server khi người chơi xin vào.
4. Server so `DeviceId` với **ban list**; nếu trùng thì từ chối phiên.

Điểm mấu chốt: server **chỉ cần lưu và so hash**, không cần lưu số serial thô của
người chơi.

## 3. Các nguồn định danh & đánh đổi

| Nguồn | Lấy từ | Độ ổn định | Ghi chú |
|-------|--------|-----------|---------|
| MachineGuid | Registry `SOFTWARE\Microsoft\Cryptography` | Cao (đổi khi cài lại Windows) | Không cần quyền admin |
| MAC card mạng | API mạng | Trung bình (đổi được) | Ưu tiên card vật lý |
| Serial ổ đĩa hệ thống | WMI `Win32_DiskDrive` | Cao | Nên có ở giai đoạn sau |
| Serial mainboard / BIOS | WMI `Win32_BaseBoard`, `Win32_BIOS` | Cao | Máy ảo thường rỗng |
| Serial CPU (ProcessorId) | WMI `Win32_Processor` | Cao | Không phân biệt máy trùng đời |

Nguyên tắc: **kết hợp nhiều nguồn** và **chấp nhận thiếu vài nguồn**. Càng nhiều
nguồn thì càng khó lách; nhưng nếu ghép cứng tất cả vào một hash thì chỉ cần đổi
một linh kiện là `DeviceId` đổi theo. Cách bền hơn là lưu từng thành phần (đã
hash) và tính "trùng" theo tỉ lệ khớp (fuzzy), để một thay đổi nhỏ không thoát ban
mà thay linh kiện lẻ cũng không tạo máy "mới" hoàn toàn.

## 4. IsleWarden làm thế nào

- **`DeviceFingerprintCollector`** (trong `IsleWarden.Core`) hiện thu
  `MachineGuid` + địa chỉ MAC rồi băm thành `DeviceId`. Mỗi thành phần có thể
  vắng mặt và được bỏ qua an toàn. Mở rộng thêm serial ổ đĩa/mainboard/BIOS qua
  WMI là bước tiếp theo để fingerprint bền hơn.
- **Mạnh hơn HWID thô — mô hình "device record"** (trong `Protocol/Messages.cs`):
  - Khi người chơi đăng nhập bằng **Steam + Discord**, server phát `DeviceId` + một
    `DeviceKey` bí mật; server **chỉ lưu hash** của key.
  - Lệnh cấm gắn với **bản ghi thiết bị + Steam ID + fingerprint phần cứng** cùng
    lúc. `SessionDecision.Banned` được trả khi bất kỳ dấu hiệu nào trùng ban list.
  - Nhiều tín hiệu kết hợp khó lách hơn nhiều so với chỉ một HWID đơn.

## 5. Riêng tư & minh bạch (bắt buộc)

- **Chỉ lưu hash**, không lưu serial thô của người chơi.
- **Thông báo trước**: người chơi phải biết launcher có thu fingerprint máy; lưu
  lại `disclosureVersion` họ đã đồng ý.
- Thu **tối thiểu**, nêu **thời gian lưu**, có **kênh khiếu nại** (ví dụ ticket Discord).
- Tuân thủ luật dữ liệu cá nhân áp dụng cho bạn.

## 6. Giới hạn (nói thẳng)

- HWID user-mode **lách được**: đổi MAC, cài lại Windows, dùng máy ảo, hoặc dùng
  spoofer. HWID ban **tăng chi phí** né ban chứ không tuyệt đối.
- Muốn mạnh hơn thì kết hợp nhiều nguồn định danh **và** EasyAntiCheat (EAC có ban
  ở tầng thấp hơn user-mode).
- Coi chừng **báo nhầm**: máy net công cộng hay anh em dùng chung một máy sẽ trùng
  fingerprint. Đừng ban quá rộng — nên cấm theo tổ hợp (fingerprint + nhiều tài
  khoản vi phạm) hoặc để admin xét duyệt (`DeviceStatus.Pending`) thay vì tự động
  cấm cứng theo mỗi HWID.
