# Muse ai tool (v1.0)

## Luồng Muse hiện tại

### Cấp phép theo mã máy qua Firebase

- `firebase_config.json` dùng `databaseURL`: `https://muse-ai-617ac-default-rtdb.firebaseio.com`; có thể đặt biến môi trường `MUSE_FIREBASE_DATABASE_URL` thay thế. Không cần khóa Admin SDK.
- Quản lý tài khoản → Mã máy → Copy mã máy. Mã được băm từ Windows MachineGuid, không cho sửa trong giao diện; cài lại Windows có thể làm thay đổi mã. Không gửi GUID gốc hay cookie Muse lên Firebase.
- Mã có dạng `MUSE-XXXX-XXXX-XXXX-XXXX`, bố trí giống Dola Render Gateway. Realtime Database lưu ở `licenses/{mã máy}` với trường **string** `status`: `free` = 3 tài khoản, `10` = 10, `50` = 50, `active` = không giới hạn.
- Nếu chưa có license, lần thêm tài khoản đầu tiên đọc Firebase rồi tạo license `free`. Tạo có điều kiện `If-Match: null_etag` để không ghi đè license quản trị viên đã tạo/cập nhật. Lần thêm sau chỉ GET license; không PUT/PATCH lại status. Tool không tự nâng gói.
- File `database.rules.json` là mẫu cho database cấp phép này. Cần tự publish trong Firebase Console → Realtime Database → Rules; file này chưa tự được triển khai. Rules cho đọc từng license và chỉ tạo mới với `free`; chặn sửa/xóa license từ tool. Ai biết mã máy và URL có thể đọc license, nên không lưu cookie hay thông tin riêng tư ở nhánh này.
- Chỉ POST thêm tài khoản mới đọc Firebase một lần. Mở tool, mở popup tài khoản, chạy video và kiểm tra sức khỏe không gọi Firebase. Tài khoản tắt/Offline vẫn tính vào số đã lưu.
- Status lạ, lỗi quyền, lỗi tạo license hoặc mất mạng sẽ chặn thêm tài khoản; các tài khoản đã lưu vẫn hoạt động. Không có fallback tự cấp `free` khi lỗi.
- Giới hạn số tài khoản độc lập với số prompt chạy đồng thời. Trình tự kiểm tra và thêm được khóa để tránh nhiều yêu cầu thêm đồng thời vượt hạn mức.
- Bản `.exe` cần đóng gói lại bằng `build.bat` sau khi sửa mã. Có thể đặt `firebase_config.json` bên cạnh `.exe` để thay thế cấu hình được đóng gói.

### Tạo video

- Mỗi prompt dùng một tab và một thread riêng; các prompt trong batch được chia đều cho tài khoản Online đang bật. Dispatcher tuân theo số luồng và slot tài khoản.
- Sau khi nạp cookie, click `button[data-testid="hatch-chat-compose"]`. Nếu không tìm thấy nút, mở trực tiếp `https://muse.ai/thread/new`. Chỉ nhập prompt khi trang chat mới sẵn sàng.
- Sau khi gửi, lưu ID từ URL `https://muse.ai/thread/{id}`, tab và tài khoản vào job. Giao diện hiển thị link thread để đối chiếu.
- Không giới hạn thời gian tạo video. Theo dõi câu trả lời qua DOM: có nội dung trả lời, hết dấu hiệu đang xử lý và nội dung ổn định qua ba lần đọc. Câu trả lời hoàn tất không có video sẽ thất bại.
- Mất kết nối CDP tạm thời: kết nối lại cùng tab, không gửi lại prompt. Khởi động lại server hoặc bấm chạy lại sẽ tiếp tục thread đã lưu. Nếu đã gửi nhưng không còn tab và chưa lưu được ID, báo lỗi để tránh gửi trùng.
- Chỉ hoàn thành sau khi tải video, xác thực bằng `ffprobe`, lấy thumbnail từ Muse hoặc trích frame thật bằng `ffmpeg`. Cần cài Chrome, FFmpeg và cho phép chạy các chương trình này.
- Nút dừng ngừng theo dõi tại tool; không đảm bảo hủy tác vụ đang chạy trên máy chủ Muse.
- Các trường `maxRetries` / `timeoutMinutes` cũ được giữ để đọc dữ liệu và tương thích API; không tự retry hoặc hết hạn job đang chờ Muse. Các mô tả retry/timeout/reallocate và dán tự chạy trong đặc tả cũ bên dưới không còn áp dụng.
- Ảnh chung batch và ảnh từ `@tag` được đính kèm qua file input của Muse trước khi gửi prompt. Driver chờ ảnh preview hoặc thẻ tệp sẵn sàng; thiếu ảnh hoặc không tìm thấy input sẽ báo lỗi, không gửi prompt thiếu ảnh. Bước đính kèm mới đã kiểm thử giả lập CDP, chưa xác minh trên Muse thực tế.

> **Đặc tả sản phẩm chi tiết cho tool tạo video AI hàng loạt**: Xếp hàng loạt prompt, tham chiếu nhân vật bằng `@tag`, chạy đa luồng qua nhiều tài khoản và theo dõi trực tiếp — kèm module Flow Studio kéo-thả image-to-video.

---

## 🌟 Tính Năng Chính Theo Đặc Tả

### 1. Account Pool — Quản lý nhiều tài khoản (Mục 2)
* Quản lý nhiều tài khoản đăng nhập trong một pool dùng chung cho toàn bộ hàng đợi.
* Hỗ trợ bật/tắt (enabled), kiểm tra sức khỏe phiên (health check), tự động chuyển Offline khi phiên hết hạn.
* **Bảo mật tuyệt đối (Mục 2.5 & AC-12):** Thông tin đăng nhập/token được mã hóa khi lưu trữ (*encrypted at rest*), khóa mã hóa lưu độc lập, không bao giờ hiển thị lại plaintext trên UI hay trong log; hiển thị định danh đã che (ví dụ: `us***1@muse.ai`).
* **Tự động phục hồi & Reallocate (AC-08):** Khi một tài khoản bị tắt hoặc rớt mạng giữa chừng, job đang chạy trên tài khoản đó **không bị mất**, tự động quay về trạng thái "Chờ" để Dispatcher gán sang tài khoản Online khác.

### 2. Kho Ảnh Tham Chiếu (Reference Library) (Mục 3)
* Panel cố định ở header, luôn hiển thị ở mọi tab kèm số lượng ảnh và hướng dẫn gõ `@`.
* Nút **+ Thêm ảnh tham chiếu** nổi bật, hỗ trợ chọn nhiều file cùng lúc (PNG, JPG, WebP; tối đa 8 MB/file).
* Tự động sinh tag từ tên file (`[a-z0-9-_]`), cho phép chỉnh sửa tag trước khi lưu, kiểm tra trùng lặp.
* Tag là duy nhất trong toàn kho và dùng chung cho mọi prompt, batch và Flow Studio.

### 3. Soạn Batch Prompt & Cơ Chế @mention (Mục 4)
* Ô textarea lớn có 3 chế độ tách prompt: *Mỗi dòng = 1 video (mặc định)*, *Mỗi đoạn = 1 video*, *Toàn bộ = 1 video*.
* **Badge đếm prompt trực tiếp (AC-01):** Phản hồi tức thì (~200ms debounce) khi gõ, dán hoặc đổi chế độ tách.
* **Gõ `@` gợi ý ảnh (AC-02):** Dropdown hiển thị thumbnail + tag, chọn bằng phím mũi tên hoặc chuột.
* **Cảnh báo tag lạ (AC-03):** Gõ `@khongco` chưa có trong kho sẽ hiển thị cảnh báo đỏ ngay lập tức, ngăn chặn việc chạy thiếu ảnh tham chiếu.
* **Toggle "Dán là chạy luôn" (AC-05):** Mặc định BẬT; khi dán danh sách prompt, hệ thống tự thêm vào hàng đợi sau ~2s kèm toast thông báo và nút **Hoàn tác** trong vài giây.

### 4. Chạy Hàng Đợi & Dispatcher (Mục 5)
* Dispatcher là thành phần duy nhất gán job (FIFO), chạy cuốn chiếu liên tục cho tới khi hết hàng đợi.
* Số luồng hiệu dụng = `min(số luồng cấu hình, tổng slot trống của các tài khoản Online)`.
* Tự động **retry tối đa N lần** (mặc định N=2) khi gặp lỗi nền tảng trước khi đánh dấu "Thất bại" kèm mã lỗi chi tiết (AC-09).
* Tự động phát hiện **job treo** quá X phút (mặc định 15 phút) để thu hồi và gán lại.

### 5. Danh Sách Video & Dải Trực Tiếp (Mục 6)
* **Dải "Đang chạy trực tiếp" (Mục 6.4 & AC-06):** Ghim phía trên danh sách, hiển thị đồng thời mọi video đang chạy kèm thanh tiến độ %, % hoàn thành và đồng hồ đếm giây nhảy từng giây; cập nhật mỗi 2 giây.
* **Bố cục 1 dòng gọn gàng (Mục 6.3 & AC-10):** Thumbnail, prompt rút gọn, Task ID, thời lượng/tỉ lệ, badge trạng thái, nút Tải MP4 và nút xóa. Bấm vào dòng để mở rộng xem full prompt, ảnh tham chiếu và chi tiết lỗi.
* **Xem trước rồi mới tải (Mục 6.5 & AC-07):** Bấm thumbnail phát video trực tiếp bằng player nhúng ngay trên dòng, xem ưng ý mới bấm tải MP4.
* Tabs lọc trạng thái (Tất cả / Chờ / Đang chạy / Hoàn thành / Thất bại / Đã dừng) kèm bộ đếm live, tìm kiếm theo prompt/Task ID, phân trang 10/20/50, nút "Dọn mục đã xong".

### 6. Flow Studio — Canvas Kéo-Thả Image-to-Video (Mục 7 & AC-11)
* Tab thứ 2 với bề mặt canvas nền chấm (*dot grid*), các thẻ video nổi kéo-thả tự do bằng header.
* Thanh zoom ở góc dưới (`-`, `+`, `% zoom`, "Vừa khung", Ctrl + chuột lăn).
* Nút **+ Thêm ảnh** tạo thẻ mới từ kho hoặc file tải lên; mỗi thẻ có prompt riêng hỗ trợ `@tag`.
* Nút **▶ Tạo tất cả** đẩy toàn bộ thẻ chưa tạo vào cùng cơ chế Dispatcher dùng chung Account Pool và hàng đợi.
* Khi hoàn thành, thẻ hiển thị player nhúng phát video ngay trên thẻ kèm nhãn "Video đã tạo", badge chất lượng HD và nút tải về.
* Chuyển tab giữa "Hàng đợi" và "Studio kéo thả" **không làm mất dữ liệu** hay trạng thái đang chạy.

---

## 🚀 Hướng Dẫn Khởi Chạy

### 1. Khởi động 1-Click trên Windows
Nhấp đúp chuột vào file:
👉 **[`start.bat`](start.bat)**

Trình duyệt sẽ tự động mở giao diện tại: **`http://127.0.0.1:18610`**

### 2. Chạy bằng dòng lệnh
```bash
python app.py
```

### 3. Chạy toàn bộ Suite kiểm thử Tiêu chí nghiệm thu (AC-01 -> AC-12)
```bash
python -m unittest tests/test_acceptance_criteria.py
```
*(Kết quả 100% tests đạt chuẩn theo Mục 10).*
