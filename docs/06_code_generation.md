# 06. Bước 5 — Code Generation

## Mục tiêu
Từ ngữ cảnh đã chuẩn bị, LLM sinh **SQL (DuckDB) hoặc Python (pandas)** để tính đáp án. Sinh N ứng viên độc lập để bỏ phiếu.

## Prompt gồm
1. **Vai trò + quy tắc đầu ra**: chỉ trả code, không giải thích; kết quả cuối gán vào biến/trả về cột chuẩn.
2. **Schema** (bảng, cột, kiểu, vài dòng mẫu) từ Profile.
3. **Rulebook của split** (trích phần liên quan: định nghĩa doanh thu, loại đơn hủy/trả hàng, bán chạy = theo số lượng...).
4. **Khoảng thời gian đã giải** (ngày cụ thể, không để LLM tự tính).
5. **Thực thể đã nối** (giá trị đúng trong dữ liệu, kèm danh sách alias/ứng viên nếu mơ hồ).
6. **Kiểu đáp án kỳ vọng** (number/percent/string/...) và quy tắc làm tròn.
7. **Few-shot** lấy động từ tập train/dữ liệu tự sinh theo độ tương tự (embedding hoặc loại câu hỏi).

## Chiến lược sinh
- N ứng viên (ví dụ 3–5) với seed cố định; có thể đa dạng hóa bằng thay đổi thứ tự few-shot hoặc yêu cầu SQL vs Python.
- Temperature 0 hoặc rất thấp để tái lập; đa dạng đến từ prompt, không từ ngẫu nhiên.
- Có thể dùng guided decoding để ép dạng đầu ra (khối code, JSON) giảm lỗi cú pháp.
- Kiểm tra cú pháp SQL bằng sqlglot trước khi chạy.

## Chọn SQL hay Python
- SQL: gọn, nhanh, phù hợp tổng hợp/lọc/nhóm.
- Python: dùng khi cần logic phức tạp (giá vốn bình quân theo lô, so sánh kỳ, xử lý chuỗi).

## Cài đặt hiện tại
Prompt dạng chat (system + user), đầu ra `<sql>…</sql>`, parser và báo cáo theo bước: xem [16_phase4_p0.md](16_phase4_p0.md).

## Rủi ro và cách giảm
Quên loại đơn hủy/trả hàng; dùng sai cột ngày; JOIN nhân đôi dòng; nhầm số lượng với doanh thu. → Đưa rulebook vào prompt, thêm checklist trong system prompt, và bước Voting bắt các lệch.
