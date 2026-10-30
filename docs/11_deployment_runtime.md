# 11. Triển khai và vận hành

## Docker
- Base image có CUDA ≥ 12.8 (dùng image chính thức theo Docker guideline của BTC).
- Chứa: source code (huấn luyện và suy luận), trọng số mô hình, `predict.sh`, README.
- Cài đặt phụ thuộc **lúc build**; không `pip install`/tải mô hình lúc chạy.
- Đặt `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`. Container chạy không mạng.

## predict.sh
1. Đọc test từ `/data`, ghi `/result/submission.jsonl` và `/result/logs/`.
2. Đặt seed và biến môi trường offline.
3. Gọi `python -m datamate.cli run --data-dir /data --result-dir /result`.
4. Luôn thoát an toàn sau khi flush, in tóm tắt (số câu đã trả lời / unanswerable / abstain / thời gian).

## Time guard
- Ngân sách tổng (mặc định ~5h30m, chừa biên an toàn dưới 6h, đã tính thời gian nạp mô hình).
- Theo dõi tốc độ trung bình; khi thời gian còn lại không đủ → các câu còn lại ghi `abstain` ngay.
- Có thể giảm N ứng viên/vòng sửa khi gần hết giờ (chế độ nhanh).

## Resume
Nếu chạy lại, bỏ qua các id đã có trong `submission.jsonl` (không trùng dòng).

## Logs
Mỗi câu một bản ghi: id, câu gốc và câu chuẩn hóa, khoảng thời gian đã giải, thực thể nối, code sinh ra, kết quả thực thi, kết quả bỏ phiếu, đáp án cuối, thời gian. BTC dùng log để đối chiếu khi hai lần chạy khác nhau.

## Danh sách kiểm tra trước khi nộp
- [ ] Tổng tham số ≤ 15B, README khai báo đủ mô hình.
- [ ] Chạy offline thành công (container không mạng).
- [ ] Toàn bộ test chạy trong < 6 giờ trên máy tương đương (kể cả nạp mô hình).
- [ ] `/data` chỉ đọc vẫn chạy được.
- [ ] Hai lần chạy lệch ≤ 0,03 trên dev.
- [ ] Không có hard-code theo id; test no-hardcoding pass.
- [ ] Log đầy đủ trong `/result/logs/`.
