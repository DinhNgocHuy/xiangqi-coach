# Live Xiangqi Screen Coach

Ứng dụng desktop huấn luyện tính toán cờ Tướng. Người dùng tự chia sẻ cửa sổ bàn cờ (Ziga.vn), ứng dụng hỗ trợ luyện tập.
Đây là công cụ huấn luyện, **không phải bot chơi cờ**: không tự thao tác trên Ziga, không chạy ẩn.

Trạng thái: **Giai đoạn 1** — Dashboard, Screen Monitor, chia sẻ màn hình chủ động, chụp & hiển thị một khung hình.
Kiến trúc và lộ trình: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Cài đặt trên Windows 10/11

1. **Microsoft C++ Build Tools** — cài [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/), chọn workload *Desktop development with C++*.
2. **WebView2 Runtime** — có sẵn trên Windows 11 và Windows 10 bản mới. Nếu thiếu: tải *Evergreen Bootstrapper* tại https://developer.microsoft.com/microsoft-edge/webview2/.
3. **Rust** — cài từ https://rustup.rs (toolchain mặc định `stable-x86_64-pc-windows-msvc`). Kiểm tra: `rustc --version`.
4. **Node.js 22 LTS** — https://nodejs.org. Kiểm tra: `node -v` (≥ 20.19).

> Nếu mã nguồn đang nằm trong WSL, hãy sao chép thư mục dự án sang ổ Windows (ví dụ `C:\dev\xianqi`) và chạy các lệnh dưới đây trong PowerShell.
> Bản build Linux/WSL dùng WebKitGTK, không hỗ trợ chia sẻ màn hình.

## Chạy

```powershell
cd desktop
npm install
npm run tauri dev       # mở ứng dụng ở chế độ phát triển (lần đầu biên dịch Rust mất vài phút)
```

Các lệnh khác:

```powershell
npm test                # unit test (Vitest)
npm run build           # kiểm tra kiểu TypeScript + build frontend
npm run tauri build     # tạo bộ cài .msi / .exe (NSIS) trong desktop\src-tauri\target\release\bundle\
```

## Backend (dev)

Python 3.12, chỉ lắng nghe `127.0.0.1` (mặc định cổng 8765). Hiện có `GET /health`, SQLite + migration, bộ luật cờ (`app/services/rules/xiangqi.py`) và API engine Pikafish (`/engine/*`); giao diện desktop gọi tất cả các API này qua `desktop/src/services/backend.ts`.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'      # Windows: .venv\Scripts\pip install -e ".[dev]"
.venv/bin/python -m app                # chạy server: http://127.0.0.1:8765/health
.venv/bin/pytest -q                    # toàn bộ test (perft độ sâu 3 mất ~5 s)
.venv/bin/pytest -q -m "not slow"      # bỏ test chậm
```

Cấu hình qua biến môi trường tiền tố `XQC_` (xem `backend/.env.example`): `XQC_PORT`, `XQC_DB_PATH` (mặc định `%APPDATA%\XiangqiCoach\coach.db` trên Windows, `~/.local/share/xiangqi-coach/coach.db` trên Linux), `XQC_PIKAFISH_PATH`, `XQC_LLM_PROVIDER`, `XQC_LLM_API_KEY`, `XQC_LLM_MODEL`, `XQC_HF_TOKEN`, `XQC_HF_MODEL`, `XQC_LOG_LEVEL`.

### Pikafish (engine, GĐ4)

```bash
cd backend
.venv/bin/pip install -e '.[dev,engine-setup]'
.venv/bin/python scripts/fetch_pikafish.py   # tải bản chính thức mới nhất vào engine/pikafish/ (~54 MB)
.venv/bin/pytest -q -m engine                # test với engine thật (tự bỏ qua nếu chưa tải)
```

Script kiểm tra kích thước và SHA-256 rồi chép `pikafish[.exe]`, `pikafish.nnue`, `Copying.txt` (giấy phép GPL-3.0), `NNUE-License.md` và `SOURCE.txt` (phiên bản + link mã nguồn). Thư mục `engine/pikafish/` không được commit. Dùng binary khác: `XQC_PIKAFISH_PATH`. Giới hạn tài nguyên: `XQC_ENGINE_THREADS` (mặc định min(2, số CPU)), `XQC_ENGINE_HASH_MB` (128), `XQC_ENGINE_MAX_DEPTH` (30), `XQC_ENGINE_MAX_MOVETIME_MS` (10000). Chưa có engine thì backend vẫn chạy, các API `/engine/*` trả 503.

API: `GET /engine/status`, `POST /engine/analyze`, `POST /engine/evaluate-move` (xem `docs/ARCHITECTURE.md` §6).

**Nghĩa vụ GPL-3.0 khi phân phối Pikafish:** chạy Pikafish như tiến trình riêng (UCI), kèm `Copying.txt`, `NNUE-License.md` và link mã nguồn đúng phiên bản (`SOURCE.txt`) trong bộ cài.

**Giấy phép:** backend dùng [pyffish](https://github.com/fairy-stockfish/Fairy-Stockfish) (Fairy-Stockfish, GPL-3.0) để sinh nước đi hợp lệ, và sẽ dùng Pikafish (GPL-3.0) ở GĐ4, nên bản backend được phân phối phải tuân theo GPL-3.0.

### AI Thinking Coach (GĐ5, tùy chọn)

Coach dùng LLM để diễn giải kết quả Move Review bằng lời. Hai nhà cung cấp: **Anthropic** (Claude) hoặc **Hugging Face Inference Providers** (model mở như Qwen, Llama qua API đám mây). Không bắt buộc: không có key/token thì ứng dụng vẫn dùng nhận xét theo quy tắc. Chọn bằng `XQC_LLM_PROVIDER` = `anthropic` | `huggingface` | `none`; để trống thì tự chọn: Anthropic nếu có `XQC_LLM_API_KEY`, không thì Hugging Face nếu có `XQC_HF_TOKEN`, không thì tắt.

Anthropic:

```powershell
$env:XQC_LLM_API_KEY = "<key của bạn>"   # bash: export XQC_LLM_API_KEY=...
$env:XQC_LLM_MODEL = "claude-opus-5-5"   # tùy chọn, đây là mặc định
.venv\Scripts\python -m app
```

Hugging Face Inference Providers:

1. Vào [Settings → Access Tokens](https://huggingface.co/settings/tokens/new?ownUserPermissions=inference.serverless.write&tokenType=fineGrained), tạo token loại **fine-grained** có quyền **"Make calls to Inference Providers"** (theo [tài liệu](https://huggingface.co/docs/inference-providers/index#authentication)).
2. Đặt biến môi trường rồi chạy backend:

```powershell
$env:XQC_HF_TOKEN = "hf_..."                                    # bash: export XQC_HF_TOKEN=...
$env:XQC_HF_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"         # tùy chọn, đây là mặc định
.venv\Scripts\python -m app
```

`XQC_HF_MODEL` nhận mọi model chat có trên [danh sách Inference Providers](https://huggingface.co/models?inference_provider=all), có thể thêm hậu tố `:fastest` (nhanh nhất), `:cheapest` (rẻ nhất) hoặc `:<tên nhà cung cấp>` (chỉ nhà cung cấp đó). **Chi phí** ([Pricing](https://huggingface.co/docs/inference-providers/pricing)): tính theo giá của nhà cung cấp, không cộng thêm phí; tài khoản PRO và tổ chức Team/Enterprise có $2.00 credits/tháng (mỗi seat), tài khoản miễn phí **không** có credits hằng tháng mà phải mua credits trước. Hết credits → API trả 402, coach báo "Đã hết hạn mức Hugging Face" và giữ nhận xét theo quy tắc. Model mở nhỏ dễ bịa nước đi hơn; bộ lọc bên dưới vẫn áp dụng y nguyên.

Không ghi key/token vào file được commit. Dữ liệu gửi cho LLM (cả hai nhà cung cấp) **chỉ là văn bản**: FEN, nước đi, điểm engine, điểm/nhận xét theo quy tắc và câu trả lời tự đánh giá của bạn — **không gửi ảnh**. Mặc định không gửi nước tốt nhất/biến của engine. Mọi câu trả lời của LLM đi qua bộ lọc: câu nhắc nước đi không có trong dữ liệu hoặc biến sai luật bị loại. API: `GET /coach/status`, `POST /coach/move-feedback` (xem `docs/ARCHITECTURE.md` §7). Đã nối với Move Review (nút **Nhận xét AI Coach**); chưa thử với API thật.

## Đóng gói bộ cài Windows

CI (`.github/workflows/windows-build.yml`) làm toàn bộ việc này trên `windows-latest` và đưa `.exe` (NSIS) + `.msi` lên artifact. Làm tay trên Windows (PowerShell, từ thư mục gốc repo, đã cài Python 3.12, Node, Rust):

```powershell
python -m pip install -e "./backend[dev]" pyinstaller==6.22.3 py7zr
python backend/scripts/fetch_pikafish.py                                  # engine/pikafish/ (bản Pikafish cố định)
cd backend
python -m PyInstaller --noconfirm --distpath dist --workpath build packaging/xqc-backend.spec   # dist/xqc-backend/
python packaging/collect_licenses.py --out dist/licenses                  # giấy phép kèm bộ cài
cd ../desktop
npm ci
npx tauri build --config src-tauri/tauri.bundle.conf.json
```

`src-tauri/tauri.bundle.conf.json` chỉ dùng khi build bộ cài: nó thêm 3 thư mục resource `backend/` (backend đã đóng gói), `pikafish/` và `licenses/`. Nhờ vậy `npm run tauri dev` không cần các file này: khi không thấy backend đóng gói, app ghi log *dev mode* và bạn tự chạy backend (`python -m app`).

Bản cài tự chạy backend (cổng 8765, Pikafish đi kèm) và tắt nó khi đóng app (gửi tín hiệu qua stdin để backend tắt engine + đóng DB; quá 3 s thì kill). Chỉ chạy được một cửa sổ app: mở lần hai sẽ đưa cửa sổ cũ lên trước. Chi tiết: `docs/ARCHITECTURE.md` §11.

**Giấy phép (GPL-3.0):** bộ cài chứa Pikafish (GPL-3.0) và backend dùng pyffish (Fairy-Stockfish, GPL-3.0), nên bản phân phối theo GPL-3.0 (`LICENSE`). Thư mục cài đặt có `licenses/` (`LICENSE-GPL-3.0.txt`, `NOTICE.txt` với link mã nguồn ứng dụng và pyffish, `THIRD_PARTY_LICENSES.txt` cho mọi thư viện Python đi kèm: OpenCV, numpy, FastAPI, uvicorn, pydantic, anthropic…) và `pikafish/` (`Copying.txt`, `NNUE-License.md`, `SOURCE.txt` với link mã nguồn đúng phiên bản Pikafish).

## Sử dụng

Cần backend đang chạy (bộ cài tự chạy; khi dev: `cd backend && .venv/bin/python -m app`). Thanh bên hiện trạng thái **Backend / Pikafish / AI Coach** (kiểm tra mỗi 10 giây); "Backend chưa chạy" nghĩa là mọi chức năng dưới đây trừ chia sẻ màn hình và chế độ mẫu đều không dùng được. Địa chỉ backend mặc định `http://127.0.0.1:8765`, đổi khi dev bằng `VITE_BACKEND_URL`.

1. **Chia sẻ màn hình** — *Screen Monitor* → **Start Monitoring** → chọn cửa sổ trình duyệt đang mở Ziga.vn. **Chụp khung hình** vẫn chụp một ảnh tĩnh để xem.
2. **Hiệu chỉnh (một lần cho mỗi giao diện quân cờ)** — mở một ván ở **thế cờ ban đầu, đủ 32 quân**, bấm **Hiệu chỉnh (thế cờ ban đầu)**. Backend học hình quân cờ và lưu file hiệu chỉnh cạnh cơ sở dữ liệu.
3. **Tạo buổi tập** — khung *Buổi tập*: chọn thế cờ ban đầu hoặc FEN tùy chỉnh + bên đi trước, chọn bên bạn cầm quân (mặc định: bên ở phía dưới màn hình theo kết quả nhận diện) → **Tạo buổi tập**.
4. **Ghi nước đi**
   - **Theo dõi tự động**: cứ ~1,5 giây chụp một khung hình và nhận diện; chỉ gửi thế cờ khi nhận diện **đầy đủ** (không ô nào chưa chắc chắn) và **giống nhau 2 khung liên tiếp**. Kết quả: *Đã ghi nước đi*, *Thế cờ không đổi* hoặc *Không khớp* kèm lý do. Nếu backend thấy có vẻ đã đi 2 nước, nó chỉ **gợi ý** — bạn phải bấm **Xác nhận 2 nước** thì mới ghi.
   - **Thủ công**: **Nhận diện bàn cờ** → bàn cờ hiện ra, ô viền vàng là ô chưa chắc chắn; bấm ô để chọn quân/ô trống, rồi **Xác nhận thế cờ**.
   - **Hoàn tác nước cuối** khi ghi nhầm; **Kết thúc buổi tập** khi xong ván.
5. **Move Review** — danh sách nước **của bạn** chưa đánh giá. Chọn một nước → trả lời phần tự đánh giá (đều không bắt buộc) → **Gửi đánh giá** hoặc **Bỏ qua**. Chỉ sau bước này app mới hỏi Pikafish (`/engine/evaluate-move`), chấm điểm theo quy tắc và lưu nhận xét vào cơ sở dữ liệu. Điểm chiếu hết được hiển thị bằng chữ ("chiếu hết sau N nước"), không tính như centipawn.
6. **AI Coach (tùy chọn)** — dưới thẻ nhận xét, **Nhận xét AI Coach** gửi dữ liệu dạng văn bản cho LLM (cần `XQC_LLM_API_KEY` hoặc `XQC_HF_TOKEN`). Hiện rõ nguồn (AI kèm nhà cung cấp và model, hay theo luật) và số câu bị bộ lọc loại. Không có key → hiện lý do, nhận xét theo luật vẫn giữ nguyên.
7. **Nhật ký tư duy** — mẫu lỗi lặp lại theo kỹ năng, xu hướng theo tuần, danh sách lỗi gần đây.
8. **Luyện tập** — **Tạo bài tập từ lỗi của tôi** (cần Pikafish), chọn bài, trả lời bằng nước UCI (ví dụ `h2e2`) hoặc chọn đánh giá thế cờ; app hiện đúng/sai, giải thích và biến của engine.
9. **Dashboard** — thống kê (tổng buổi, điểm trung bình, lỗi thường gặp, theo tuần, kỹ năng cần cải thiện; hiện "Chưa đủ dữ liệu" khi chưa đủ mẫu), **Xuất dữ liệu (JSON)** và **Sao lưu** (hiện đường dẫn file sao lưu).

Không có buổi tập nào thì *Move Review* chạy **Chế độ mẫu** (3 nước viết tay, không qua Pikafish, không lưu).

Quyền riêng tư: khung hình chỉ nằm trong bộ nhớ và chỉ gửi tới backend trên chính máy này (127.0.0.1); backend xử lý ảnh trong bộ nhớ, không ghi đĩa. Lựa chọn bên cầm quân lưu trong `localStorage` của ứng dụng.

**Chưa kiểm chứng:** toàn bộ luồng giao diện này mới chạy được build/unit test và gọi thử API bằng script trên Linux; **chưa thử trên Windows/WebView2 và chưa thử với ảnh Ziga.vn thật** (độ chính xác nhận diện trên Ziga chưa biết).

## Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| “WebView hiện tại không hỗ trợ chia sẻ màn hình” | Cài/cập nhật WebView2 Runtime; đảm bảo đang chạy trên Windows, không phải WSL. |
| “Bạn đã hủy hoặc từ chối…” | Bấm Start Monitoring lại và chọn một nguồn. |
| Cửa sổ chia sẻ màu đen | Một số ứng dụng chặn chụp (DRM/tăng tốc phần cứng); thử chia sẻ cả màn hình hoặc tắt hardware acceleration của trình duyệt. |
| `Port 1420 is already in use` | Đóng tiến trình `npm run dev` / `tauri dev` cũ. |
