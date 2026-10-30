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

## Phần luật đã triển khai (Phase 3)
`gate/__init__.py` chặn (`unanswerable`) chỉ khi có bằng chứng rõ: thực thể được hỏi không tồn tại (`missing_entity`), khái niệm câu hỏi cần
không có trong dữ liệu (`missing_capability`: công nợ, giá vốn, hạn dùng, nhân viên, chi phí vận hành), hoặc kỳ thời gian nằm hoàn toàn ngoài
dữ liệu (`period_outside_data`). Mơ hồ và lỗi ánh xạ không chặn. Chưa có LLM judge và ngưỡng `abstain`; những phần đó thuộc Phase 4. Chi tiết: [15_phase3.md](15_phase3.md).

## Kiểm tra theo dữ liệu (Phase 4, mục 1)
`linking/data_facts.py` đếm dòng, doanh thu và số lượng của `v_sales` trong từng kỳ đã giải (kết nối chỉ đọc), kết quả nằm ở
`flags["period_stats"]` (danh sách theo thứ tự nhắc, `None` = không biết, không bao giờ chặn). Chỉ truy vấn khi câu hỏi dùng dữ liệu bán hàng,
thuộc nhóm `top1/bottom1/date_of_max/avg/compare_percent` và kỳ chính nằm trong phạm vi dữ liệu. Gate (`_data_reason`) chặn `unanswerable` khi:
- `top1/bottom1/date_of_max/avg` mà kỳ chính không có dòng bán hợp lệ nào;
- `compare_percent` mà kỳ so sánh có doanh thu (hoặc số lượng, nếu metric là `quantity`) bằng 0 (mẫu số 0).

`topN` trên kỳ rỗng vẫn trả `[]`, tổng và đếm vẫn trả `0`: không bị chặn. Quy ước này lấy từ bộ sinh (`synth/src/answers.py`: `_growth`, `_unans`);
chưa có xác nhận từ luật chấm chính thức, và train hiện không có câu nào thuộc nhóm này nên chưa đo được lợi ích.

## Lợi nhuận cần giá vốn của từng sản phẩm đã bán (Phase 4, mục 2)
Câu hỏi **lợi nhuận** bị chặn khi có SKU đã bán trong kỳ chính mà không có lô nhập nào có giá
(`purchase_date <= as_of`, `qty > 0`, `unit_cost` khác NULL). `has_cost` chỉ nói "có ít nhất một giá vốn" nên không đủ; kiểm tra theo từng SKU nằm ở
`linking/data_facts.py::uncosted_skus` (`flags["uncosted_skus"]`, tối đa 5 SKU để ghi log, `None` = không biết), lý do: "Thiếu lô có giá nhập cho một số sản phẩm đã bán trong kỳ."
Chỉ chạy khi metric là `profit` và `has_cost` là `True` (thiếu hẳn giá vốn vẫn đi theo `missing_capability`). Bộ sinh coi giá nhập rỗng là 0
còn ta coi là chưa biết; hai cách chỉ khác nhau khi lô có giá rỗng từng phần, ca không có trong train.
Các kiểm tra nhất quán khác (`consistency:*`, xem [02_ingest_profile.md](02_ingest_profile.md)) chỉ ghi nhận, không bao giờ chặn.
