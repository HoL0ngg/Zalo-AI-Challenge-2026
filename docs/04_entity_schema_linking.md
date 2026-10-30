# 04. Bước 3 — Entity & Schema Linking

## Mục tiêu
Nối cụm từ trong câu hỏi với **giá trị và cột có thật** trong dữ liệu. Đáp án chấm khớp tuyệt đối nên bước này quyết định phần lớn độ chính xác.

## 3a. Chuẩn bị chỉ mục (một lần mỗi business)
- Lấy mọi giá trị khác nhau của các cột dạng tên.
- Tạo các dạng: NFC, chữ thường, bỏ dấu, bỏ ký tự đặc biệt, token.
- Dựng chỉ mục: tra chính xác, n-gram/BM25, (tùy chọn) vector embedding.
- **Gộp biến thể** của cùng một thực thể ("Sting dâu 330ml", "sting dau 330 ml", mã `SP0042`) thành thực thể chuẩn + danh sách alias.

## 3b. Entity Linking
1. **Phát hiện mention**: loại từ khóa chức năng và cụm thời gian đã giải; tạo n-gram ứng viên; nhận mẫu mã SP, số điện thoại, kích cỡ ("330ml", "50kg").
2. **Sinh ứng viên** song song: khớp chính xác → khớp bỏ dấu → fuzzy (rapidfuzz) → BM25/n-gram → embedding (bổ trợ).
3. **Chấm điểm**: gộp điểm các phương pháp; cộng điểm khi khớp số/đơn vị/thương hiệu/ngữ cảnh cột; giữ top-K.
4. **Xử lý mơ hồ**:
   - Một ứng viên vượt trội → chọn.
   - Nhiều ứng viên sát điểm → đưa tất cả cho LLM kèm ngữ cảnh, hoặc coi là nhóm (IN/LIKE).
   - Không ứng viên đạt ngưỡng → gắn cờ `missing_entity` cho Gate.
5. **Tie-break ổn định** (theo thứ tự cố định) để đảm bảo tái lập.

## 3c. Schema Linking
- Chọn bảng/cột cần dùng: "bán được" → số lượng dòng hàng; "tuần rồi" → cột ngày đơn; "doanh thu" → đơn giá × số lượng − giảm giá dòng...
- Dùng từ điển đồng nghĩa (doanh thu/tiền bán...), tên cột viết tắt (SL, DT), README.
- Gợi ý đường JOIN từ quan hệ khóa.

## Đầu ra: `LinkResult`
```json
{"entities":[{"mention":"sting dâu","column":"products.ten_sp","matched":"Sting dâu 330ml",
  "alias_ids":["SP0042"],"score":0.93,"alternatives":[["Sting dâu 250ml",0.71]]}],
 "schema":{"tables":["order_lines","orders","products"],"metric":"so_luong","date_col":"orders.ngay"},
 "flags":{"ambiguous":false,"missing_entity":false}}
```

## Lỗi thường gặp
Khớp quá tay (bánh quy ↔ bánh quế); từ chung chung (danh mục hay tên SP?); chia nhỏ số liệu vì không gộp biến thể; trùng tên khách; thực thể không tồn tại nhưng bị ép khớp; kết quả khác nhau giữa hai lần chạy do tie-break.

## Đo lường
Với dữ liệu tự sinh: top-1 accuracy và recall@K theo từng loại nhiễu. Thường là điểm nghẽn lớn nhất của hệ thống.
