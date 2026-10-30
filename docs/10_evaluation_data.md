# 10. Đánh giá và dữ liệu

## Scorer nội bộ
`eval/scorer.py` mô phỏng cách chấm chính thức: khớp theo `type`; number khớp chính xác; percent làm tròn 2 chữ số và đúng dấu; string chuẩn hóa (NFC, chữ thường, ký tự không phải chữ/số → khoảng trắng, gộp khoảng trắng, giữ dấu) và so với alias; list có thứ tự; table; đếm đúng/sai/abstain.

## Đo theo từng bước (để biết lỗi nằm ở đâu)
| Bước | Chỉ số |
|---|---|
| Normalizer | tỉ lệ khôi phục đúng câu chuẩn theo loại nhiễu |
| Temporal | độ chính xác khoảng ngày |
| Entity linking | top-1 accuracy, recall@K |
| Gate | precision/recall của unanswerable |
| CodeGen | tỉ lệ code chạy được, tỉ lệ ra đúng đáp án |
| Voting | độ chính xác theo mức đồng thuận (hiệu chỉnh ngưỡng abstain) |
| Toàn hệ thống | accuracy, abstain rate, thời gian trung bình/câu |

## Dữ liệu
1. **Train của BTC** (có `answers.jsonl`): nguồn chính để đo và few-shot.
2. **Dữ liệu tự sinh** (xem prompt bộ sinh dữ liệu): nhiều loại hình, nhiễu teencode/typo, đáp án tính bằng code; kèm một split "loại hình chưa thấy".
3. **Dữ liệu công khai** (Instacart, Superstore, Online Retail...) để lấy cấu trúc; kiểm tra giấy phép.
4. Cấm dùng public/private test để huấn luyện hay thu thập đáp án.

## Quy trình
Chia dev riêng; không tinh chỉnh ngưỡng trên dữ liệu đã dùng để huấn luyện; theo dõi lỗi theo nhóm (thời gian, thực thể, rulebook, kiểu đáp án) và sửa nhóm lỗi lớn nhất trước.

## Tái lập
Chạy hai lần liên tiếp phải cho kết quả gần như giống nhau (ràng buộc ≤ 0,03). Có test so sánh hai lần chạy.
