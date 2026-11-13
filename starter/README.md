# Starter · PostgreSQL + pgvector

Bộ pipeline local cho lab cá nhân. Docker Compose tạo PostgreSQL + pgvector; mã trong `src/` đọc PDF, tạo embedding đa ngữ local, lưu vector và chạy ba cấu hình retrieval. Corpus và benchmark hiện được lấy từ `../data/` và `../benchmark/`.

## Cấu trúc

```text
starter/
├── docker-compose.yml     # PostgreSQL 16 + pgvector, chỉ mở cổng local
├── init.sql               # bật extension khi tạo database mới
├── requirements.txt       # psycopg, pypdf, python-dotenv, sentence-transformers
├── .env.example           # cấu hình mẫu; copy thành .env
├── scripts/check_setup.py # kiểm tra kết nối và extension (đã chạy được)
├── src/                   # ingestion, chunking, embedding, store, evaluation, run
└── results/               # trace top-3 và metrics được tạo khi chạy
```

## 1. Cài và kiểm tra database

Cần Docker Desktop hoặc Docker Engine + Compose, Python **3.11–3.14**, và mạng để tải image/dependencies lần đầu. Các lệnh sau chạy từ thư mục `starter/`:

```bash
cd starter
python -m venv .venv
```

Kích hoạt `.venv`: macOS/Linux dùng `source .venv/bin/activate`; Windows PowerShell dùng `.venv\Scripts\Activate.ps1`. Sau đó:

```bash
python -m pip install -r requirements.txt
# macOS/Linux: cp .env.example .env
# Windows PowerShell: Copy-Item .env.example .env
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py
```

Kỳ vọng: hiện tên database, phiên bản PostgreSQL và pgvector, sau đó `Setup OK`. Đây **chỉ là kiểm tra hạ tầng**, không phải kết quả benchmark. Docker dùng cổng `127.0.0.1:55433` và mật khẩu cố định **chỉ dùng local cho lab**; nếu cổng bận, sửa đồng thời port trong `docker-compose.yml` và `DATABASE_URL` trong `.env`. `init.sql` chỉ chạy khi volume mới được tạo; nếu database sẵn có chưa bật extension, xem log Docker và kiểm tra cấu hình thay vì xóa volume chứa dữ liệu.

Dừng container nhưng giữ dữ liệu:

```bash
docker compose -p day6_student_starter stop
```

## 2. Embedding model

Mặc định dùng `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, chạy local và không cần API key. Lần đầu chạy cần mạng để tải model. Có thể thay `EMBEDDING_MODEL` trong `.env`, nhưng phải ghi lại model và số chiều, đồng thời dùng cùng model cho cả ba chiến lược.

## 3. Hoàn thiện pipeline

1. Xem nguồn, quyền, trang nội dung và phân đoạn metadata trong [manifest](../data/manifest.json).
2. Xác minh đủ câu hỏi, split và evidence trước khi chạy retrieval:
   `python -m src.run --validate-only`
3. Cấu hình A dùng chunk cố định; B dùng chunk theo đoạn; C dùng cùng chunking với B nhưng áp dụng filter theo `section` khi câu hỏi có filter.
4. Chạy database: `docker compose -p day6_student_starter up -d --wait`, sau đó `python -m src.run`.
5. Đọc `results/traces.json` và `results/summary.json`. Các nhãn coherence, metadata usefulness và grounding cần audit thủ công; pipeline không tự tạo nhãn này.

Pipeline kiểm tra SHA-256 của PDF và benchmark theo manifest trước khi xử lý, ghim revision mặc định của model, và lưu hash cùng phiên bản runtime/package/PostgreSQL/pgvector và thiết bị embedding vào `results/summary.json`. Các package chính và dependency ảnh hưởng đến model/vector được ghim phiên bản trong `requirements.txt`.

### Kiểm thử tái lập

Sau khi database sẵn sàng và model đã tải về, chạy từ `starter/`:

```bash
python scripts/check_reproducibility.py
```

Script chạy pipeline hai lần, so sánh trace (điểm similarity được làm tròn 6 chữ số), metric, cấu hình và số chunk trong database; các trường thời gian được bỏ qua. Kỳ vọng: `Reproducibility OK`. Script ghi đè các file kết quả như một lần chạy bình thường.

Lưu code, cấu hình, kết quả và lệnh chạy để người chấm tái lập; không commit key, dữ liệu mật hoặc dữ liệu không có quyền chia sẻ.
