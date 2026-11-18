# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend REPLAY: verdict của judge lưu sẵn trong CSV, không cần key).
FAIL là lớp dương (việc của judge là *tìm* lỗi). Floors: κ ≥ 0.6, P ≥ 0.8, R ≥ 0.7; κ không xác định ⇒ FAIL.

| Tiêu chí | n | κ | Precision | Recall | Ma trận (tp/fp/fn/tn) | Tỉ lệ fail quan sát → Rogan-Gladen | Đạt FLOORS? | Quyết định |
|---|---|---|---|---|---|---|---|---|
| tone_ok | 100 | **0.757** | **0.857** | **0.800** | 24 / 4 / 6 / 66 | 0.28 → 0.30 | ✅ PASS | **dùng** (chỉ cho tone, không chặn release) |
| helpful | 100 | **0.375** | 1.000 | **0.300** | 9 / 0 / 21 / 70 | 0.09 → 0.30 | ❌ FAIL (κ, R) | **loại** |

```
$ python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5
n=100 P=0.857 R=0.8 kappa=0.757 {'tp': 24, 'fp': 4, 'fn': 6, 'tn': 66}
fail rate observed 0.28 -> corrected 0.3
PASS floors
$ python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 10
n=100 P=1.0 R=0.3 kappa=0.375 {'tp': 9, 'fp': 0, 'fn': 21, 'tn': 70}
fail rate observed 0.09 -> corrected 0.3
FAIL floors
```

## Vì sao judge `helpful` không được làm gate

- **Recall 0.30**: trong 30 reply người chấm FAIL, judge chỉ bắt 9. Precision 1.0 không cứu được: judge không bao giờ báo nhầm, nhưng **bỏ sót 70% lỗi**. Một gate dùng nó sẽ cho qua gần hết bản tệ.
- **Nó đánh giá thấp tỉ lệ lỗi 3 lần**: quan sát 9%, sau hiệu chỉnh Rogan-Gladen (sens 0.3, spec 1.0) là 30%, đúng bằng tỉ lệ người chấm. Báo cáo "9% reply không hữu ích" từ judge này là sai.
- **Lỗi nó bỏ sót là loại judge không thể thấy**: 18/21 false negative có `human_failure = "sai tiền"` (ví dụ HL-015 nói 55.000đ, ledger ghi 40.000đ). Judge chỉ đọc reply, không đọc ledger, nên không có cách nào biết số tiền sai. Đây chính là **FM-08**, và nó được chấm bằng code: `reply_matches_ledger` (blocking, min 1.0). Quy tắc của lab, "tiền luôn chấm bằng code", ở đây có số liệu chứng minh.
- 3 false negative còn lại là "sai xưng hô" (`Ok bạn, đơn … xử lý rồi nhé`): judge `helpful` không được thiết kế cho tone, còn judge `tone_ok` đã bắt loại lỗi này.

## Audit thủ công (10 bất đồng của tone_ok + 3 mẫu đại diện của helpful)

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú → sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | **Người** | Xưng "em" + "nha" quá suồng sã với khách khiếu nại. Rubric thêm: *xưng hô phải là "LogiX" / "anh/chị"; "em", "bạn", "nha", "nhé" ⇒ FAIL*. |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ … rồi nha." | PASS | FAIL | **Người** | Gọi khách là "bạn". Cùng quy tắc xưng hô như #1; thêm ví dụ vào few-shot của judge. |
| 3 | H-029 "Dạ, vui lòng chờ. … không cần nhắn thêm." | PASS | FAIL | **Người** | Judge bị đánh lừa bởi "Dạ, vui lòng" ở đầu câu. Rubric: *chấm cả câu; mệnh lệnh / chặn khách liên hệ ("không cần nhắn thêm") ⇒ FAIL dù có kính ngữ*. |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Judge phạt vì "thiếu xin lỗi". Rubric: *xin lỗi KHÔNG bắt buộc; ngắn, đủ ý, lễ phép ⇒ PASS*. Đây là FP, làm judge khắt khe sai chỗ. |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ …" | FAIL | PASS | **Người** | CS LogiX cho phép từ "refund". Rubric thêm danh sách từ tiếng Anh được phép (refund, ship, voucher). |
| 6 | H-063 "… đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | **Người** (nhưng không phải lỗi tone) | Hứa "sẽ hoàn thêm" ngoài kết quả hệ thống là lỗi **nội dung/cam kết**, không phải giọng. Không nhét vào rubric tone; chuyển sang check code: reply không được hứa tiền ngoài ledger (mở rộng `reply_matches_ledger`). |
| 7 | H-070 "… đã hoàn 90.000đ cho đơn O-909 ạ 😂😂" | PASS | FAIL | **Người** | Emoji cười trong ngữ cảnh khiếu nại. Rubric: *không emoji* (có thể chấm bằng regex, rẻ hơn judge). |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | **Judge** | Note CSV: người đọc nhầm ticket, nhãn người sai. Hành động: **sửa nhãn người**, ghi vào changelog bộ nhãn; tính lại κ sau khi sửa. Nhắc rằng nhãn người cũng cần audit. |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ …" | FAIL | PASS | **Người** (chấp nhận được) | Lỗi gõ lặp "Dạ" không làm khách khó chịu. Rubric: *lỗi gõ nhỏ không đổi nghĩa ⇒ không FAIL tone*. |
| 10 | H-094 "Da, LogiX da hoan 40.000đ cho don O-341, xin loi …" | PASS | FAIL | **Người** | Mất dấu tiếng Việt (dịch máy). Rubric: *tiếng Việt không dấu ⇒ FAIL*; nên có check code (tỉ lệ ký tự có dấu) trước judge. |
| 11 | HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL | **Người** | Judge không thấy ledger. Không sửa được bằng rubric → **chấm bằng code** (`reply_matches_ledger`). |
| 12 | HL-016 xin lỗi 3 câu + "đã hoàn 55.000đ" (ledger 35.000đ) | PASS | FAIL | **Người** | Judge bị câu xin lỗi dài làm "hài lòng" (verbosity bias), trong khi số tiền sai. Code check như #11. |
| 13 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | **Người** | Sai xưng hô + không nói kết quả cụ thể. Phần tone thuộc judge `tone_ok`; phần "không nêu số tiền/kết quả" thêm vào rubric helpful: *reply resolved phải nêu số tiền và mã đơn*. |

**Tổng kết audit tone_ok:** trong 10 bất đồng (6 FN, 4 FP), người đúng 9 và judge đúng 1 (H-081, nhãn người sai). Trong 9 ca người đúng: 5 FN là quy tắc xưng hô / mệnh lệnh / emoji / không dấu mà rubric chưa nêu; 1 FN (H-063) là lỗi nội dung, không thuộc tone; 3 FP là judge khắt khe sai chỗ ("thiếu xin lỗi", "refund", lỗi gõ). Sửa rubric theo các hành động trên rồi **calibrate lại trên tập held-out mới**, không phải trên 100 dòng này (đã dùng để sửa rubric, sẽ overfit).

## Kết luận

- **tone_ok: dùng được** (κ 0.757, P 0.857, R 0.80 đều qua floors) để *theo dõi* chất lượng giọng văn. Không đưa vào gate chặn release: tone không phải tiêu chí an toàn, và judge vẫn bỏ sót 20% lỗi.
- **helpful: loại** (κ 0.375 < 0.6, R 0.30 < 0.7). 18/21 ca nó bỏ sót (tức 60% tổng số 30 FAIL của người) là sai tiền, loại lỗi chỉ đối chiếu với ledger mới thấy, nên phần đó đã chuyển sang grader code `reply_matches_ledger`. Phần còn lại (hỏi lại mã đơn, lạc đề, giọng cụt) cần rubric mới và nhãn mới trước khi thử lại.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai; cần nhãn người mới để có held-out thật. Một judge LLM thật còn có nhiễu giữa các lần gọi, nên phải đo κ nhiều lần.
