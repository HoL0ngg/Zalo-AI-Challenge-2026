# 03. Bước 2 — Question Understanding

Gồm hai phần nối tiếp: **Normalizer** rồi **Temporal Resolver**. Câu hỏi gốc luôn được giữ để ghi log.

## 2a. Vietnamese Normalizer (sàng lọc input)
Mục tiêu: đưa câu hỏi nhiễu về câu tiếng Việt chuẩn mà **không đổi ý định**.

Các bước:
1. **Chuẩn hóa Unicode** (NFC), bỏ ký tự điều khiển, gộp khoảng trắng.
2. **Teencode / viết tắt** theo từ điển `data/teencode_dict.json`: `sp→sản phẩm`, `dc/đc→được`, `ko/k/hok→không`, `bn/bnh→bao nhiêu`, `hnay→hôm nay`, `nhìu→nhiều`...
3. **Kéo dài ký tự / lặp**: `nhiềuuu → nhiều`.
4. **Lỗi gõ Telex/VNI**: `thnags→tháng`, `banj→bạn`... dùng bảng quy tắc + từ điển từ vựng.
5. **Khôi phục dấu** cho câu viết không dấu (`thang nay hang nao ban cham nhat`): dùng mô hình/quy tắc nhẹ hoặc LLM có ràng buộc; **bước này có thể nhận kết quả sai**, nên giữ cả bản không dấu để Entity Linking so khớp song song.
6. **Tách đoạn có khả năng là tên riêng** (sản phẩm, khách) và **không sửa** chúng ở bước này, để tránh biến tên thật thành từ khác (xử lý ở bước Linking).

Nguyên tắc: sửa ít còn hơn sửa sai. Nếu không chắc, giữ nguyên và để các bước sau xử lý bằng khớp mờ.

## 2b. Temporal Resolver (rule-based, không dùng LLM)
Đầu vào: câu đã chuẩn hóa, `as_of_date`, `calendar.csv`, tham số rulebook.
Việc cần làm:
1. **Nhận diện cụm thời gian**: hôm nay, hôm qua, tuần này/tuần rồi, tháng này/tháng trước, quý, năm nay/năm ngoái, cùng kỳ năm ngoái, "7 ngày qua", Tết, Trung thu, cuối tuần, "ngày 15"...
2. **Giải thành khoảng ngày cụ thể** `[start, end]` theo rulebook:
   - Tuần mặc định Thứ 2–Chủ nhật (có thể khác ở split khác).
   - "Tháng này" = tháng chứa `as_of_date`, tính đến hết ngày đó.
   - "Cùng kỳ năm ngoái" = cùng khoảng ngày tương ứng năm trước (xử lý 29/2).
   - Cửa sổ Tết = 23 tháng Chạp đến mùng 10, tra từ `calendar.csv`.
3. **Ví dụ**: `as_of_date = 2026-03-04 (Thứ Tư)`, "tuần rồi" → `2026-02-23 .. 2026-03-01`.
4. **Ý định gợi ý** (dạng nhẹ): loại phép tính (top, tổng, so sánh, đếm, kiểm tra tồn tại), thước đo (số lượng/doanh thu) từ từ khóa như "bán chạy" → theo số lượng (theo rulebook).

## Đầu ra: `ResolvedQuestion`
`original`, `normalized`, `normalized_no_diacritics`, `periods[]` (nhãn + start/end), `intent_hints`, `rule_params`, `warnings`.

## Kiểm thử
Unit test cho: tuần Thứ 2–CN, ranh giới đầu/cuối tháng, `as_of_date` là Thứ 2 hoặc Chủ nhật, năm nhuận, cửa sổ Tết; bộ test chuẩn hóa với từng loại nhiễu (bỏ dấu, viết tắt, gõ sai).
