# Kiến trúc — Live Xiangqi Screen Coach

## 1. Phân tích tổng thể

Modular monolith gồm 3 tiến trình chạy cục bộ trên máy người dùng:

```
┌──────────────────────── Tauri app (Windows, WebView2) ────────────────────────┐
│ React UI                                                                      │
│  Screen Monitor ── getDisplayMedia (người dùng tự chọn nguồn) ── khung hình   │
│        │                                                                      │
│        │  (GĐ2+) gửi 1 khung hình PNG qua HTTP/WebSocket localhost            │
└────────┼──────────────────────────────────────────────────────────────────────┘
         ▼
┌──────────── Python backend (FastAPI, 127.0.0.1) ────────────┐
│ vision/   OpenCV: tìm lưới 9×10, nhận diện quân  (GĐ2)       │
│ board/    trạng thái bàn cờ + xác nhận của người dùng (GĐ2)  │
│ moves/    so sánh 2 trạng thái → nước đi, lượt đi  (GĐ3)     │
│ engine/   1 tiến trình Pikafish dài hạn, UCI, MultiPV (GĐ4)  │
│ coach/    LLM chỉ diễn giải dữ liệu engine đã có    (GĐ5)    │
│ training/ SQLite: buổi tập, lỗi tư duy, tiến bộ     (GĐ6)    │
└──────────────────────────────────────────────────────────────┘
```

Ranh giới quan trọng:

- **Chụp màn hình nằm ở frontend.** `getDisplayMedia` buộc người dùng chọn cửa sổ qua hộp thoại của hệ điều hành/WebView2 và hiển thị chỉ báo đang chia sẻ — đúng yêu cầu “người dùng chủ động”. Backend không bao giờ tự chụp màn hình.
- **Backend chỉ nhận từng khung hình rời rạc**, không nhận luồng video liên tục. Không ghi khung hình xuống đĩa trừ khi người dùng yêu cầu.
- **Backend chỉ lắng nghe 127.0.0.1.** Không có máy chủ từ xa; chỉ lời gọi LLM (GĐ5) đi ra ngoài và chỉ gửi văn bản (FEN, nước đi, điểm engine, câu trả lời tự đánh giá của người chơi), không gửi ảnh.
- **Chặn trang web gọi backend** (`app/main.py`): header `Host` phải là `127.0.0.1`/`localhost` (TrustedHostMiddleware, chống DNS rebinding; test thêm `testserver` qua `tests/conftest.py`, không có trong bản chạy thật). Mọi request POST/PUT/PATCH/DELETE phải có header **`X-XQC-Client: 1`**, thiếu → 403: trang web lạ không thể gửi header tùy chỉnh mà không qua CORS preflight (chỉ origin Tauri/Vite qua được), nên POST "đơn giản" từ trang khác bị chặn. **Frontend phải gửi header này cho mọi lời gọi ghi.** Body thường (JSON…) giới hạn 2 MB (413); multipart và `image/png` được bỏ qua ở middleware — ảnh vision (PNG thô) do chính `/vision/*` giới hạn 10 MB khi đọc (kiểm tra `Content-Length` rồi đếm từng chunk, không đệm quá giới hạn).
- **Một kết nối SQLite dùng chung** (threadpool + event loop): mọi ghi/transaction, backup, export giữ `db.db_lock` (RLock; `db.transaction(conn)` = lock + BEGIN IMMEDIATE/COMMIT/ROLLBACK). Code async không giữ lock trên event loop: phần DB chạy qua `asyncio.to_thread` (cache engine, Training Center).
- **Không có thao tác tự động lên Ziga.vn** (không click, không gửi phím). Ứng dụng chỉ đọc hình ảnh người dùng chia sẻ.
- **Pikafish là một tiến trình dài hạn** do backend quản lý (khởi động 1 lần, hàng đợi phân tích, giới hạn thời gian/luồng), không tạo mới cho mỗi request.
- **LLM không là nguồn sự thật về cờ.** Mọi nước đi/đánh giá đến từ Pikafish; LLM chỉ diễn giải và bị kiểm tra lại: câu nào nhắc nước đi không có trong dữ liệu đầu vào sẽ bị loại (§7).

## 2. Cấu trúc thư mục

Hiện có:

```
xianqi/
  README.md                 hướng dẫn cài đặt & chạy trên Windows
  docs/ARCHITECTURE.md
  desktop/                  Tauri 2 + React 19 + TypeScript + Tailwind 4
    src/
      components/           Sidebar (+ trạng thái backend), StatusBadge, SelfAssessmentForm, MoveReviewCard,
                            SessionPanel, TrackingPanel, BoardEditor, SessionReview, CoachPanel, Card
      pages/                Dashboard, ScreenMonitor, MoveReview, Journal (Nhật ký tư duy), Training (Luyện tập)
      hooks/                useScreenCapture (sở hữu MediaStream duy nhất), useSession (buổi tập hiện tại),
                            useBackendStatus (poll 10 s), useLoad (tải 1 tài nguyên API)
      services/             backend (client HTTP, header X-XQC-Client, timeout, lỗi tiếng Việt) + test
                            screenCapture (getDisplayMedia, grabFrame / grabFrameBlob) + test
                            moveReview (chấm điểm nước đi & tư duy theo luật, map kết quả Pikafish) + test
                            board (FEN xếp quân ⇄ ma trận, sửa ô) + autoMonitor (quyết định theo dõi tự động) + test
      data/                 sampleMoves — nước đi + số liệu engine MẪU, chỉ cho "Chế độ mẫu"
      types/                api.ts (kiểu dữ liệu API backend), moveReview.ts, capture.ts
    src-tauri/              vỏ Rust tối thiểu (không có command nào ở GĐ1)
```

Backend (desktop gọi qua `services/backend.ts`, xem §5):

```
  backend/
    pyproject.toml          fastapi, uvicorn, pydantic 2, numpy, opencv-python-headless, pyffish; dev: pytest, httpx
    .env.example            biến môi trường XQC_* (không có giá trị thật)
    app/__main__.py         `python -m app` → uvicorn trên 127.0.0.1:XQC_PORT
    app/main.py             create_app(settings): lifespan mở SQLite + migration, CORS chỉ cho origin Tauri + Vite dev
    app/api/                ROUTERS — GĐ sau thêm router vào đây; hiện chỉ có GET /health
    app/core/               config (env, dataclass), logging (JSON), db (sqlite3, migration, export_json, backup_to)
    app/migrations/         0001_init.sql: sessions, moves, move_reviews, thinking_mistakes, engine_cache
                            0002_session_start_fen.sql: sessions.start_fen (thế bắt đầu của Move Tracker)
                            0003_journal_training.sql: UNIQUE move_reviews(session_id, move_number), exercises, exercise_attempts
    app/services/rules/     xiangqi.py — FEN ↔ ma trận 10×9, kiểm tra thế cờ, nước hợp lệ/chiếu/hết cờ
                            (adapter mỏng trên pyffish, đổi tọa độ hàng 1–10 của pyffish ↔ 0–9 kiểu UCI Pikafish)
    app/services/vision/    GĐ2: locate, grid, classify, calibrate, orient, pipeline (xem §9); API app/api/vision.py
    tests/                  pytest: config, db, logging, rules (perft 44/1920/79666), /health
```

Sẽ thêm khi tới giai đoạn tương ứng:

```
  backend/app/{schemas,services/{vision,board,moves,engine,coach,training}}   GĐ2–6
  engine/pikafish/          binary + NNUE (không commit, tải theo hướng dẫn)  GĐ4
```

**Giấy phép:** backend phụ thuộc pyffish (Fairy-Stockfish, GPL-3.0) và sau này Pikafish (GPL-3.0) ⇒ bản backend phân phối kèm bộ cài là GPL-3.0. Thư viện `cchess` đã thử và bị loại (perft(2) = 1926, sai).

Khác với đề xuất ban đầu: bỏ `backend/app/services/screen/` (chụp màn hình thuộc frontend, xem trên) và `docker/` (ứng dụng desktop cục bộ, backend sẽ được đóng gói kèm app bằng PyInstaller làm Tauri sidecar thay vì Docker).

## 3. Phiên bản thư viện (đã kiểm tra cài đặt và build được)

| Thành phần | Phiên bản | Ghi chú |
|---|---|---|
| Node.js | ≥ 20.19 (đã thử 22.22) | yêu cầu của Vite 8 |
| Tauri CLI / crate | 2.12.x / 2.x | |
| React | 19.3 | |
| TypeScript | 6.0 | |
| Vite | 8.4 | |
| Tailwind CSS | 4.3 (`@tailwindcss/vite`) | không cần `tailwind.config.js` |
| Vitest | 5.1 | unit test |
| Rust | stable (MSVC) | chỉ cần trên máy build Windows |
| Python backend | 3.12 | đã thử: fastapi 0.165, uvicorn 0.54, pydantic 2.14, numpy 2.5, opencv-python-headless 5.1, pyffish 0.0.91, pytest 9.2 |

## 4. Quyết định kỹ thuật ở Giai đoạn 1

1. **`getDisplayMedia` thay vì API chụp màn hình native (Rust).** Có sẵn trong WebView2, có hộp thoại chọn nguồn và chỉ báo của hệ điều hành, người dùng dừng được bất kỳ lúc nào. Không cần quyền Tauri nào thêm. Hạn chế: WebKitGTK trên Linux không hỗ trợ — sản phẩm nhắm Windows nên chấp nhận.
2. **`frameRate ≤ 10`, không âm thanh.** Chỉ cần ảnh tĩnh; giảm tải CPU/GPU.
3. **Khung hình chỉ là object URL trong bộ nhớ**, bị giải phóng khi chụp khung mới, bấm Xóa hoặc rời trang. Không lưu đĩa.
4. **Một `MediaStream` duy nhất ở cấp `App`**, nên chuyển trang không làm mất phiên chia sẻ; track tự dừng khi Stop, khi stream bị thay hoặc khi app đóng. Khi người dùng dừng từ thanh chia sẻ của hệ điều hành, sự kiện `ended` đưa trạng thái về “Chưa chia sẻ”.
5. **Không dùng router** — 5 màn hình chuyển bằng state; thêm `react-router` khi cần deep link hoặc nhiều màn hình hơn.
6. **CSP bật cho bản build** (`default-src 'self'`, cho phép `blob:`/`mediastream:` cho ảnh & video). Tắt ở chế độ dev để Vite HMR hoạt động.
7. **Bỏ plugin `opener` và lệnh `greet` của template** — chưa dùng IPC nào.

## 5. Frontend ↔ backend

- **Client** (`services/backend.ts`): `BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? "http://127.0.0.1:8765"`. Mọi POST/PUT/PATCH/DELETE gửi `X-XQC-Client: 1`. Timeout bằng `AbortController` (15 s; 90 s cho Pikafish/LLM/tạo bài tập; 5 s cho các lệnh trạng thái). Lỗi thành `BackendError` (`status` = mã HTTP, `null` khi không kết nối/hết giờ) với thông báo tiếng Việt: lấy `detail` của FastAPI (chuỗi hoặc danh sách lỗi validate), không có thì theo mã HTTP; không kết nối được → "Backend chưa chạy…". Kiểu dữ liệu API ở `types/api.ts` (snake_case như backend).
- **Trạng thái** (`useBackendStatus`): poll `GET /health`, `/engine/status`, `/coach/status` mỗi 10 s, hiện ở thanh bên.
- **Buổi tập** (`useSession`, ở cấp `App` như MediaStream): id buổi hiện tại và **bên người chơi** lưu trong `localStorage` (backend chưa có trường `player_side`; ghi chú `ponytail:` trong code). Mặc định bên người chơi = bên ở dưới màn hình theo `orientation` của vision.
- **Nhận diện & theo dõi** (`TrackingPanel`): khung hình lấy bằng `grabFrameBlob` (PNG Blob, không tạo object URL) gửi thẳng làm body (`Content-Type: image/png`, không multipart) tới `/vision/calibrate` hoặc `/vision/board`. Theo dõi tự động: 1 khung / 1,5 s, bỏ qua nếu request trước chưa xong; `autoMonitor.observeFrame` chỉ cho gửi khi nhận diện **đầy đủ** (`low_confidence` rỗng, có `fen_placement`) và **giống nhau 2 khung liên tiếp**, và khác thế đã gửi lần trước; gửi lỗi → được gửi lại. Không kết nối được / chưa hiệu chỉnh (409) → tự tắt theo dõi. Gợi ý 2 nước của tracker chỉ được ghi khi người dùng bấm xác nhận (2 lần `POST /sessions/{id}/moves`).
- **Board Editor**: bàn 10×9, Đỏ luôn ở dưới, chữ Hán + tên tiếng Việt, ô chưa chắc chắn viền vàng; gửi `placement` (ma trận) tới `/sessions/{id}/positions`. Dùng lại ở chế độ chỉ xem cho Luyện tập.
- **Move Review**: có buổi tập → danh sách nước **của người chơi** chưa có nhận xét. Engine chỉ được gọi **sau** khi nộp/bỏ qua tự đánh giá: `POST /engine/evaluate-move` → `fromEvaluation` (giữ `cp_loss`, `eval_*_mate`) → `buildMoveReview` → `POST /sessions/{id}/reviews`. `moveQuality` dùng `cp_loss` của backend khi có (điểm chiếu hết đã được map ±30000 nên không được trừ thô), nhãn thêm "bỏ lỡ đường chiếu hết"/"đối thủ có đường chiếu hết"; điểm hiển thị dạng "chiếu hết sau N nước". Pikafish lỗi → nhận xét không có engine (ghi rõ). Lịch sử từ `GET /sessions/{id}/reviews`. Nút **Nhận xét AI Coach** → `POST /coach/move-feedback` (mặc định `reveal_engine=false`), hiện nguồn llm/rules và số câu bị bộ lọc loại; không khả dụng → hiện lý do, giữ nhận xét theo luật. Không có buổi tập → **Chế độ mẫu** (dữ liệu viết tay, chỉ trong bộ nhớ, có nhãn).
- **Nhật ký tư duy / Luyện tập / Dashboard**: `GET /journal/patterns`, `/journal/mistakes`; `POST /training/generate`, `GET /training/exercises`, `POST /training/exercises/{id}/attempt`; `GET /stats/summary` (giá trị `null` hiện "Chưa đủ dữ liệu"), `GET /data/export` (tải về qua Blob), `POST /data/backup` (hiện đường dẫn).
- **Rule-based Move Review** (không LLM): không tự sinh nước đi; mọi nước trong nhận xét đến từ dữ liệu engine hoặc câu trả lời của người chơi; nước của engine chỉ hiện trong mục "Xem phân tích engine". Điểm tư duy (5 phần có trọng số) tách khỏi điểm nước đi; thiếu phần nào thì phần đó và tổng là "Chưa đủ dữ liệu đánh giá". Ngưỡng centipawn còn tạm thời.
- **Chưa kiểm chứng:** chưa chạy giao diện trên Windows/WebView2 và chưa thử với ảnh Ziga thật; chưa có test UI/hook (chỉ test logic thuần và client).

## 6. Engine Pikafish (GĐ4)

Mã: `backend/app/services/engine/` (`uci.py` giao thức, `manager.py` tiến trình + hàng đợi + cache, `evaluate.py` đánh giá một nước), API `backend/app/api/engine.py`.

- **Lấy engine:** `backend/scripts/fetch_pikafish.py` tải bản phát hành **được ghim** (`PINNED_TAG = Pikafish-2026-09-06`, `Pikafish.2026-09-06.7z`, 53603424 byte, SHA-256 `41952bbf…25e5b` ghi trong script), sai/thiếu SHA-256 → dừng (cả với `--archive`); `--allow-unpinned` lấy bản mới nhất qua GitHub API và bắt buộc có digest SHA-256 của GitHub; tên file trong archive chứa `\` hoặc `..` bị loại, giải nén `.7z` (py7zr, extra `engine-setup`), chọn binary theo hệ điều hành (bản "universal" tự chọn tập lệnh CPU lúc chạy), chép `pikafish[.exe]`, `pikafish.nnue`, `Copying.txt` (GPL-3.0), `NNUE-License.md` và ghi `SOURCE.txt` (tag + link mã nguồn) vào `engine/pikafish/` (không commit). Đường dẫn khác: `XQC_PIKAFISH_PATH`.
- **Một tiến trình dài hạn** (asyncio subprocess), khởi động lười ở lần phân tích đầu: `uci` → `setoption Threads/Hash/EvalFile` → `isready`. Threads mặc định `min(2, số CPU)`, Hash 128 MB; độ sâu/movetime bị chặn bởi `XQC_ENGINE_MAX_DEPTH` (30) / `XQC_ENGINE_MAX_MOVETIME_MS` (10 s). Tắt sạch trong lifespan: `quit`, quá 2 s thì kill.
- **Hàng đợi:** `asyncio.Lock` — engine không bao giờ chạy 2 lệnh `go` cùng lúc. Mỗi request có timeout (`engine_timeout_s`, 30 s; movetime + 5 s) → gửi `stop`, trả kết quả dở dang (`timed_out`).
- **Tự phục hồi:** tiến trình chết, im lặng, bỏ qua `stop` hoặc request bị hủy giữa chừng → kill, khởi động lại (backoff 0 / 0,5 / 2 s), tối đa 3 lần; sau đó `EngineUnavailable` (HTTP 503, thông báo tiếng Việt). Thiếu binary → app vẫn chạy, `/engine/status` báo `available: false`.
- **Không truyền nước bịa:** mọi PV và `bestmove` đi qua `rules.validate_line`/`is_legal`; PV bị cắt ở nước sai đầu tiên kèm cảnh báo, kết quả có cảnh báo không được cache. Tọa độ Pikafish (hàng 0–9) trùng với UCI của chúng ta (đã kiểm tra: `b2e2` ở thế khai cuộc).
- **Cache:** bảng `engine_cache` theo (vị trí + bên đi, độ sâu, MultiPV); chỉ kết quả theo độ sâu, đủ sâu, không timeout. Khóa bỏ bộ đếm nước nên có thể lệch khi gần luật 60 nước.
- **Điểm số:** luôn theo bên tới lượt trong `AnalysisResult`; chiếu hết n nước → `±(30000 − n)` cp kèm trường `mate`.
- **`evaluate_move`** (khớp kiểu `EngineAnalysis` của frontend, thêm `cp_loss`, `eval_*_mate`, `depth`, `stable`, `notes`): phân tích trước (MultiPV 1) và sau (MultiPV 3) nước đi, quy về góc nhìn **người vừa đi**. Quy tắc (ghi trong docstring `evaluate.py`): `cp_loss` không trừ 2 điểm chiếu hết thô — cùng là thắng/thua bắt buộc thì 0, còn lại kẹp về ±2000 cp; `threats.check` = nước đáp tốt nhất của đối thủ chiếu; `capture` = 1 trong 3 nước đáp tốt nhất ăn quân; `counterattack` = đối thủ có chiếu hết bắt buộc hoặc mất ≥ 150 cp; `material_at_risk` = nước đáp tốt nhất ăn quân mà PV không cho thấy ăn lại quân giá trị ≥. `stable` = 3 độ sâu cuối cùng nước tốt nhất, chênh ≤ 30 cp; không đạt → ghi chú "Phân tích chưa đủ sâu"/"chưa ổn định".
- **API:** `GET /engine/status`, `POST /engine/analyze {fen, depth?, movetime_ms?, multipv?}`, `POST /engine/evaluate-move {fen_before, move, depth?}`; 400 khi FEN/nước sai, 503 khi không có engine.
- **GPL-3.0:** Pikafish chạy là tiến trình riêng qua UCI; khi đóng gói phải kèm `Copying.txt`, `NNUE-License.md` và `SOURCE.txt` (link mã nguồn đúng tag) cạnh binary.

## 7. AI Thinking Coach (GĐ5)

Mã: `backend/app/services/coach/` (`llm.py` nhà cung cấp LLM, `coach.py` prompt + bộ lọc), API `backend/app/api/coach.py`.

- **Vai trò:** chỉ diễn giải kết quả Move Review đã có (điểm nước đi, điểm tư duy 5 phần, điểm tốt, nguy cơ bỏ sót — chấm theo quy tắc ở frontend) cùng kết quả `evaluate_move`. LLM **không chấm lại** và không phân tích thế cờ.
- **Nhà cung cấp:** giao thức `LLMProvider.complete(system, user, max_tokens, schema)`; `AnthropicProvider` dùng SDK chính thức `anthropic` (`AsyncAnthropic`, xây trên `httpx2`), timeout 60 s, SDK tự thử lại 2 lần (lỗi kết nối, 429, 5xx). Model mặc định `claude-opus-5-5`, đổi bằng `XQC_LLM_MODEL`. Model này luôn bật thinking: **không** gửi `thinking` tắt/`budget_tokens`/`temperature` (lỗi 400); đặt rõ `output_config.effort = "medium"` (mức khởi điểm khuyến nghị, cần đo trước khi hạ), `max_tokens` 16000 để đủ chỗ cho thinking. Structured outputs (`output_config.format` JSON schema của phản hồi) nên JSON hỏng hiếm khi xảy ra. Fallback khi bị từ chối: `beta.messages.create(..., betas=["server-side-fallback-2026-07-01"], fallbacks="default")`; kiểm tra `stop_reason == "refusal"` trước khi đọc nội dung, chỉ đọc khối `text`. Lỗi được bắt theo thứ tự xác thực/quyền → 429 → `APIStatusError` (≥ 500 / khác) → timeout → kết nối, đổi thành `ProviderError` với lý do tiếng Việt. Key không bao giờ được ghi log (repr ẩn key); prompt chỉ ghi độ dài ở mức DEBUG.
- **`HuggingFaceProvider`** (Hugging Face Inference Providers): `POST https://router.huggingface.co/v1/chat/completions` (OpenAI-compatible), header `Authorization: Bearer <XQC_HF_TOKEN>`, gọi thẳng bằng `httpx2` (đã có sẵn qua `anthropic`; `huggingface_hub` sẽ thêm ~6 MB wheel gồm cả `hf_xet` native chỉ để gửi 1 POST). Model mặc định `Qwen/Qwen3-235B-A22B-Instruct-2507` (instruct, không thinking, đa ngôn ngữ), đổi bằng `XQC_HF_MODEL` (có thể thêm `:fastest`/`:cheapest`/`:<provider>`). Gửi `messages` system + user, `max_tokens`, `response_format = {type: "json_schema", json_schema: {name, schema, strict: true}}`; nếu nhà cung cấp trả 400/422 (model không hỗ trợ structured output) thì gửi lại 1 lần không có `response_format`, dựa vào prompt + parse/retry. `max_tokens` giới hạn 2048 (JSON ngắn, model mặc định không thinking). Timeout kết nối 10 s, mỗi POST tối đa 60 s (`asyncio.timeout`); không tự thử lại vì router đã tự chuyển sang nhà cung cấp khác khi lỗi. 400/422 trước khi gửi lại: ghi WARNING kèm `error.message` của nhà cung cấp (cắt 200 ký tự). Lỗi: 401/403 → token Hugging Face không hợp lệ/thiếu quyền Inference Providers, **402 → hết hạn mức Hugging Face**, 429 → giới hạn tần suất, ≥ 500 → quá tải, timeout, lỗi kết nối, còn lại "HTTP n". Nội dung `choices[0].message.content` (bỏ khối `<think>…</think>`, kể cả khối thiếu thẻ mở/đóng); body không đọc được → chuỗi rỗng, coach xử lý như JSON hỏng. Token ẩn trong repr và `Settings`.
- **Chọn nhà cung cấp** (`make_provider`): `XQC_LLM_PROVIDER` = `anthropic` | `huggingface` | `none`; để trống → Anthropic nếu có `XQC_LLM_API_KEY`, không thì Hugging Face nếu có `XQC_HF_TOKEN`, không thì tắt. Nhà cung cấp được chọn mà thiếu key → coach tắt.
- **Prompt (tiếng Việt):** chỉ giải thích từ dữ liệu; không bịa nước/biến; tách đánh giá engine khỏi đánh giá kỹ năng; tối đa 3 điểm cần cải thiện, luôn kèm lý do; trả JSON `{did_well[], missed[], why_it_matters, what_to_learn, next_exercise, questions[]}`. Mặc định `reveal_engine=false`: nước tốt nhất, nước đáp và PV của engine **không được gửi** cho LLM, prompt yêu cầu đặt câu hỏi gợi mở.
- **Bộ lọc đầu ra (tất định, lớp bảo vệ thứ hai):** JSON hỏng → gọi lại 1 lần, vẫn hỏng → fallback. Mọi chuỗi được tách câu; token dạng nước đi `[a-i]\d[a-i]\d` (không phân biệt hoa/thường, kể cả dính liền chữ) phải thuộc tập cho phép = nước của người chơi + nước đáp/biến người chơi tự dự đoán (+ nước engine nếu `reveal_engine`), nếu không cả câu bị bỏ (`guard.removed`). Chuỗi ≥ 2 nước liên tiếp (cách nhau bởi khoảng trắng, dấu phẩy, mũi tên) được coi là biến và phải hợp lệ theo `rules.validate_line` từ thế trước hoặc sau nước của người chơi, nếu không câu bị bỏ (`guard.illegal_variations`). Danh sách cắt còn 3 mục, chuỗi còn 600 ký tự (`guard.truncated`). Bộ lọc loại hết nội dung → fallback. Token tọa độ có thể viết tách (`h2-e2`, `h2 e2`, `h2→e2`, `h2xe2`) và được chuẩn hóa về `h2e2` trước khi so. Câu chứa ký hiệu truyền thống (`Pháo 2 bình 5`, `Mã 8 tiến 7`, `C2=5`, `C2.5`, `H8+7`, `R1-2`, `炮二平五`; tên quân có/không dấu hoặc chữ K/A/B/E/N/H/R/C/P + số cột + tiến/thoái/bình hoặc `. = + -` + số) không kiểm tra được nên bị bỏ (tính vào `guard.removed`); câu chỉ nhắc tên quân ("Xe của bạn") được giữ. Hạn chế: biến người chơi tự nhập mà sai luật cũng không được LLM trích dẫn.
- **Hạn chót chung:** cả pha gọi LLM của một lần `coach_move` (gọi lại khi JSON hỏng, gửi lại không `response_format`: tối đa 4 POST) nằm trong một `asyncio.timeout` 75 s (`COACH_DEADLINE_S`, dưới `SLOW_MS` 90 s của desktop), áp dụng cho mọi nhà cung cấp; quá hạn → lý do timeout. Client HTTP của nhà cung cấp được đóng khi backend tắt (lifespan).
- **Fallback:** không có key, lỗi nhà cung cấp, quá hạn chót hoặc lỗi bất ngờ của nhà cung cấp (chỉ ghi log loại lỗi) → `{source: "rules", available: false, reason}`; JSON hỏng/bị lọc hết → `{source: "rules", available: true, reason}`. Frontend giữ nhận xét theo quy tắc; không bao giờ giả câu trả lời LLM.
- **API:** `GET /coach/status` (không gọi mạng) → `{available, provider, model, reason}`; `POST /coach/move-feedback` nhận các trường `MoveReview` (`board_before`, `player_move`, `move_quality_*`, `thinking_*`, `strengths`, `missed_threats`, `self_assessment`, `engine`) + `reveal_engine` → `{source, available, reason, feedback, guard, model, provider}` (`source` vẫn là `"llm"` với mọi nhà cung cấp; `provider` = `anthropic` | `huggingface`); 400 khi FEN/nước sai (kiểm tra trước khi gọi LLM).

## 8. Move Tracker & buổi tập (GĐ3)

Mã: `backend/app/services/tracker.py`, schema `backend/app/schemas/session.py`, API `backend/app/api/sessions.py`.

- **Trạng thái chỉ nằm trong SQLite:** `sessions.start_fen` (migration 0002, FEN đầy đủ có bên đi) + bảng `moves`. Mỗi request dựng lại tracker từ DB (`tracker.load`), nên khởi động lại backend không mất buổi tập. `move_number` là số thứ tự nửa nước (ply), `side` là bên đã đi. Một `threading.Lock` tuần tự hóa đọc–ghi vì cả app dùng chung 1 kết nối sqlite.
- **Đầu vào là thế cờ đã được xác nhận** (ma trận 10×9 theo quy ước của bộ luật, hoặc trường xếp quân của FEN). So với thế hiện tại:
  - giống hệt → `unchanged`;
  - đúng 1 nước hợp lệ của bên tới lượt (`rules.find_move_between`) → `recorded`, lưu `fen_before`/`fen_after` (từ pyffish), đổi lượt;
  - còn lại → `inconsistent` + `reason`: nhiều ứng viên; khớp nước của bên **không** tới lượt; không nước nào khớp (kèm lỗi `validate_position` nếu có). Nếu đúng 1 chuỗi 2 nước khớp thì trả `suggestion: [m1, m2]` — **không tự ghi**, người dùng xác nhận bằng cách nhập 2 nước qua `POST /sessions/{id}/moves`. Tìm 2 nước được cắt tỉa: ô xuất phát của cả 2 nước luôn thay đổi và tối đa 4 ô đổi (không tỉa thì ~2000 lần gọi pyffish, vài giây).
- **Hết cờ:** sau mỗi nước dùng `rules.game_status`; `status` = `checkmate`/`stalemate` (bên tới lượt thua) chặn ghi thêm (409) nhưng vẫn cho hoàn tác. `ended` khi người dùng kết thúc buổi; khi đó mọi thay đổi bị chặn (409). Chưa có luật hòa (lặp lại, 60 nước) và chiếu/đuổi dai.
- **Thế bắt đầu:** mặc định thế khai cuộc; FEN tùy chỉnh phải có bên đi, qua `validate_position` + kiểm tra của pyffish, lỗi → 400.
- **API:** `POST /sessions {start_fen?, note?}` (201), `GET /sessions` (mới nhất trước), `GET /sessions/{id}` (kèm nước đi, FEN hiện tại, bên đi, trạng thái), `POST /sessions/{id}/positions {placement | fen_placement}` → `{result, move?, reason?, suggestion?, session}`, `POST /sessions/{id}/moves {uci}` (201, phải hợp lệ), `DELETE /sessions/{id}/moves/last` (trong cùng transaction xóa luôn nhận xét, lỗi tư duy, bài tập và lần làm bài của nước đó, để chúng không bị gán cho nước thay thế), `POST /sessions/{id}/end`. Lỗi: 404 không có buổi, 400 thế cờ/nước sai, 409 buổi đã kết thúc / ván đã hết / không có nước để hoàn tác.

## 9. Computer Vision (GĐ2)

Mã: `backend/app/services/vision/`, schema `backend/app/schemas/board.py`, API `backend/app/api/vision.py`.

> **Giới hạn quan trọng:** thuật toán mới chỉ được kiểm chứng trên **ảnh tổng hợp** do `backend/tests/vision_synth.py` vẽ bằng OpenCV (quân là đĩa tròn có chữ Latin, không phải chữ Hán; theme gỗ tự chế). **Độ chính xác trên ảnh Ziga thật chưa biết** cho tới khi có bộ ảnh mẫu có nhãn (roadmap §5 mục 3). Các ngưỡng bên dưới có thể phải chỉnh lại theo ảnh thật.

**Thuật toán** (mọi bước sau `locate` làm trên ảnh bàn cờ đã chuẩn hóa về 48 px/ô, nên theme không phụ thuộc kích thước cửa sổ):

1. `locate` — adaptive threshold tìm nét tối mảnh → mở hình thái học bằng kernel ngang/dọc 15 px (bỏ chữ, đĩa quân, đường chéo cung) → thành phần liên thông làm vùng ứng viên (nới 1/8 mỗi cạnh vì hàng cuối có thể bị quân che kín) → trong mỗi vùng tìm cấp số cộng 10 hàng / 9 cột khớp nhất với profile nét, tinh chỉnh bằng bình phương tối thiểu trên tâm từng đường → thử dịch lưới ±3 ô và chọn lưới có các đường được phủ tốt nhất *trong* khung, không kéo dài ra ngoài, và **đúng vị trí sông** (chỉ 2 đường dọc biên đi qua sông) — sông neo vị trí tuyệt đối, nên bàn cờ bị cắt mất hàng/cột đầu vẫn không bị lệch 1 ô. Không có ứng viên đạt → `BoardNotFoundError`. Ảnh chụp màn hình không bị méo phối cảnh nên lưới chỉ cần `x0, y0, dx, dy`.
2. `grid` — 90 giao điểm, kích thước ô, cắt + resize vùng bàn cờ về ảnh chuẩn.
3. `classify` — mỗi giao điểm:
   - *có quân hay trống*: gradient **hướng tâm** trên vòng tròn bán kính đĩa (48 góc, lấy phân vị 30%). Đường kẻ và đường chéo cung đi qua tâm nên gradient của chúng vuông góc với bán kính và gần như không tính; so sánh theo thang log giữa mức "trống" và "có quân" học được khi hiệu chỉnh;
   - *trống phải có bằng chứng*: mọi nhánh đường kẻ lẽ ra phải có tại điểm đó (không có nhánh ra ngoài ở biên, không có nhánh qua sông ở các cột trong) phải thấy nét tối ở đoạn 0,15–0,38 ô; bị hộp thoại/toast/con trỏ che → "không chắc", không bao giờ thành "trống";
   - *màu*: tỉ lệ điểm ảnh đỏ (HSV) trên tổng điểm "mực" (đỏ, hoặc tối hơn 0,6 × độ sáng trung vị của mặt quân — tương đối nên lớp tô màu trong suốt không làm mất mực) trong lòng quân; ít mực hơn một nửa mức tối thiểu lúc hiệu chỉnh (vòng đánh dấu, tô màu đậm) → độ tin cậy màu = 0;
   - *loại quân*: normalized cross-correlation (cho phép lệch ±2 px) với 7 mẫu cùng màu của theme.
   - *Confidence* mỗi ô = mức thấp nhất của 3 quyết định. Với loại quân, khoảng cách best − second được so với độ khác nhau giữa chính 2 mẫu đó (cặp mẫu càng giống thì càng cần ít chênh lệch, sàn 0,1) — hai quân trông gần giống nhau trong một theme không bị coi là luôn "không chắc".
4. `orient` — Tướng đỏ ở 3 hàng dưới (trong cung) → `red_bottom`, ở trên → `red_top`; quy về ma trận `board[rank][file]` (rank 0 = hàng cuối của Đỏ) như bộ luật. Không thấy Tướng nào → `orientation: null`, cảnh báo, không có FEN.
5. `pipeline.recognize` — điểm có cửa sổ nửa ô vượt ra ngoài ảnh → confidence 0 và cảnh báo `board is cut off by the image edge`; ô có confidence < 0,5 vào `low_confidence`; `fen_placement` (chỉ trường xếp quân của FEN — **không suy đoán bên đi**, `side_to_move: null`) chỉ có khi không có ô nào không chắc **và** `rules.validate_position` không báo lỗi; ngược lại `problems` ghi lý do. Không bao giờ âm thầm đoán.

**Hiệu chỉnh (`calibrate`)**: người dùng chụp 1 ảnh **thế cờ ban đầu**. Vì thế cờ đã biết, không cần gán nhãn tay: hướng bàn cờ suy ra từ màu (nửa nào có quân đỏ), bán kính đĩa = vòng tròn có gradient mạnh nhất trên 32 ô có quân, mẫu của mỗi loại quân = trung bình các quân trùng loại (5 Tốt, 2 Xe…). Kiểm tra: quân/ô trống và đỏ/đen phải tách được hoàn toàn, rồi nhận diện lại chính ảnh đó phải đúng cả 90 ô với confidence ≥ 0,5; sai → 422. Theme (phiên bản 2: 14 mẫu xám ~19×19 px + 6 số; file hỏng/sai định dạng/phiên bản cũ → 409, ghi theo kiểu file tạm + fsync + rename) lưu ở `vision_theme.npz` cạnh file SQLite trong thư mục dữ liệu người dùng; **không lưu ảnh chụp**. Đổi skin quân trên Ziga thì phải hiệu chỉnh lại.

**API (hợp đồng với frontend)**: `POST /vision/calibrate` và `POST /vision/board`, **body là byte PNG thô**, header `Content-Type: image/png` và `X-XQC-Client: 1` (không multipart). Body được đọc vào bộ nhớ với giới hạn cứng 10 MB: `Content-Length` > 10 MB → 413 ngay, body không có/nói sai `Content-Length` bị đếm khi stream và cắt ở 10 MB → 413; không bao giờ ghi ra đĩa. Kiểm tra chữ ký + header PNG, mỗi cạnh ≤ 8192 px và tổng ≤ 3840×2160×2 điểm ảnh *trước khi* giải mã (chống ảnh bom giải nén). Lỗi (tiếng Việt trong `detail`): 415 sai `Content-Type`; 413 ảnh quá lớn; 422 không phải PNG / hỏng / quá nhiều điểm ảnh / không tìm thấy bàn cờ / không hiệu chỉnh được; 409 chưa hiệu chỉnh hoặc file theme hỏng/không hợp lệ; 500 không ghi được file theme. `timing_ms` gồm giải mã + nhận diện (không gồm thời gian upload). Kết quả `/vision/board`: `board`, `confidence` (cùng chỉ số `[rank][file]`), `orientation`, `fen_placement`, `side_to_move` (luôn null), `low_confidence` (ví dụ `"e0"`), `problems`, `grid` (vị trí lưới trong ảnh), `timing_ms`.

**Kết quả trên ảnh tổng hợp** (`pytest tests/test_vision.py -s`, máy dev Linux/WSL2 6 lõi): lưới lệch tối đa 0,013 ô (yêu cầu ≤ 0,25); 32 thế cờ ngẫu nhiên hợp lệ (đi ngẫu nhiên từ khai cuộc qua bộ luật, 2 hướng, bàn rộng 400–900 px trong khung "trình duyệt" có rác UI, highlight, blur, JPEG) → 2880/2880 ô đúng, 32/32 thế cờ có `fen_placement`; thời gian median ~70–115 ms, max ~205 ms/khung (khung tới 1587×1267). Thử thêm ngoài pytest (8 seed × 40 thế cờ = 28 800 ô: 0 sai; bàn 320–400 px, blur 5×5 + JPEG chất lượng 30–55: 0 sai, vài ô bị báo không chắc). Các trường hợp bất lợi (đều có test): quân đang chạy hiệu ứng (bản sao lệch 0,45 ô), lớp tô vàng trong suốt **phủ lên** quân vừa đi, vòng đánh dấu cỡ quân và chấm nước đi trên điểm trống, hộp thoại đục che một phần bàn cờ, bàn cờ bị mép ảnh cắt (trên/dưới/trái/phải) → có ô sai nhưng **mọi ô sai đều bị báo không chắc** và không sinh FEN. Thử thêm ngoài pytest (15–30 khung mỗi loại): 0 ô sai không bị báo. Ngưỡng NCC 0,8–0,9 được chỉnh theo trường hợp quân đang chạy trên ảnh tổng hợp. Cái giá: lớp tô phủ lên quân vừa đi làm quân đó thường bị "không chắc" (chỉ ~1/3 khung đọc đủ) — nếu Ziga tô highlight lên trên quân, cần chỉnh lại trên ảnh thật.

**Chưa làm / rủi ro:** chưa thử ảnh Ziga thật (quân chữ Hán, hiệu ứng, bóng đổ, highlight thật); hướng bàn cờ dựa vào vị trí Tướng (không thấy Tướng → không có FEN); bàn cờ phải nằm ngang thẳng (không xoay); bước "ổn định qua 2 khung hình" và Board Editor nằm ở frontend (§5); chưa đo trên máy Windows tầm trung.

## 10. Thinking Journal, Training Center, Dashboard, export (GĐ6)

Mã: `backend/app/services/journal.py` (nhận xét, nhật ký lỗi, thống kê), `backend/app/services/training.py`, schema `backend/app/schemas/review.py`, API `backend/app/api/{journal,training,data}.py`, migration 0003. Frontend gọi các API này từ Move Review, Nhật ký tư duy, Luyện tập và Dashboard (§5).

- **Lưu nhận xét:** `POST /sessions/{id}/reviews` nhận đúng JSON `MoveReview` do `desktop/src/services/moveReview.ts` tạo. Kiểm tra trường bắt buộc (pydantic; 5 khóa `thinking_components` bắt buộc, giá trị `null` hoặc 0..1; điểm 0..100), `session_id` trong body = đường dẫn, buổi tập và nước `move_number` phải tồn tại (404), `player_move` phải trùng nước đã ghi (400). Trường giao diện khác được giữ nguyên trong `review_json`. Upsert theo (session_id, move_number), giữ `created_at` lần đầu (giờ máy chủ, UTC). `GET /sessions/{id}/reviews`.
- **Lỗi tư duy:** mỗi lần lưu, xóa rồi tạo lại `thinking_mistakes` của nước đó: 1 dòng cho mỗi phần **đã trả lời** có điểm < 1 (phần `null` không phải lỗi). Mô tả lấy câu tương ứng trong `missed_threats` (khớp theo cụm từ của moveReview.ts), không có thì dùng câu mặc định kèm điểm. `fen` = `fen_before` của nước đã ghi trong bảng `moves` (không tin `board_before` của client).
- **Nhật ký:** `GET /journal/mistakes?component&date_from&date_to&limit&offset` (ngày theo UTC, `date_to` tính cả ngày). `GET /journal/patterns` → mỗi phần: `count`, `share`, `last_seen`, `recurring` (sai ≥ 3 lần trong 10 nước được đánh giá gần nhất), `trend` (điểm trung bình theo tuần ISO, chỉ câu đã trả lời), `direction` (so 2 tuần gần nhất có dữ liệu: ≥ +0,1 improving, ≤ −0,1 worsening, còn lại flat; < 2 tuần → insufficient_data).
- **Training Center:** `POST /training/generate {limit?}` (mặc định 5, tối đa 20) duyệt lỗi theo phần sai nhiều nhất → gần nhất, bỏ qua bài đã có (UNIQUE session, nước, loại). Bài tập chỉ lấy từ thế cờ thật (`fen_before`/`fen_after` của nước có lỗi), phân tích Pikafish độ sâu 12, MultiPV 5:
  - `threat_detection` (threatAwareness): thế sau nước của người chơi, đáp án = nước đối thủ cách nước tốt nhất ≤ 30 cp **và** chiếu hoặc ăn quân; engine không thấy đe dọa thật → bỏ qua kèm lý do.
  - `response_prediction` (responsePrediction): thế sau nước của người chơi, đáp án = nước đối thủ cách nước tốt nhất ≤ 30 cp.
  - `variation_calculation` (variationCalculation): thế trước nước, đáp án = nước cách nước tốt nhất ≤ 30 cp (chỉ chấm nước đầu; PV hiện sau khi trả lời).
  - `position_evaluation` (positionEvaluation): thế sau nước, đáp án = better/equal/worse theo góc nhìn người chơi, ngưỡng ±50 cp như frontend.
  - `defensive_awareness` (pieceSafety): thế trước nước, đáp án = nước ≤ 30 cp không để mất quân theo quy tắc `material_at_risk` của `evaluate.py`.
  - Chưa làm `tactical_awareness`.
  Khi nước tốt nhất là chiếu hết: chỉ chấp nhận nước cũng chiếu hết cho cùng bên với khoảng cách lệch ≤ 1 (chiếu hết sau N → chấp nhận ≤ N+1; bị chiếu hết sau N → chấp nhận ≥ N−1); không bao giờ trừ điểm mate đã quy đổi như cp, giải thích ghi "chiếu hết sau N nước". Phân tích hết giờ hoặc có cảnh báo (nước engine sai luật) → không tạo bài (bỏ qua kèm lý do).
  Mọi nước đáp án qua `rules.is_legal`; lời đề không chứa đáp án; nước đã đi ở thế "trước nước" chỉ hiện sau khi trả lời. Không có engine → không tạo bài, trả `reason` (không bao giờ tự bịa lời giải). Độ sâu đạt được lưu ở `engine_depth`.
- **Làm bài:** `GET /training/exercises?status=pending|done` (lời giải ẩn tới khi có lần làm), `POST /training/exercises/{id}/attempt {answer}` — nước sai luật / lớp đánh giá sai → 400, không lưu; còn lại lưu lần làm, trả `correct`, `explanation` (nước được chấp nhận, PV, độ sâu) và bài kèm lời giải.
- **Dashboard:** `GET /stats/summary` → số buổi, số nước đã đánh giá, điểm tư duy/nước đi trung bình (chỉ giá trị khác null, kèm số mẫu), số nhận xét chưa đủ dữ liệu, 3 lỗi phổ biến nhất, chuỗi theo tuần ISO và theo tháng (UTC), kỹ năng cần cải thiện (trung bình thấp nhất với ≥ 5 câu trả lời; không đủ → `skills_message`). DB trống → 0/null + "Chưa có dữ liệu", không có số giả.
- **Export/backup:** `GET /data/export` tải JSON mọi bảng người dùng (`export_json`, có cả `engine_cache`). `POST /data/backup` ghi bản sao `coach-backup-<UTC timestamp>.db` vào thư mục chứa DB qua SQLite online backup, trả đường dẫn; chỉ giữ 10 bản mới nhất. Chưa có import.

## 11. Đóng gói Windows

- **Backend → 1 thư mục:** `backend/packaging/xqc-backend.spec` (PyInstaller **onedir**, `console=False`) → `backend/dist/xqc-backend/` (`xqc-backend.exe` + `_internal/`), gồm `app/migrations/*.sql` (đọc qua `importlib.resources`), `pyffish`, `cv2`, `numpy`, `anthropic`/`httpx2`, mọi submodule `uvicorn`. Không dùng onefile: onefile giải nén ~100 MB vào `%TEMP%\_MEI…` mỗi lần chạy và để lại rác khi bị kill. **Không** chứa Pikafish. Bản Linux thử local: 275 MB chưa nén (onefile nén: 108 MB); bộ cài NSIS/MSI tự nén.
- **Giấy phép:** `backend/packaging/collect_licenses.py` đi theo cây dependency runtime của `xiangqi-coach-backend` (không extras) và ghi `licenses/` (GPL-3.0, `NOTICE.txt`, `THIRD_PARTY_LICENSES.txt` từ dist-info của từng gói).
- **Resource chỉ khi đóng gói:** `desktop/src-tauri/tauri.bundle.conf.json` (truyền bằng `tauri build --config …`, CLI gộp vào config rồi chuyển cho cả `tauri-build` lẫn bundler) map `backend/dist/xqc-backend/` → `backend/`, `backend/dist/licenses/` → `licenses/`, 5 file `engine/pikafish/` → `pikafish/`. `tauri.conf.json` gốc không có resource nào nên `tauri dev`/`cargo build` không cần file đã build. Không dùng `externalBin`/sidecar vì backend là cả một thư mục.
- **Khởi động** (`desktop/src-tauri/src/lib.rs`, `tauri-plugin-shell` ≥ 2.6): trong `setup`, nếu có `<resource_dir>/backend/xqc-backend.exe` thì Rust chạy nó bằng `app.shell().command(...)` (gọi từ Rust nên không cần quyền shell trong capability; frontend không gọi được shell) với `XQC_PORT=8765`, `XQC_PIKAFISH_PATH=<resource_dir>/pikafish/pikafish.exe`, `XQC_EXIT_ON_STDIN_EOF=1`, `set_process_group(true)` (job object). `XQC_DB_PATH` để mặc định (`%APPDATA%\XiangqiCoach\coach.db`). Không có file (dev) → log "dev mode", không spawn. Log backend được in ra stderr của app (`[xqc-backend] …`). Spawn lỗi hoặc cổng 8765 bị chiếm → frontend báo backend offline.
- **Tắt:** ở `RunEvent::Exit`, Rust ghi một dòng vào stdin của backend; `app/__main__.py` (chỉ khi `XQC_EXIT_ON_STDIN_EOF=1`) có thread đọc stdin, gặp dòng hoặc EOF thì đặt `server.should_exit` → uvicorn chạy lifespan shutdown (engine `quit`, đóng DB). Chờ tối đa 3 s, quá thì `kill()` cả job object (backend + Pikafish).
- **Một instance:** `tauri-plugin-single-instance` (đăng ký đầu tiên) — mở lần hai thì focus cửa sổ cũ và thoát trước khi spawn backend thứ hai.
- **Engine:** không gửi `EvalFile` tuyệt đối; Pikafish chạy với cwd = thư mục engine nên tự nạp `pikafish.nnue` tương đối (tránh lỗi đường dẫn có ký tự không phải ASCII trên Windows).
- **CSP:** `connect-src` thêm `http://127.0.0.1:8765`.
- **CI** (`.github/workflows/windows-build.yml`, windows-latest, `permissions: contents: read`): cài backend + PyInstaller 6.22.3 → `fetch_pikafish.py` → `pytest -q` (gồm test engine) → build onedir → `collect_licenses.py` → smoke test (`/health`, `/engine/status`, `POST /engine/analyze` độ sâu 6 với `X-XQC-Client: 1`, đóng stdin → thoát mã 0 trong 10 s, không còn `pikafish`) → `npm ci`, `npm test`, `npx tauri build --config src-tauri/tauri.bundle.conf.json` → artifact `.exe` (NSIS) + `.msi`.
- **GPL-3.0:** bộ cài chứa Pikafish (GPL-3.0) và backend liên kết pyffish (GPL-3.0); toàn bộ phân phối theo GPL-3.0 (`LICENSE` ở gốc repo), giấy phép và link mã nguồn nằm trong `licenses/` và `pikafish/`.
