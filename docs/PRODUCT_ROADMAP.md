# Product Roadmap — Live Xiangqi Screen Coach

Cập nhật: 2026-11-27. Tài liệu này ghi **trạng thái thật** của mã nguồn. Một module chỉ được ghi "Hoàn thành" khi đã có code, test tự động và đã thử trên Windows.

Kiến trúc chi tiết: [ARCHITECTURE.md](ARCHITECTURE.md).

## 1. Kết quả audit (2026-11-27)

| Hạng mục | Hiện trạng |
|---|---|
| Mã nguồn | ~380 dòng TS/TSX + vỏ Rust tối thiểu (không có Tauri command). Chưa có backend Python. |
| Test | 31 unit test Vitest (4 cho `services/screenCapture.ts`, 27 cho `services/moveReview.ts`), pass. Chưa có test cho hook/UI, chưa có integration test. |
| Build/CI | `.github/workflows/windows-build.yml`: mỗi lần push chạy `npm ci` → `npm test` → `tauri build`, xuất `.exe`/`.msi`. Chưa chạy lần nào trên GitHub. Chưa ký số. Chưa commit `Cargo.lock`. |
| Lint | Chưa có ESLint/Prettier; chỉ dựa vào `tsc --strict` (chạy trong `npm run build`). |
| Bảo mật | CSP bật ở bản build. `connect-src` hiện chỉ cho `'self'` và IPC → **sẽ chặn** lời gọi tới backend `127.0.0.1` ở GĐ2, phải mở đúng một origin. Không có secret trong repo. |
| Dữ liệu | Khung hình chỉ ở bộ nhớ (object URL). Chưa có lưu trữ bền. |

### Đánh giá Screen Monitor (module 1)

Đã ổn: một `MediaStream` duy nhất ở cấp `App`; track được dừng khi Stop, khi thay stream, khi unmount; bắt sự kiện `ended` khi người dùng dừng từ thanh của Windows; giải phóng object URL; thông báo lỗi tiếng Việt cho các `DOMException` chính.

Còn thiếu cho mức sản phẩm:
- Chưa có test cho `useScreenCapture` (start/stop/ended/unmount) và `grabFrame`.
- Chưa có API lấy khung hình **không cần render** (GĐ2 cần chụp định kỳ để gửi backend, không phải chỉ khi bấm nút).
- Chưa thử thực tế trên Windows với Ziga.vn (Chrome/Edge, có/không hardware acceleration).

## 2. Trạng thái module

| # | Module | Trạng thái | Phụ thuộc |
|---|---|---|---|
| 1 | Screen Monitor | Chạy được; có chụp định kỳ (`grabFrameBlob`, theo dõi tự động 1,5 s). Thiếu test hook/UI, chưa thử trên Windows | WebView2 |
| 2 | Computer Vision | **Backend có, chỉ kiểm chứng trên ảnh tổng hợp.** `POST /vision/calibrate` (học theme từ ảnh thế cờ ban đầu) + `POST /vision/board` (ma trận, confidence từng ô, hướng, FEN xếp quân khi chắc chắn và hợp lệ). Trên ảnh tổng hợp đạt tiêu chí GĐ2 (xem ARCHITECTURE §9). **Độ chính xác trên Ziga thật: chưa biết** — cần bộ ảnh mẫu có nhãn. Frontend đã nối: Hiệu chỉnh, Nhận diện, Theo dõi tự động (ổn định 2 khung), Board Editor sửa ô chưa chắc chắn. Chưa đo trên Windows. | 1, backend Python, bộ ảnh mẫu Ziga có nhãn |
| 3 | Move Tracker | Backend xong phần lõi: `services/tracker.py` + API `/sessions/*` — từ thế cờ **đã xác nhận** ghi đúng 1 nước hợp lệ của bên tới lượt, không đổi → bỏ qua, còn lại báo không nhất quán kèm lý do (không có nước khớp, bên không tới lượt đi, nhiều ứng viên); 2 nước liên tiếp khớp duy nhất → chỉ **gợi ý**, người dùng phải nhập lại để ghi. Thế bắt đầu chuẩn hoặc FEN tùy chỉnh (kiểm tra), phát hiện hết cờ, hoàn tác nước cuối, lưu SQLite (migration 0002) và khôi phục sau khi khởi động lại. Pytest (service + API). Frontend đã nối: tạo/kết thúc buổi, chọn bên cầm quân (lưu `localStorage`, backend chưa có trường này), ghi tự động/qua Board Editor, xác nhận gợi ý 2 nước, hoàn tác, danh sách nước. **Chưa**: thử trên Windows, chưa nhận biết hòa (lặp lại/luật 60 nước, chiếu dai/đuổi dai), chưa có export ván (PGN/JSON theo buổi). | 2, bộ kiểm tra luật cờ |
| 4 | Pikafish | Backend xong phần lõi: script tải bản chính thức, 1 tiến trình UCI dài hạn, hàng đợi, timeout/stop, tự khởi động lại, MultiPV, cache SQLite, kiểm tra PV bằng bộ luật, `evaluate_move` + API `/engine/*`. Test với engine giả + engine thật (khai cuộc, chiếu hết 1 nước, nước hỏng quân) trên Linux. Frontend Move Review đã gọi `/engine/evaluate-move` (dùng `cp_loss`/điểm chiếu hết của backend). **Chưa**: thử trên Windows, tập vị trí kiểm thử còn nhỏ (3 thế), ngưỡng heuristic chưa hiệu chỉnh. | 3 (FEN hợp lệ), binary + NNUE, GPL-3.0 |
| 5 | AI Thinking Coach | Backend phần lõi: lớp trừu tượng LLM (SDK `anthropic` chính thức, structured outputs, fallback khi bị từ chối; Hugging Face Inference Providers qua router OpenAI-compatible với model mở, mặc định Qwen3-235B-A22B-Instruct-2507, chọn bằng `XQC_LLM_PROVIDER`; nhà cung cấp giả cho test), prompt tiếng Việt, bộ lọc đầu ra theo quy tắc (loại câu có nước ngoài dữ liệu, kiểm tra biến bằng bộ luật, giới hạn danh sách), fallback về nhận xét theo quy tắc khi không có key/lỗi/JSON hỏng, API `/coach/*`, test chỉ với nhà cung cấp giả. Frontend: nút **Nhận xét AI Coach** trong Move Review (hiện nguồn kèm nhà cung cấp/model, số câu bị lọc, lý do khi không khả dụng). **Chưa**: **chưa gọi thử API thật** với cả hai nhà cung cấp (chất lượng nhận xét chưa được đánh giá, model mở nhỏ có thể bịa nhiều hơn — bộ lọc là lưới an toàn), chưa thử trên Windows, chưa có cách nhập key trong giao diện (chỉ biến môi trường). | 4, 6, API key LLM hoặc token Hugging Face |
| 6 | Move Review | Nối backend: nước thật của người chơi trong buổi tập → tự đánh giá → Pikafish → nhận xét theo quy tắc → lưu SQLite; lịch sử từ backend. 3 nước mẫu chỉ còn là "Chế độ mẫu" khi chưa có buổi tập. Unit test logic + map engine/chiếu hết. Chưa thử UI trên Windows, chưa có test UI. | 3, 4, 7 |
| 7 | Thinking Journal | Backend xong phần lõi (`services/journal.py`, migration 0003): lưu MoveReview JSON (upsert theo nước, kiểm tra buổi/nước/nước đi), sinh lỗi tư duy cho phần đã trả lời có điểm < 1, `/journal/mistakes` (lọc, phân trang), `/journal/patterns` (tần suất, tỉ lệ, lặp lại ≥3/10 nước gần nhất, xu hướng theo tuần). Pytest. Frontend: trang **Nhật ký tư duy** (mẫu lỗi, xu hướng, lỗi gần đây). **Chưa**: chưa có dữ liệu thật để kiểm tra ngưỡng lặp lại/xu hướng. | 6, SQLite |
| 8 | Training Center | Backend xong phần lõi (`services/training.py`): 5 loại bài từ thế cờ thật của người chơi, lời giải từ Pikafish (độ sâu 12, MultiPV 5, chấp nhận ≤ 30 cp), mọi nước qua bộ luật, không có engine → không tạo bài; chấm bài (nước/lớp đánh giá), lưu lần làm. Test với engine giả + 1 test engine thật. Frontend: trang **Luyện tập** (tạo bài, làm bài, xem đáp án). **Chưa**: `tactical_awareness`, chưa hiệu chỉnh ngưỡng 30 cp/độ sâu, chỉ chấm nước đầu của biến. | 4, 7, bộ kiểm tra luật |
| 9 | Dashboard thống kê | Backend: `GET /stats/summary` (trung bình chỉ trên giá trị có thật, số nhận xét chưa đủ dữ liệu, lỗi phổ biến, chuỗi tuần/tháng, kỹ năng cần cải thiện khi ≥ 5 mẫu). Frontend Dashboard đã hiển thị (tổng, trung bình hoặc "Chưa đủ dữ liệu", lỗi phổ biến, theo tuần, kỹ năng cần cải thiện). Chưa thử trên Windows. | 7 |
| — | Bộ kiểm tra luật cờ (FEN, nước hợp lệ) | Xong: `services/rules/xiangqi.py`, adapter mỏng trên pyffish (FEN ↔ ma trận, kiểm tra thế cờ, nước hợp lệ, chiếu/hết cờ, perft có test). Chưa có luật hòa/chiếu dai. | — (dùng chung cho 2, 3, 4, 8) |
| — | Lưu trữ SQLite + migration + export/backup | Xong ở backend (`core/db.py` + API `GET /data/export`, `POST /data/backup`, có test). Dashboard có nút Xuất dữ liệu (JSON) và Sao lưu. **Chưa** có import; tải file qua Blob chưa thử trong WebView2. | backend |
| — | Đóng gói backend thành Tauri sidecar | Chưa bắt đầu | backend, CI |

## 3. Rủi ro kỹ thuật

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Nhận diện quân sai do theme/skin, độ phân giải, zoom trình duyệt, hiệu ứng động (quân đang di chuyển, highlight nước cuối) | Cao | Bộ ảnh mẫu thật có nhãn; chỉ nhận khung hình khi 2 khung liên tiếp giống nhau; confidence từng ô; Board Editor để sửa. |
| Chưa có ảnh mẫu Ziga.vn để làm dữ liệu kiểm thử | Cao | Cần người dùng cung cấp 30–100 ảnh chụp các thế cờ khác nhau (xem §5). |
| Đóng gói Python (OpenCV, FastAPI) bằng PyInstaller làm sidecar: file lớn (~100 MB), antivirus báo nhầm, CI phức tạp hơn | Trung bình | Build sidecar trong cùng workflow Windows; giữ dependency tối thiểu (`opencv-python-headless`, `numpy`, `fastapi`, `uvicorn`); ký số khi phát hành. |
| Pikafish GPL-3.0: phân phối binary kèm app phát sinh nghĩa vụ cung cấp mã nguồn và giấy phép | Trung bình | Chạy Pikafish như tiến trình riêng qua UCI; kèm `LICENSE` + link mã nguồn đúng phiên bản trong bộ cài; ghi rõ trong README. Cần kiểm tra pháp lý trước khi phát hành thương mại. |
| Điều khoản sử dụng của Ziga.vn về công cụ hỗ trợ khi đang chơi | Cao (sản phẩm) | Ứng dụng chỉ đọc màn hình do người dùng chia sẻ, không điều khiển Ziga; chế độ luyện tập ẩn đáp án engine tới khi người chơi tự đánh giá xong. Cần người dùng tự xác nhận phạm vi được phép. |
| LLM bịa nước đi/biến cờ | Trung bình | Mọi nước LLM nhắc tới phải có trong dữ liệu engine hoặc qua bộ kiểm tra luật, nếu không thì loại bỏ. |
| CSP chặn kết nối tới backend | Thấp | Mở đúng `http://127.0.0.1:<port>` và `ws://127.0.0.1:<port>` trong `connect-src`. |

## 4. Các giai đoạn và tiêu chí nghiệm thu

Không chuyển sang giai đoạn sau khi tiêu chí của giai đoạn hiện tại chưa đạt.

### GĐ1 — Nền tảng & chia sẻ màn hình (gần xong)
- [x] Dashboard, Screen Monitor, chia sẻ chủ động, chụp khung hình tĩnh.
- [x] Unit test cho service chia sẻ màn hình.
- [x] CI build bộ cài Windows (đã có workflow, **chưa có lần chạy xanh trên GitHub**).
- [ ] Test cho `useScreenCapture` và `grabFrame`.
- [ ] Thử thực tế trên Windows 10 và 11 với Ziga.vn; ghi kết quả vào README.

### GĐ2 — Computer Vision
- Backend FastAPI chỉ lắng nghe `127.0.0.1`, chạy được dưới dạng Tauri sidecar trong bản cài.
- `POST /vision/board` nhận 1 ảnh PNG, trả về: vị trí bàn cờ trong ảnh, ma trận 10×9, confidence từng ô, hướng bàn cờ (Đỏ dưới/trên), FEN (nếu hợp lệ), danh sách cảnh báo.
- Trên bộ ảnh kiểm thử có nhãn: ≥ 99,5% ô đúng; ≥ 95% thế cờ đúng toàn bộ; mọi ô sai phải có confidence < ngưỡng (tức là ứng dụng **báo không chắc**, không âm thầm sai).
- ≤ 300 ms/khung hình trên máy Windows tầm trung.
- Thế cờ vi phạm luật cơ bản (số quân, Tướng/Sĩ ngoài cung, Tượng qua sông, 2 Tướng đối mặt khi không tới lượt) bị đánh dấu không hợp lệ, không sinh FEN.
- Board Editor trong UI: sửa từng ô, xác nhận thế cờ; bản sửa được lưu làm dữ liệu nhãn (chỉ khi người dùng đồng ý).
- Pytest cho từng bước (lưới, giao điểm, phân loại quân, kiểm tra luật) + integration test trên bộ ảnh mẫu.

### GĐ3 — Move Tracker
- Từ 2 thế cờ đã xác nhận → đúng 1 nước hợp lệ hoặc báo "không xác định" (không đoán).
- Xác định lượt đi, phát hiện thế cờ không nhất quán (nhảy nhiều nước, nhận diện sai).
- Lưu lịch sử nước đi theo buổi tập (SQLite, có migration).

### GĐ4 — Pikafish
- Một tiến trình dài hạn, UCI, MultiPV, giới hạn thời gian/độ sâu/luồng/bộ nhớ, hàng đợi phân tích, khởi động lại khi engine chết.
- Kết quả có độ sâu và độ ổn định (so sánh đánh giá giữa các độ sâu); Move Quality ghi rõ khi phân tích chưa đủ sâu.
- Test với tập vị trí đã biết kết quả.
- Đáp ứng nghĩa vụ GPL-3.0 khi đóng gói.

### GĐ5 — AI Thinking Coach
- LLM API abstraction (đổi được nhà cung cấp), key qua `.env` / cấu hình người dùng, có `.env.example`.
- LLM chỉ diễn giải dữ liệu engine + phần tự đánh giá; bộ lọc loại mọi nước/biến không có trong dữ liệu engine.
- Chạy được khi không có LLM (dùng nhận xét theo quy tắc của Move Review).

### GĐ6 — Thinking Journal, Training Center, Dashboard
Trạng thái: các tiêu chí dưới đã có ở **backend** (xem ARCHITECTURE §10), frontend đã nối (trang Nhật ký tư duy, Luyện tập, Dashboard); GĐ6 chưa nghiệm thu vì chưa thử trên Windows với dữ liệu thật.
- Lưu lỗi tư duy, phát hiện lỗi lặp lại, thống kê theo tuần/tháng.
- Bài tập chỉ lấy từ thế cờ thật của người chơi đã qua bộ kiểm tra luật + engine.
- Export/backup dữ liệu (JSON/SQLite file).

## 5. Công việc ưu tiên (theo thứ tự)

1. Đẩy code lên GitHub và có **một lần CI xanh** (bộ cài cài được trên Windows thật).
2. Thử trang Move Review trên Windows (`npm run tauri dev`) — logic đã có test, giao diện chưa được thử tay.
3. **Người dùng cung cấp ảnh mẫu Ziga.vn**: 30–100 ảnh chụp cửa sổ ở các thế cờ khác nhau, cả 2 hướng bàn cờ, vài kích thước cửa sổ, có cả ảnh đang highlight nước vừa đi. Không có bộ ảnh này thì không thể nghiệm thu GĐ2.
4. Bộ kiểm tra luật cờ (Python, có test) — nền chung cho GĐ2–4 và Training Center.
5. Khung backend FastAPI + sidecar + CI (chỉ `/health`) trước khi viết thuật toán vision, để rủi ro đóng gói lộ ra sớm.
6. Thuật toán vision (xem §6).

## 6. Kế hoạch đề xuất Giai đoạn 2 — Computer Vision

### Thiết kế
```
Frontend (ScreenMonitor)                     Backend (FastAPI, 127.0.0.1, sidecar)
 grabFrame() mỗi ~1 s khi bật "Theo dõi" ──PNG──▶ POST /vision/board
                                                 1. locate_board   – tìm vùng bàn cờ (đường kẻ + Hough / contour)
                                                 2. grid           – tính 90 giao điểm từ 4 góc (perspective transform)
                                                 3. classify       – mỗi giao điểm: trống / quân (màu bằng HSV,
                                                                     loại quân bằng template matching theo theme)
                                                 4. orient         – Đỏ dưới hay trên (vị trí 2 Tướng)
                                                 5. validate       – bộ kiểm tra luật → FEN hoặc cảnh báo
 Board Editor  ◀──── ma trận + confidence ────
```
- **Template matching trước, mô hình học máy sau**: Ziga dùng một bộ hình quân cố định, nên mẫu ảnh 14 loại quân (cắt từ ảnh thật, chuẩn hóa kích thước) đủ cho bản đầu, không cần GPU hay dataset lớn. Chỉ chuyển sang mô hình ONNX nhỏ nếu bộ ảnh kiểm thử chứng minh template không đạt ≥ 99,5%.
- Chỉ gửi khung hình khi nội dung thay đổi và **ổn định qua 2 lần chụp** (tránh lúc quân đang chạy hiệu ứng).
- Ảnh không ghi xuống đĩa, trừ khi người dùng bật chế độ lưu dữ liệu nhãn.

### File dự kiến tạo
```
backend/
  pyproject.toml              fastapi, uvicorn, opencv-python-headless, numpy, pydantic; dev: pytest, httpx
  app/main.py                 FastAPI app, /health, CORS/origin chỉ cho app Tauri, log có cấu trúc
  app/api/vision.py           POST /vision/board
  app/schemas/board.py        BoardResult (matrix, confidence, orientation, fen, warnings)
  app/services/rules/         xiangqi.py — FEN parse/serialize, kiểm tra thế cờ hợp lệ (dùng lại ở GĐ3–4)
  app/services/vision/        locate.py, grid.py, classify.py, orient.py, templates/
  tests/                      test_rules.py, test_grid.py, test_classify.py, test_vision_api.py
  tests/fixtures/ziga/        ảnh mẫu + nhãn FEN (do người dùng cung cấp)
desktop/src/
  services/backend.ts         gọi /vision/board, timeout, lỗi tiếng Việt
  components/BoardEditor.tsx  hiển thị 10×9, tô ô confidence thấp, sửa & xác nhận
```

### File dự kiến sửa
- `desktop/src-tauri/tauri.conf.json`: `connect-src` thêm `http://127.0.0.1:<port>`; khai báo sidecar `externalBin`.
- `desktop/src-tauri/src/lib.rs` + `Cargo.toml`: khởi động/dừng sidecar cùng app (`tauri-plugin-shell`).
- `desktop/src/pages/ScreenMonitorPage.tsx`: thêm nút "Nhận diện bàn cờ" và Board Editor — không đổi logic chia sẻ hiện có.
- `.github/workflows/windows-build.yml`: cài Python, chạy `pytest`, build sidecar bằng PyInstaller trước `tauri build`.
- `README.md`, `docs/ARCHITECTURE.md`.

### Thứ tự thực hiện
1. Bộ kiểm tra luật + pytest.
2. Khung backend + sidecar + CI chạy xanh (chưa có vision).
3. `locate` + `grid` trên ảnh mẫu (test: 90 giao điểm lệch ≤ 1/4 khoảng cách ô).
4. `classify` + `orient` (test: độ chính xác trên bộ ảnh có nhãn).
5. API + Board Editor + integration test.
6. Thử thực tế trên Windows với Ziga.vn, đo độ chính xác và thời gian, ghi vào README.
