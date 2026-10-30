# 00. Tổng quan bài toán

## Mục tiêu
Xây agent trả lời **câu hỏi tiếng Việt đời thường** trực tiếp trên **dữ liệu bảng** của hộ kinh doanh nhỏ (CSV, XLSX, SQLite).
Câu hỏi có thể viết tắt, teencode, sai chính tả, không dấu, ví dụ: `sp bán dc nhiều nhất tuần rồi là gì`.

## Đầu vào
- Gói dữ liệu của một business: một hoặc nhiều file `.csv/.xlsx/.sqlite` + `README.md` mô tả.
- Câu hỏi (`questions.jsonl`: id, business_id, question, as_of_date).
- `as_of_date`: mốc "hôm nay" để giải các cụm "tháng này", "tuần rồi", "cùng kỳ năm ngoái".
- `rulebook.md` (luật mặc định, **khác nhau giữa các split**) và `calendar.csv` (lịch dương–âm, Tết).

## Đầu ra (`submission.jsonl`, mỗi dòng một JSON)
| type | answer | Ghi chú |
|---|---|---|
| number | số | VND/đếm là số nguyên, còn lại làm tròn 2 chữ số |
| percent | số (đơn vị %) | làm tròn 2 chữ số, đúng dấu |
| string | chuỗi | tên sản phẩm/khách/chi nhánh/thứ... |
| date | "yyyy-mm-dd" hoặc "yyyy-mm" | câu hỏi về tháng thì yyyy-mm |
| boolean | true/false | |
| list | danh sách có thứ tự | khớp theo vị trí |
| table | {columns, rows} | |
| unanswerable | (reason tùy chọn) | dữ liệu không đủ để trả lời |
| abstain | — | agent chủ động không trả lời |

## Cách chấm
- Mỗi câu: **đúng / sai / abstain**, không có điểm từng phần; đúng khi `type` trùng và giá trị khớp.
- String: chuẩn hóa (NFC, chữ thường, ký tự không phải chữ/số thành khoảng trắng, gộp khoảng trắng; **giữ dấu**), so sánh với mọi dạng chấp nhận (alias: các cách viết trong dữ liệu + mã sản phẩm).
- Câu thiếu trong file bị tính là abstain.
- Điểm cuối là điểm khi BTC chạy lại Docker image trên private test; kết quả hai lần chạy phải lệch ≤ 0,03.

## Ràng buộc kỹ thuật (tóm tắt)
Chạy offline hoàn toàn; tổng tham số mô hình ≤ 15B; 2 × RTX 5090, tối đa 6 giờ cho toàn bộ private test (gồm nạp mô hình); `/data` chỉ đọc; không hard-code; không dùng test để huấn luyện; phải ghi log từng câu.

## Hệ quả thiết kế
1. Sai một ký tự là sai cả câu → **LLM không được tự tính số**, phải sinh code rồi thực thi.
2. Không phạt rõ ràng việc abstain so với sai (cần xác nhận trong luật chấm) → có cơ chế **ngưỡng tin cậy** để chọn abstain khi không chắc.
3. Rulebook thay đổi theo split → luật nghiệp vụ phải được **đọc và tham số hóa**, không viết cứng.
4. Loại hình kinh doanh mới xuất hiện ở private test → pipeline phải tổng quát, không gắn với ngành cụ thể.
