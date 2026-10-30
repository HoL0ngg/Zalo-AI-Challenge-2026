# 05. Bước 4 — Answerability Gate

## Mục tiêu
Quyết định câu hỏi có thể trả lời bằng dữ liệu hiện có không, trước khi tốn công sinh code.

## Kiểm tra theo thứ tự
1. **Cột/chỉ số cần thiết có tồn tại?** Ví dụ hỏi lợi nhuận nhưng không có giá vốn → `unanswerable` (reason: "Dữ liệu không có giá vốn...").
2. **Thực thể có trong dữ liệu?** `missing_entity` từ Linking (sản phẩm/khách không tồn tại).
3. **Khoảng thời gian có nằm trong phạm vi dữ liệu?** (ví dụ hỏi năm chưa có dữ liệu).
4. **Câu hỏi có đủ rõ?** (thiếu đối tượng/thước đo, mơ hồ nặng) → có thể abstain.
5. **Có mâu thuẫn với README/rulebook?** (ví dụ metric bị rulebook loại trừ).

## Cách làm
- Lớp 1: **heuristic/quy tắc** (nhanh, tái lập).
- Lớp 2: **LLM phán đoán** với đầu ra có cấu trúc (answerable / unanswerable + lý do) cho ca khó.
- Ca nhập nhằng: **không chặn cứng**; cho đi tiếp nhưng ghi cờ để bước Voting hạ độ tin cậy.

## unanswerable vs abstain
- `unanswerable`: có bằng chứng dữ liệu **không thể** hỗ trợ.
- `abstain`: dữ liệu có thể đủ nhưng agent **không đủ tin cậy**.
Hai loại được chấm khác nhau; cần đối chiếu luật chấm chính thức để đặt ngưỡng.

## Rủi ro
Chặn nhầm câu trả lời được (mất điểm chắc chắn) tệ hơn bỏ sót câu không trả lời được. Mặc định nghiêng về cho đi tiếp, trừ khi bằng chứng rõ ràng.
