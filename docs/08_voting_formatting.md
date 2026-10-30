# 08. Bước 7–8 — Voting & Formatting

## Voting (theo kết quả thực thi)
1. Chuẩn hóa kết quả của từng ứng viên (làm tròn, sắp xếp ổn định, so sánh chuỗi sau chuẩn hóa).
2. Nhóm các kết quả giống nhau; chọn nhóm đông nhất.
3. **Độ tin cậy** = tỉ lệ phiếu thắng (có thể trọng số theo ứng viên không phải sửa lỗi, kết quả qua sanity check).
4. Hòa phiếu: tie-break cố định (ví dụ ưu tiên ứng viên SQL, rồi theo chỉ số sinh) để tái lập.
5. Độ tin cậy dưới ngưỡng → `abstain` (ngưỡng cấu hình; chỉnh theo luật chấm).

Lưu ý: bỏ phiếu theo **kết quả**, không theo văn bản code.

## Formatter
Ép kết quả về đúng `type` và định dạng:
| type | Quy tắc |
|---|---|
| number | VND/đếm: số nguyên; khác: làm tròn 2 chữ số |
| percent | đơn vị %, làm tròn 2 chữ số, đúng dấu (giảm = âm) |
| string | NFC; dùng đúng cách viết có trong dữ liệu |
| date | `yyyy-mm-dd`; câu hỏi về tháng → `yyyy-mm` |
| boolean | true/false |
| list | có thứ tự đúng yêu cầu (top-3 theo xếp hạng) |
| table | `{columns:[...], rows:[[...]]}`, cột theo ngữ cảnh câu hỏi |
Dùng Pydantic để kiểm tra schema. Nếu không định dạng được → `abstain` (không ghi đáp án sai kiểu).

## Chọn `type`
Suy ra từ ý định và kết quả: hỏi "là gì/ai" → string; "bao nhiêu" → number; "tăng/giảm bao nhiêu %" → percent; "có... không" → boolean; "ngày nào" → date; "danh sách/top N" → list; bảng nhiều cột → table.
Sai `type` là sai cả câu dù giá trị đúng.

## Ghi kết quả
Ghi một dòng vào `submission.jsonl` ngay khi xong câu (append + flush + fsync); ghi log chi tiết song song.
