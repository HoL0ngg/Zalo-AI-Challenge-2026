# 18. Phase 4 / P2 — Dữ liệu chính thức: growth, repair và những gì còn thiếu

Bộ train chính thức (3000 câu, 30 business `biz_1xx`, có đáp án) và `public_test` (1000 câu, 14 business `dev_0xx`, không có đáp án) nằm ở `dataset/`.
**`dataset/train` và `dataset/dev` cũ là dữ liệu tổng hợp** (`synth/`); bản tổng hợp còn ở `synth/out/` và các test hồi quy Phase 3 đọc ở đó.
Toàn bộ số đo ở docs 16–17 là trên dữ liệu tổng hợp; **chưa có số đo LLM thật nào trên dữ liệu chính thức**.

## Luật chấm chính thức (rulebook §9) — đã chốt câu hỏi còn mở ở docs/12
Đúng **+1**, sai **−1**, abstain hoặc thiếu dòng **0**. Hệ quả: chỉ nên trả lời khi xác suất đúng > 50%; một câu sai tệ bằng một câu đúng có lợi.
`datamate report` giờ in thêm `points` (`correct`, `wrong`, `abstain`, `score`), `datamate eval` in `accuracy` và `points`.

## Kiểm tra gói dữ liệu không cần LLM
`python scripts/check_package.py dataset/train --answers dataset/train/answers.jsonl [--business biz_123]` (≈11 phút cho cả train): ingest, lớp chuẩn, kỳ, gate.

Kết quả đầu tiên trên train chính thức (trước các sửa ở docs này):
| | |
|---|---|
| business nạp được | 30/30 |
| lớp chuẩn hoàn chỉnh (`v_sales`...) | **1/30** |
| gate bắt đúng câu unanswerable | 0/70 |
| gate chặn nhầm | 34 (cả 34 ở `biz_123`) |
| câu percent có đủ 2 kỳ | 173/598 |

## Đã sửa
| Vấn đề | Sửa | File |
|---|---|---|
| "tháng 3/2025 … so với tháng liền trước" ra tháng của **hôm nay** (8/2026) thay vì 2/2025 | Sau từ nối so sánh (`so với`, `so vs`, `vs`), cụm "X trước/liền trước/rồi" là kỳ liền trước **kỳ chính**, không phải trước hôm nay. Xử lý cả khi cụm so sánh đứng trước kỳ chính. Hỗ trợ viết tắt `th`/`thg` | `understanding/temporal.py` |
| "tháng này so với tháng trước" lấy cả tháng trước | Rulebook chính thức: **cùng số ngày** (chặn ở ngày cuối tháng trước). Là tham số `time.month_compare_same_days` (mặc định `false`, giữ luật cũ); bật tự động khi rulebook có câu đó (đọc từ văn xuôi). Tuần/quý/năm đang mở giữ nguyên | `temporal.py`, `configs/rules_defaults.yaml` |
| Câu tăng giá chỉ ra ngày đổi giá | "N ngày kể từ ngày đó" vs "N ngày liền trước": hai kỳ `[D, D+N−1]` và `[D−N, D−1]` | `temporal.py` (`_price_change_windows`) |
| Mọi câu "%" bị coi là tăng trưởng | `intent_hints.percent_kind` ∈ `growth, share, rate, proportion, price_effect, shift_compare` (regex ở `intent_keywords.percent_kind`, thứ tự quan trọng) | `understanding/intent.py` |
| Model quên `FROM` (17/19 câu growth abstain; repair chép lại y nguyên) | (a) prompt có **khuôn SQL** theo `percent_kind`, điền sẵn ngày kỳ chính/kỳ so sánh (`answer_shape`); (b) `quick_fix` thêm `FROM <bảng>` xác định khi chỉ một bảng được viện dẫn | `codegen/prompt_builder.py`, `execution/repair.py` |
| Repair 1 lượt, mù lỗi | `repair` mới: chẩn đoán theo loại lỗi (thiếu bảng, cột gần đúng, mơ hồ, GROUP BY, ép kiểu), liệt kê cột thật của bảng liên quan, gửi kèm các lần thất bại trước, hỏi lại một lần nếu model lặp lại câu cũ. Pipeline cho tối đa 3 vòng (`max_repair_attempts`), dùng `quick_fix` trước | `execution/repair.py`, `runtime/pipeline.py` |
| xlsx: "12 columns passed, passed data had 11" làm mất bảng đơn hàng | openpyxl bỏ ô trống cuối dòng; bù cho đủ độ rộng tiêu đề | `ingest/loader.py` |
| Gate chặn nhầm công nợ/giá vốn/hạn dùng khi lớp chuẩn nhận vai trò sai | Thêm `column_names` cho 3 khái niệm: chỉ kết luận "thiếu" khi dữ liệu thô cũng không có cột gợi ý | `configs/schema_roles.yaml` |
| T4 chạy 3000 câu quá lâu | `--max-per-business N` (mẫu xác định, N câu đầu mỗi business); `eval --logged-only` chấm đúng tập đã chạy; notebook mặc định mẫu 8 câu/business | `runtime/runner.py`, `runtime/cli.py`, `dataparallel.py`, notebook |

Đo trên log cũ (dữ liệu tổng hợp): `quick_fix` sửa được 18/39 lỗi thực thi lần đầu, cả 18 chạy được, 11 ra đúng đáp án (trước đó cả 18 abstain).

## Còn lại — việc lớn nhất
**Lớp chuẩn (Phase 3) chưa hiểu dữ liệu chính thức.** Mỗi business là một kiểu xuất file POS khác nhau (tên cột tiếng Việt như `Mã hóa đơn`, `Thời gian`, `Trạng thái`; ngày lẫn `01/02/2025`, số serial Excel và `1 thg 6 2025`; số lượng `1 cái`; mỗi tháng một sheet; bảng quy đổi đơn vị; sổ quỹ; phiếu giao hàng).
Khi không ghép đủ vai trò, prompt dùng schema thô và README bị cắt ở 2000 ký tự, trong khi README chứa thông tin quyết định (quy đổi đơn vị, ý nghĩa cột, quy ước nợ).
- Ví dụ prompt thô: `biz_115` ≈ 36 000 ký tự (16 bảng, mỗi tháng một sheet) vượt `max_model_len: 8192` trên T4 → câu đó abstain; `biz_106` ≈ 16 700.
- Hướng làm: đọc **README của từng business** (`- **Cột**: ý nghĩa`) để gán vai trò (đơn giá, trạng thái đơn, tên hàng, ngày bán, số lượng quy đổi, thành tiền sau giảm, mã/tên khách), thống nhất ngày/tiền/số lượng, gộp các sheet theo tháng, đọc bảng quy đổi đơn vị, và 4 trạng thái đơn của rulebook §8.
- Chưa làm: gate "kỳ nằm ngoài khoảng dữ liệu" (nguồn chính của 70 câu unanswerable) cho business chưa có lớp chuẩn; `weekday_vi`, `v_inventory`, giá vốn theo dòng bán (rulebook §5), đơn vị cơ bản.

## Kết quả Kaggle đầu tiên trên `public_test` (1000 câu, 2×T4, Qwen2.5-Coder-7B-AWQ, `max_model_len` 8192)
Chỉ **84/1000** câu có trả lời (916 abstain). Nguyên nhân (đọc từ `logs/questions.jsonl`):
| Nguyên nhân | Số câu | Ghi chú |
|---|---|---|
| Prompt vượt 8192 token (`VLLMValidationError`) | 622 | 8/14 business (dev_002/003/004/005/008/012/013/014) abstain 100%: profile thô quá lớn |
| `Parser Error` ở mọi lần thử | 238 | model viết `Thành tiền`, `Ngày tháng` không có nháy kép; 5 business (dev_001/007/010/011/...) |
| Lỗi cột/bảng/khác | ~40 | |
Mẫu 64 câu `train_01…08` trong `datamate_results_2` là **dữ liệu tổng hợp** (cell 1b cũ còn fallback sang repo): 0,734 (47/64), +33 điểm, so với 0,622 trước đó; chỉ là mốc so sánh nội bộ.

## Sửa sau lần chạy đó (chưa kiểm chứng trên Kaggle; không còn dữ liệu chính thức trên máy dev)
- `prompt_builder.compact_profile`: mỗi cột một dòng `"tên" KIỂU e.g. 3 mẫu ngắn` (tên đã có nháy kép khi cần); bỏ null_ratio/min/max/distinct. Thêm dòng `RAW` hướng dẫn nháy kép, `TRY_CAST(REPLACE(...))`, đọc README.
- `loader.merge_same_schema`: sheet cùng tiêu đề trong một workbook (`02.2025`, `03.2025`…) và file chia phần (`..._1`, `..._2`) gộp thành **một bảng** + cột `_sheet`. Giảm số bảng trong prompt và cho phép truy vấn nhiều tháng trong một câu.
- `repair.quote_known_identifiers`: trước khi chạy, tự thêm nháy kép cho tên bảng/cột có thật trong schema cần nháy (dấu cách, dấu tiếng Việt, dấu chấm), bỏ qua chuỗi và định danh đã có nháy. Chạy trước mỗi lần thực thi.
- `models_kaggle.yaml`: `max_model_len` 8192 → 16384 (KV cache T4 còn dư: log báo 120k token).
- `vote_stub`: lỗi rõ ràng ("no candidate executed: …") thay cho `StopIteration`.
Hạn chế còn lại: dữ liệu thô vẫn là chuỗi (`1,234,000`, `VND 1.000`, `1 cái`, ngày hỗn hợp); model phải tự ép kiểu — đó là việc của lớp chuẩn đọc theo README.

## Lớp chuẩn theo README (`ingest/readme_layer.py`, `configs/readme_columns.yaml`)
Được ưu tiên hơn cơ chế từ đồng nghĩa cũ khi README có mục `## Cột trong \`file\``; cơ chế cũ chỉ là dự phòng (README không mô tả cột: `biz_106`, `biz_109`, `biz_123`).
- Mô tả cột trong README (`mã đơn`, `ngày bán`, `thành tiền sau giảm`, `số lượng đã đổi ra đơn vị cơ bản`…) → khái niệm chuẩn bằng regex trong `readme_columns.yaml`. Bảng nạp được ghép với file trong README **theo độ trùng tập cột**, không theo tên (tên bảng đổi khi gộp sheet).
- Tìm bảng dòng bán hàng (có hàng, số lượng, tiền); nếu ngày/trạng thái nằm ở bảng đơn khác thì ghép theo mã đơn. Gói chỉ liệt kê đơn (`biz_110`) dùng "tiền hàng của đơn" làm doanh thu.
- Tạo `v_sales, v_orders, v_valid_orders, v_lines, v_products, v_customers`; `capabilities.date_range` đủ để gate bắt "kỳ ngoài dữ liệu", các khả năng khác để `None` (không chặn).
- Quy tắc rulebook đã áp dụng: §8 ô trống dòng sau = dòng đầu của đơn (kể cả mã đơn) → mã đơn điền xuống; hai dòng giống hệt trong cùng đơn tính một lần; 4 trạng thái (huỷ, trả hàng, đang giao, hoàn thành) từ hơn 25 cách ghi (`status_patterns`); doanh thu = tổng thành tiền dòng của đơn hoàn thành/đang giao, không trừ giảm giá đơn, không VAT/ship; khách lẻ không phải khách; dòng "phí phục vụ" không phải mặt hàng (`is_item`).
- Chuẩn hóa giá trị: tiền (`115,000.0000`, `90.000đ`, `45k`, `1tr440`), ngày (`01/02/2025`, ISO có giờ, số serial Excel, `1 thg 6 2025`, `d/m` lấy năm từ tên sheet), số lượng (`5 kg`). Cơ chế cũ dùng chung bộ đọc ngày/tiền và có thêm `line_amount`, khử trùng dòng giống hệt, và nhận trạng thái "trả hàng".
- Loại dòng tổng của export: dòng không có tên/mã hàng hoặc không có số lượng (`TỔNG NGÀY 02/04`, `Tổng tháng 4/2026`).

### Kiểm tra với đáp án chính thức (`scripts/validate_layer.py`, không cần LLM)
Câu "thuần" (một kỳ, không thực thể/điều kiện phụ): doanh thu và số đơn tính từ `v_sales`/`v_valid_orders` so với đáp án train chính thức.
| Mốc | Câu khớp |
|---|---|
| Đầu tiên (chỉ README, chưa sửa lỗi dữ liệu) | 292/393 (74%) |
| Sau điền mã đơn, bỏ dòng tổng, đọc `XtrY`, serial Excel, khử trùng dòng, trạng thái trả hàng, đơn chỉ liệt kê, README theo sheet | **323/327 (98,8%)**; 29/30 business có lớp chuẩn |
Còn lại: 4 câu lệch (`biz_127`, `biz_129` theo từng món; `biz_130` "từ đầu năm tới hết hnay": chuẩn hóa không sửa được `hnay` nên chỉ ra ngày hôm nay); `biz_124` (tên cột bị đổi khác nhau ở từng bảng, README không mô tả: cần từ đồng nghĩa riêng); một số câu lệch là câu có điều kiện phụ (theo món, "từ đầu năm") mà script không lọc hết. Tồn kho, công nợ, giá vốn theo dòng (rulebook §4–5), đơn vị cơ bản và `v_inventory` **chưa có view**.
