# 07. Bước 6 — Sandbox Executor & Self-repair

## Sandbox
- **SQL**: kết nối DuckDB **read-only**, có timeout.
- **Python**: chạy trong subprocess riêng: giới hạn thời gian và bộ nhớ, không mạng, chỉ cho import một danh sách an toàn (pandas, numpy, duckdb, datetime, math, re, unicodedata), dữ liệu chỉ đọc, file tạm ghi ra `/tmp`.
- Chặn ghi vào `/data`, chặn lệnh hệ thống và truy cập mạng.
- Kết quả được chuẩn hóa thành cấu trúc trung gian (scalar, list, bảng).

## Self-repair
1. Nếu lỗi (cú pháp, cột không tồn tại, kiểu dữ liệu, timeout, kết quả rỗng bất thường), gửi lại cho LLM: code cũ + thông báo lỗi/traceback + schema liên quan.
2. Tối đa K vòng (cấu hình). Hết vòng vẫn lỗi → ứng viên đó bị loại khỏi bỏ phiếu.
3. Ghi log mỗi vòng (code, lỗi, code sửa) vào `/result/logs/`.

## Kiểm tra hợp lý sau thực thi (sanity checks)
- Kết quả rỗng khi câu hỏi mong có giá trị → thử sửa/gắn cờ.
- Giá trị âm bất thường, tỉ lệ > 100% không hợp lý, ngày ngoài phạm vi.
- Số dòng sau JOIN tăng đột biến (dấu hiệu nhân đôi).

## Hiệu năng
Có ngân sách thời gian cho từng câu; chạy ứng viên song song khi có thể; tái dùng kết nối DuckDB theo business.
