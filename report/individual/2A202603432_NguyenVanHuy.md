# Báo cáo cá nhân — Day 6

> **Trạng thái audit:** Các nhãn coherence và grounding dưới đây được tạo từ đánh giá hỗ trợ bởi AI, không phải đánh giá độc lập của học viên. Cần đối chiếu lại từng chunk với PDF và xác nhận/sửa nhãn trước khi nộp chính thức. Các số retrieval và metadata được lấy từ kết quả pipeline đã lưu.

## Dữ liệu và pipeline

- **Chủ đề:** Kỹ thuật thu hoạch năng lượng RF (RF energy harvesting).
- **Nguồn:** *RF Energy-Harvesting Techniques: Applications, Recent Developments, Challenges, and Future Opportunities*, DOI [10.3390/telecom6030045](https://doi.org/10.3390/telecom6030045).
- **Quyền:** Bài báo ghi giấy phép CC BY 4.0; thông tin được lưu trong `data/manifest.json`.
- **Phạm vi trang:** 33 trang nội dung, trang PDF 2–34; không tính trang bìa và phần tài liệu tham khảo. `page` trong metadata là số trang vật lý của PDF.
- **Chuẩn hóa:** `pypdf` trích xuất văn bản; Unicode NFKC, nối từ bị ngắt ở cuối dòng, gộp xuống dòng đơn thành khoảng trắng nhưng giữ ranh giới đoạn. Trang không có văn bản trích xuất được phát cảnh báo. Giới hạn: PDF có thể làm mất cấu trúc bảng/bố cục; không dùng OCR.
- **Embedding:** Sentence Transformers chạy local, model `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`, 384 chiều; cùng model cho query và document, vector được chuẩn hóa. Không gọi API, chi phí dịch vụ $0.
- **Vector store:** PostgreSQL 16.16 + pgvector 0.8.7; cosine distance, exact search; Docker Compose, database `day6_lab`, cổng local `127.0.0.1:55433`.
- **Runtime chạy thử:** Python 3.13.0, Windows 11, CPU. Các phiên bản package đã ghim trong `starter/requirements.txt` và được ghi đầy đủ trong `starter/results/summary.json`.
- **Metadata mỗi chunk:** `document_id`, `source`, `page`, và `section`. `section` được gán theo page ranges của manifest (overview, fundamentals, techniques, developments, applications, challenges, future, conclusions); dùng để lọc khi câu hỏi nêu phạm vi. Chunk ID chứa document, trang, phương pháp, chỉ số chunk và hash nội dung để hỗ trợ truy vết.
- **Tính tái lập:** PDF SHA-256 `2f2f6d7905e9c9df70a4d58ca24a89a7271e2e16ae4c553594813286e9eb2d72`; benchmark SHA-256 `64653484ef5e4c57fc83c7e87116c52c15d074466bb0c34c53972865ebb453d8`. Pipeline kiểm tra hai hash trước khi chạy.

## Cấu hình và benchmark

- **A:** chunk ký tự cố định, tối đa 500 ký tự, overlap 50.
- **B:** chunk theo đoạn/câu, tối đa 500 ký tự; không filter.
- **C:** cùng chunk và metadata như B; chỉ thêm filter `section` khi câu hỏi cung cấp filter. B–C chỉ khác việc áp dụng filter.
- **Benchmark:** 20 câu hỏi, 15 dev / 5 test; 5 câu có filter (2 dev, 3 test). Mỗi câu có expected answer, trang nguồn và evidence quote. Trước khi chạy, validator kiểm tra evidence sau chuẩn hóa nằm trên trang PDF được khai báo, split hợp lệ và filter bao gồm gold page. `section` được coi là phạm vi do người dùng cung cấp trước retrieval, không lấy từ đáp án/gold.
- **Quy tắc chọn đã ghi trước khi xem test** trong `artifacts/experiment_log.csv`: tối đa hóa dev Evidence Hit@3, tiếp đó dev Hit@1; dùng audit thủ công và runtime để phân định nếu hòa. Theo quy tắc này A đứng đầu dev Evidence Hit@3. Test chỉ dùng đánh giá cuối, không dùng để đổi lựa chọn.

## Kết quả

### Retrieval

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Số chunk | Ingest (giây) | Retrieval (giây) | Chi phí API |
|---|---|---:|---:|---:|---:|---:|---:|
| A | dev | 2/15 | 5/15 | 266 | 21.082 | 0.889 | $0 |
| A | test | 2/5 | 2/5 | 266 | 21.082 | 0.889 | $0 |
| B | dev | 2/15 | 4/15 | 288 | 30.424 | 1.360 | $0 |
| B | test | 3/5 | 4/5 | 288 | 30.424 | 1.360 | $0 |
| C | dev | 2/15 | 4/15 | 288 | 0.894* | 1.830 | $0 |
| C | test | 3/5 | 4/5 | 288 | 0.894* | 1.830 | $0 |

`*` C tái sử dụng 288 embedding đã tạo cho B; 0.894 giây chỉ là thời gian ghi/index, không phải ingest lạnh hay so sánh embedding công bằng. Thời gian là một lần chạy, phụ thuộc máy và tải hệ thống.

### Audit các khía cạnh còn lại

| Strategy | Coherence trung bình /2 (n=10) | Metadata đủ và đúng (top-3 test) | Filter tuân thủ | Grounding 0/1/2 (số câu) | Grounding trung bình /2 |
|---|---:|---:|---:|---:|---:|
| A | 1.9/2 | 15/15 | N/A — không áp dụng filter | 1 / 2 / 2 | 1.2 |
| B | 1.8/2 | 15/15 | N/A — không áp dụng filter | 1 / 0 / 4 | 1.6 |
| C | 1.8/2 | 15/15 | 9/9 câu test có filter; 15/15 bản ghi top-3 của cả 5 câu lọc | 1 / 0 / 4 | 1.6 |

Metadata được kiểm tra trên 5 câu test × top-3 mỗi cấu hình: `document_id`, source path, page và section khớp manifest 45/45 bản ghi. Section hữu ích để giới hạn retrieval và giải thích nguồn; hạn chế là nhãn gán theo khoảng trang, khá thô nếu một trang nằm sát ranh giới section hoặc chứa nhiều chủ đề.

Các nhãn coherence sử dụng cùng 10 evidence anchor (`q01`, `q02`, `q03`, `q05`–`q11`) cho cả ba cấu hình. Các nhãn grounding dùng toàn bộ 5 câu test (`q16`–`q20`) mỗi cấu hình. Điểm và lý do từng mẫu nằm trong `starter/results/manual_audit.json`; hiện cần tác giả kiểm tra và xác nhận độc lập.

### Cách chạy và artifacts

Chạy từ thư mục `starter/` sau khi tạo môi trường, cài `requirements.txt`, cấu hình `.env` theo `.env.example` và khởi động Docker:

```powershell
python -m src.run --validate-only
docker compose -p day6_student_starter up -d --wait
python -m src.run
python scripts/check_reproducibility.py
```

Artifacts:
- `starter/results/traces.json` — top-3, score, provenance và kết quả evidence cho 60 lượt câu hỏi × chiến lược.
- `starter/results/summary.json` — metrics dev/test, cấu hình, thời gian, hash, runtime và phiên bản backend.
- `starter/results/manual_audit.json` — mẫu audit và nhãn sơ bộ cần tác giả xác minh.
- `artifacts/experiment_log.csv` — giả thuyết, cấu hình và quy tắc chọn.

Kiểm thử tái lập đã chạy pipeline hai lần liên tiếp: trace/metric ổn định sau khi làm tròn score 6 chữ số; số chunk trong DB khớp và không có chunk ID trùng: A=266, B=288, C=288.

## Phân tích và kết luận

- **A–B:** A cao hơn B trên dev Evidence Hit@3 (5/15 so với 4/15), dev Hit@1 bằng nhau (2/15). Mẫu coherence sơ bộ của A cũng cao hơn nhẹ (1.9 so với 1.8). Trên test nhỏ, B cao hơn (Evidence Hit@3 4/5 so với 2/5; Hit@1 3/5 so với 2/5). B tạo nhiều chunk hơn (288 so với 266) và lần ingest đầy đủ trong lần đo này lâu hơn.
- **B–C:** chunking, chunk count và embedding giống nhau. Filter của C tuân thủ trong toàn bộ các bản ghi có filter đã đo, nhưng tổng Evidence Hit@3 không đổi so với B. Trên câu `q13`, filter section vẫn không đưa gold evidence vào top-3. Filter tăng khả năng giới hạn phạm vi/truy vết, nhưng không đảm bảo tăng recall.
- **Ví dụ lỗi 1 — `q16`:** hỏi nguồn môi trường và lợi ích của hybrid harvesting (gold PDF trang 18). Audit sơ bộ đánh giá top-3 của A/B/C không chứa đủ bằng chứng về danh sách nguồn và lợi ích; cả ba nhận grounding 0. Đây là lỗi truy xuất/evidence, không phải phán xét câu trả lời do LLM sinh ra.
- **Ví dụ lỗi 2 — `q18`:** hỏi mô hình spectrum prediction (gold PDF trang 23). Top-3 của A có chủ đề ML/adaptive spectrum liên quan nhưng không hỗ trợ đủ phần dự đoán băng tần tối ưu; B/C có chunk hỗ trợ trực tiếp ở hạng 1 và được chấm grounding 2. Câu này có filter `developments`; filter không cứu được cấu hình A vì A không áp dụng filter.
- **Lựa chọn:** theo tiêu chí dev đã ghi trước, chọn A cho mục tiêu ưu tiên Evidence Hit@3 trên dev của benchmark này. B/C cho kết quả test tốt hơn và grounding sơ bộ cao hơn nhưng test chỉ có 5 câu, không đủ cơ sở để đổi lựa chọn hoặc kết luận khái quát. C phù hợp khi cần ràng buộc theo section có chủ đích; không nên quảng bá rằng filter cải thiện metric tổng thể trong thí nghiệm này.
- **Giới hạn và cải tiến:** chỉ có một bài báo và một test gồm 5 câu; section gán theo page range; trích xuất PDF có thể làm phẳng bảng; thời gian đơn lần chạy và C dùng cache nên không so sánh cold ingest; nhãn audit chưa được tác giả xác minh. Nếu mở rộng, cần người chấm độc lập xác nhận nhãn, thêm tài liệu/câu hỏi và test mới, cải thiện phát hiện heading/bảng, đo lặp nhiều lần với cache state được kiểm soát, đồng thời đánh giá riêng câu có filter.
