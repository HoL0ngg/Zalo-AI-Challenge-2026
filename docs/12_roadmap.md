# 12. Lộ trình và rủi ro

## Lộ trình gợi ý
1. **Khung chạy được** (mock): ingest, IO, time guard, scorer, test, Docker khung.
2. **Baseline**: LLM sinh SQL một lần, không linking nâng cao; đo trên train.
3. **Temporal Resolver + Normalizer** hoàn chỉnh (lợi ích lớn, dễ kiểm thử).
4. **Entity/Schema Linking** + đo recall@K theo loại nhiễu.
5. **Self-repair + N ứng viên + Voting**, hiệu chỉnh ngưỡng abstain.
6. **Answerability Gate**.
7. **Dữ liệu tự sinh** để mở rộng benchmark và few-shot; thử LoRA bằng rejection sampling.
8. **Tối ưu thông lượng** (vLLM, data parallel, prefix cache) để đảm bảo < 6 giờ.
9. **Đóng băng** mô hình, kiểm tra tái lập và quy trình nộp Docker.

## Rủi ro chính
| Rủi ro | Giảm thiểu |
|---|---|
| Nối sai thực thể | Đo recall@K, gộp alias, fuzzy có ngưỡng |
| Rulebook khác giữa split | Đọc và tham số hóa rulebook của split, test với rulebook biến thể |
| Loại hình kinh doanh mới | Không hard-code ngành; dùng dữ liệu tự sinh có loại chưa thấy |
| Vượt thời gian 6 giờ | Time guard, chế độ nhanh, đo tốc độ sớm |
| Kết quả không tái lập | Seed, temperature 0, tie-break cố định, vote theo kết quả |
| Vượt ngân sách 15B | Kiểm tra tự động trong code |
| Sai `type` đáp án | Formatter và test theo từng type |
| Lỗi môi trường Blackwell/CUDA | Dùng đúng base image, thử sớm trên máy tương đương |

## Câu hỏi cần làm rõ với luật chính thức
- Hình phạt sai so với abstain và unanswerable (quyết định ngưỡng).
- Có yêu cầu nộp mã huấn luyện riêng không.
- Base image Docker chính xác.
